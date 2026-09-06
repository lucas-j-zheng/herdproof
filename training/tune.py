"""Bounded fine-tuning with explicitly reviewed, training-only background crops."""
from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from training.common import (PACKAGE, code_fingerprint, configure_runtime, cuda_environment,
                             digest, exclusive_lock, load_config, read_json, verify_prepared, write_json)
from training.evaluate import predict_sources, score
from training.run import training_arguments
from training.runtime import (TrainingMonitor, checked_trainer, read_recovery,
                              restore_recovery, validate_checkpoint)


def validate_negative_record(item, catalog):
    row = catalog[item["source_id"]]
    if row["split"] != "train" or item["group"] != row["group"]:
        raise ValueError("Supplemental negatives must belong to the frozen training split")
    if item["review"] != "accepted_no_visible_cattle":
        raise ValueError("Unreviewed negative crop")
    if item["source_sha256"] != row["image_sha256"]:
        raise ValueError("Negative source identity changed")
    x, y, size = item["x"], item["y"], item["size"]
    if any(type(v) is not int for v in (x, y, size)) or size != 1024:
        raise ValueError("Expected integer native-1024 crop coordinates")
    if x < 0 or y < 0 or x+size > row["width"] or y+size > row["height"]:
        raise ValueError("Negative crop outside source")
    for a, b, c, d in row["boxes"]:
        if min(x+size,c*row["width"]) > max(x,a*row["width"]) and min(y+size,d*row["height"]) > max(y,b*row["height"]):
            raise ValueError("Negative crop intersects an annotated cow")
    return row


def verify_negatives(root, prepared, source):
    from PIL import Image, ImageChops
    manifest = read_json(root / "manifest.json")
    catalog = {r["id"]: r for r in read_json(prepared / "catalog.json")}
    seen, images = set(), []
    for item in manifest["crops"]:
        row = validate_negative_record(item, catalog)
        key = (item["source_id"], item["x"], item["y"])
        if key in seen:
            raise ValueError("Duplicate reviewed crop")
        seen.add(key)
        image, label = (root / item[k] for k in ("image", "label"))
        if not image.resolve().is_relative_to(root.resolve()) or not label.resolve().is_relative_to(root.resolve()):
            raise ValueError("Negative path escapes manifest root")
        if digest(image) != item["image_sha256"] or label.read_text().strip():
            raise ValueError("Negative image changed or label is not empty")
        original_path = source / row["image"]
        if digest(original_path) != row["image_sha256"]:
            raise ValueError("Original negative source changed")
        with Image.open(original_path) as raw, Image.open(image) as crop:
            expected = raw.convert("RGB").crop((item["x"], item["y"], item["x"]+1024, item["y"]+1024))
            actual = crop.convert("RGB")
            if actual.size != (1024,1024) or ImageChops.difference(expected,actual).getbbox() is not None:
                raise ValueError("Negative pixels do not match the documented source crop")
        images.append(image.resolve())
    if not images:
        raise ValueError("No reviewed negatives")
    return images


def write_tuning_yaml(prepared, negatives, folder, *, smoke=False, repeats=8):
    import yaml
    tiles = read_json(prepared / "tiles.json")
    positives = sorted((t for t in tiles if t["split"] == "train"), key=lambda t: (-t["objects"],t["image"]))
    validation = sorted((t for t in tiles if t["split"] == "val"), key=lambda t: t["image"])
    train = [prepared/t["image"] for t in positives]
    val = [prepared/t["image"] for t in validation]
    if smoke:
        train, val = train[:24]+negatives[:8], val[:16]
    else:
        train += negatives*repeats
    if not train or not val:
        raise ValueError("Empty tuning dataset")
    data = {"path": str(folder.resolve()), "names": {0:"cattle"}}
    for split, paths in (("train",train),("val",val)):
        path = folder / (split+".txt")
        path.write_text("".join(str(p.resolve())+"\n" for p in paths))
        data[split] = str(path.resolve())
    target = folder / "dataset.yaml"
    target.write_text(yaml.safe_dump(data))
    return target, len(train)


