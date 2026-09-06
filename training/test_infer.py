import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from training.common import digest, write_json
from training.infer import input_records, load_default_config, predict_image, resolve_checkpoint


class DefaultInferenceTests(unittest.TestCase):
    def test_wrong_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"wrong.pt"; path.write_bytes(b"wrong checkpoint")
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                resolve_checkpoint(load_default_config(),path)

    def test_explicit_checkpoint_location_still_verifies_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"model.pt"; path.write_bytes(b"fixture")
            self.assertEqual(resolve_checkpoint({"checkpoint_sha256":digest(path)},path),path.resolve())

    def test_manifest_input_drops_annotations_and_respects_requested_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            write_json(folder/"manifest.json",{"records":[{"id":"one","image":"one.jpg","image_sha256":"sha","boxes":[[0,0,1,1]]}]})
            record=input_records(folder,["one"])[0]
            self.assertNotIn("boxes",record)
            self.assertEqual(record["id"],"one")
            with self.assertRaisesRegex(ValueError,"not found"): input_records(folder,["missing"])

    def test_native_tiles_class_and_global_merge_match_selected_recipe(self):
        import torch
        from PIL import Image
        calls=[]
        outputs=[[[200,50,300,150,.85,0],[600,50,700,150,.69,0]],[[24,50,124,150,.8,0]]]
        class Model:
            def predict(self,crop,**kwargs):
                self.assert_size=crop.size
                calls.append(kwargs)
                return [SimpleNamespace(boxes=SimpleNamespace(data=torch.tensor(outputs[len(calls)-1])))]
        model=Model(); result=predict_image(model,Image.new("RGB",(1200,1024)),load_default_config())
        self.assertEqual(result["tiles"],2)
        self.assertEqual(len(result["boxes"]),2)  # duplicate removed, low-score raw box retained
        self.assertEqual(result["count"],1)  # default 0.70 cutoff applied to the actual count
        self.assertEqual(model.assert_size,(1024,1024))
        for call in calls:
            self.assertEqual(call["classes"],[0])
            self.assertEqual(call["iou"],.9)
            self.assertEqual(call["imgsz"],1024)
            self.assertFalse(call["augment"])


if __name__=="__main__": unittest.main()
