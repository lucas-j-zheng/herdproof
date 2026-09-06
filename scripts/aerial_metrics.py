"""Object-level matching and count metrics, with no model dependency."""
from __future__ import annotations
from collections import defaultdict


def iou(a, b):
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - overlap
    return overlap / union if union > 0 else 0.0


def match_boxes(predictions, truth, threshold=0.5):
    """Maximum cardinality one-to-one IoU matching (not count-only agreement)."""
    edges = [sorted((j for j, b in enumerate(truth) if iou(p, b) >= threshold),
                    key=lambda j: -iou(p, truth[j])) for p in predictions]
    assigned = {}
    def augment(p, visited):
        for g in edges[p]:
            if g in visited: continue
            visited.add(g)
            if g not in assigned or augment(assigned[g], visited):
                assigned[g] = p
                return True
        return False
    for p in range(len(predictions)): augment(p, set())
    matches = sorted((p, g) for g, p in assigned.items())
    matched_p = {p for p, _ in matches}
    return {"matches": matches,
            "fp_indices": [p for p in range(len(predictions)) if p not in matched_p],
            "fn_indices": [g for g in range(len(truth)) if g not in assigned]}


def evaluate(record, predictions, threshold):
    selected = [p for p in predictions if p[4] >= threshold]
    matched = match_boxes([p[:4] for p in selected], record["boxes"])
    tp, fp, fn = len(matched["matches"]), len(matched["fp_indices"]), len(matched["fn_indices"])
    return {"id": record["id"], "flight": record["flight"], "split": record["split"],
            "truth": len(record["boxes"]), "predicted": len(selected),
            "tp": tp, "fp": fp, "fn": fn, "error": len(selected)-len(record["boxes"]),
            "correction_operations": fp+fn, "matching": matched, "predictions": selected}


def aggregate(rows):
    n = len(rows)
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    negatives = [r for r in rows if r["truth"] == 0]
    return {"images": n, "flights": len({r["flight"] for r in rows}),
            "annotated_observations": tp+fn, "predicted_observations": tp+fp,
            "tp": tp, "fp": fp, "fn": fn,
            "precision": tp/(tp+fp) if tp+fp else None,
            "recall": tp/(tp+fn) if tp+fn else None,
            "count_mae": sum(abs(r["error"]) for r in rows)/n if n else None,
            "count_bias": sum(r["error"] for r in rows)/n if n else None,
            "exact_count_images": sum(r["error"] == 0 for r in rows),
            "exact_count_rate": sum(r["error"] == 0 for r in rows)/n if n else None,
            "correction_operations": fp+fn,
            "correction_operations_per_annotated_animal": (fp+fn)/(tp+fn) if tp+fn else None,
            "negative_images": len(negatives),
            "negative_images_with_false_alarms": sum(r["predicted"] > 0 for r in negatives)}


def by_flight(rows):
    groups = defaultdict(list)
    for row in rows: groups[row["flight"]].append(row)
    return {flight: aggregate(items) for flight, items in sorted(groups.items())}