def train_stage(folder, initial, prepared, negatives, config, recipe, *, smoke=False, device=0):
    folder.mkdir(parents=True, exist_ok=True)
    recipe_path = folder/"recipe.json"
    stage_recipe = {**recipe,"stage":"smoke" if smoke else "fine-tune"}
    if recipe_path.exists() and read_json(recipe_path) != stage_recipe:
        raise ValueError("Cannot resume a changed tuning experiment")
    write_json(recipe_path,stage_recipe)
    if (folder/"complete.json").exists():
        done = read_json(folder/"complete.json")
        if done["recipe_sha256"] != digest(recipe_path) or digest(folder/"fit/weights/best.pt") != done["best_sha256"]:
            raise ValueError("Completed tuning stage changed")
        return done
    recovery = read_recovery(folder,digest(recipe_path))
    if recovery:
        restore_recovery(folder,recovery)
    elif (folder/"fit").exists():
        archive=folder/"interrupted"/uuid.uuid4().hex
        archive.mkdir(parents=True)
        for name in ("fit","timing.json"):
            if (folder/name).exists():
                (folder/name).rename(archive/name)
    data, count = write_tuning_yaml(prepared,negatives,folder,smoke=smoke,repeats=config.get("negative_repeats",8))
    arguments = training_arguments(config,data,folder,"fit",smoke=smoke,device=device,smoke_images=count)
    write_json(folder/"requested-arguments.json",arguments)
    monitor = TrainingMonitor(folder,restored=recovery["monitor"] if recovery else None,device_type="cpu" if device=="cpu" else "cuda")
    started=time.monotonic()
    if not recovery or not recovery["training_finished"]:
        from ultralytics import YOLO
        model=YOLO(str(folder/recovery["last"] if recovery else initial))
        monitor.install(model)
        if recovery:
            def restore_stopper(trainer):
                for key,value in recovery["stopper"].items():
                    setattr(trainer.stopper,key,value)
            model.add_callback("on_pretrain_routine_end",restore_stopper)
            model.train(trainer=checked_trainer(),resume=True)
        else:
            model.train(trainer=checked_trainer(),**arguments)
    best=folder/"fit/weights/best.pt"
    sample=next(t for t in read_json(prepared/"tiles.json") if t["split"]=="val")
    checks=monitor.completion_checks(smoke)
    checks.update(validate_checkpoint(best,prepared/sample["image"],device=device))
    done={"best_sha256":digest(best),"recipe_sha256":digest(recipe_path),"checks":checks,
          "train_samples":count,"elapsed_seconds":time.monotonic()-started,
          "completed_epoch_seconds":sum(r["epoch_seconds"] for r in monitor.state["epoch_times"])}
    write_json(folder/"complete.json",done)
    return done


def select_candidate(candidates, *, recall_floor=.85, dense_recall_floor=.85, group_recall_floor=.80):
    """Select using validation only; do not hide poor recall behind an overall average."""
    eligible = [c for c in candidates
                if c["metrics"]["annotation_recall"] >= recall_floor
                and c["dense_images"]["annotation_recall"] >= dense_recall_floor
                and all(m["annotation_recall"] >= group_recall_floor for m in c["by_group"].values())]
    if not eligible:
        return None
    return min(eligible,key=lambda c:(c["metrics"]["annotation_disagreements"],c["metrics"]["count_mae_vs_annotations"],-c["confidence"],c["variant"],c["nms_iou"]))


def evaluate_tuning(args, config):
    output=args.output/"evaluation"
    output.mkdir(exist_ok=True)
    catalog=read_json(args.prepared/"catalog.json")
    validation=[r for r in catalog if r["eligible"] and r["split"]=="val"]
    checkpoints={"baseline":args.baseline_checkpoint,
                 "fine-tune-best":args.output/"fine-tune/fit/weights/best.pt",
                 "fine-tune-last":args.output/"fine-tune/fit/weights/last.pt"}
    if args.comparison_checkpoint is not None:
        checkpoints["previous-bale-model"] = args.comparison_checkpoint
    recipe={"checkpoints":{name:digest(p) for name,p in checkpoints.items()},
            "tuning_recipe":digest(args.output/"recipe.json"),"code":code_fingerprint(),
            "selection_policies":config["selection_policies"]}
    if (output/"recipe.json").exists() and read_json(output/"recipe.json")!=recipe:
        raise ValueError("Evaluation inputs changed")
    write_json(output/"recipe.json",recipe)
    if (output/"complete.json").exists():
        done=read_json(output/"complete.json")
        for filename,sha in done["outputs"].items():
            if digest(output/filename)!=sha:
                raise ValueError("Evaluation result changed")
        return
    candidates=[]
    predictions={}
    for name,checkpoint in checkpoints.items():
        predictions[name]=predict_sources(checkpoint,args.source,validation,config,output/"cache"/("val-"+name))
        write_json(output/("val-"+name+"-predictions.json"),predictions[name])
        for nms_iou in config["global_nms_candidates"]:
            for confidence in config["confidence_candidates"]:
                report=score(validation,predictions[name],confidence,nms_iou,config)
                candidates.append({"variant":name,"checkpoint_sha256":digest(checkpoint),
                                   "confidence":confidence,"nms_iou":nms_iou,"metrics":report["overall"],
                                   "dense_images":report["dense_images"],"by_group":report["by_group"]})
    write_json(output/"validation-candidates.json",candidates)
    selected={name:select_candidate(candidates,**policy) for name,policy in config["selection_policies"].items()}
    # Publish every validation decision before any test read. An unmet floor is recorded, never relaxed.
    write_json(output/"selection.json",{"policies":config["selection_policies"],"selected":selected})
    files=["validation-candidates.json","selection.json"]
    for name,winner in selected.items():
        if winner is None:
            print("No candidate meets policy:",name,flush=True)
            continue
        write_json(output/(name+"-winner.json"),{**winner,"policy":config["selection_policies"][name]})
        write_json(output/(name+"-validation-report.json"),score(validation,predictions[winner["variant"]],winner["confidence"],winner["nms_iou"],config))
        test=[r for r in catalog if r["eligible"] and r["split"]=="test"]
        test_predictions=predict_sources(checkpoints[winner["variant"]],args.source,test,config,output/"cache"/("test-"+winner["variant"]))
        write_json(output/(name+"-test-report.json"),{**score(test,test_predictions,winner["confidence"],winner["nms_iou"],config),
                   "winner_sha256":digest(output/(name+"-winner.json")),
                   "status":"Previously inspected public test benchmark; diagnostic only, not fresh blind validation."})
        files.extend([name+"-winner.json",name+"-validation-report.json",name+"-test-report.json"])
        print("Validation-selected result:",name,winner,flush=True)
    write_json(output/"complete.json",{"outputs":{name:digest(output/name) for name in files}})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source","prepared","negatives","output","initial-checkpoint"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--initial-sha256",required=True)
    parser.add_argument("--baseline-checkpoint",type=Path)
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--comparison-checkpoint",type=Path)
    parser.add_argument("--comparison-sha256")
    parser.add_argument("--epochs",type=int,default=30)
    parser.add_argument("--patience",type=int,default=10)
    parser.add_argument("--lr0",type=float,default=.0002)
    parser.add_argument("--negative-repeats",type=int,default=4)
    parser.add_argument("--config",type=Path,default=PACKAGE/"config.json")
    args=parser.parse_args()
    if not 1 <= args.epochs <= 100 or not 0 <= args.patience <= 100 or not 0 < args.lr0 <= .001 or not 1 <= args.negative_repeats <= 8:
        parser.error("Invalid bounded training settings")
    if (args.baseline_checkpoint is None) != (args.baseline_sha256 is None) or (args.comparison_checkpoint is None) != (args.comparison_sha256 is None):
        parser.error("Every optional checkpoint must have an explicit SHA256")
    args.baseline_checkpoint=args.baseline_checkpoint or args.initial_checkpoint
    args.baseline_sha256=args.baseline_sha256 or args.initial_sha256
    for key,value in vars(args).items():
        if isinstance(value,Path):
            setattr(args,key,value.resolve())
    configure_runtime(args.output/".cache")
    with exclusive_lock(args.output/".tuning.lock"):
        environment=cuda_environment()
        verify_prepared(args.prepared,args.config)
        if digest(args.initial_checkpoint)!=args.initial_sha256:
            raise ValueError("Initial cattle checkpoint changed")
        if digest(args.baseline_checkpoint)!=args.baseline_sha256:
            raise ValueError("Evaluation baseline changed")
        if args.comparison_checkpoint is not None and digest(args.comparison_checkpoint)!=args.comparison_sha256:
            raise ValueError("Comparison checkpoint changed")
        negatives=verify_negatives(args.negatives,args.prepared,args.source)
        config={**load_config(args.config),"epochs":args.epochs,"patience":args.patience,"lr0":args.lr0,
                "negative_repeats":args.negative_repeats,
                "confidence_candidates":[.05,.1,.15,.2,.25,.3,.35,.4,.45,.5,.6,.7,.8,.9],"global_nms_candidates":[.3,.5],
                "selection_policies":{
                    "balanced":{"recall_floor":.85,"dense_recall_floor":.85,"group_recall_floor":.80},
                    "high-recall":{"recall_floor":.90,"dense_recall_floor":.90,"group_recall_floor":.85}}}
        recipe={"parent_prepared_sha256":digest(args.prepared/"complete.json"),
                "negative_manifest_sha256":digest(args.negatives/"manifest.json"),
                "initial_checkpoint_sha256":args.initial_sha256,"baseline_checkpoint_sha256":args.baseline_sha256,
                "comparison_checkpoint_sha256":args.comparison_sha256,"config":config,"code":code_fingerprint()}
        if (args.output/"recipe.json").exists() and read_json(args.output/"recipe.json")!=recipe:
            raise ValueError("Existing fine-tune uses a different recipe")
        write_json(args.output/"recipe.json",recipe)
        write_json(args.output/("environment-"+environment["slurm_job_id"]+".json"),environment)
        smoke=train_stage(args.output/"smoke",args.initial_checkpoint,args.prepared,negatives,config,recipe,smoke=True)
        if not all(smoke["checks"].get(k) for k in ("finite_checkpoint","finite_inference","weights_changed")) or smoke["checks"]["post_warmup_steps"]<2:
            raise RuntimeError("Fine-tune smoke did not pass")
        # Restart from the original checkpoint: smoke weights do not seed the experiment.
        train_stage(args.output/"fine-tune",args.initial_checkpoint,args.prepared,negatives,config,recipe)
        evaluate_tuning(args,config)


if __name__=="__main__":
    main()
