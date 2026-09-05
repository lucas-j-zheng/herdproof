"""One-to-one box agreement with provisional source annotations."""
from __future__ import annotations


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union > 0 else 0.


def matched_count(predictions, truth, threshold=.5):
    # Iterative augmenting paths: maximum-cardinality matching without recursion limits in dense images.
    edges = [sorted((j for j, box in enumerate(truth) if iou(p, box) >= threshold),
                    key=lambda j: -iou(p, truth[j])) for p in predictions]
    assigned = {}
    for origin in range(len(predictions)):
        queue, previous, seen_truth = [origin], {}, set()
        matched = False
        for p in queue:
            for g in edges[p]:
                if g in seen_truth:
                    continue
                seen_truth.add(g)
                if g not in assigned:
                    assigned[g] = p
                    while p in previous:
                        old_g, parent = previous[p]
                        assigned[old_g] = parent
                        p = parent
                    matched = True
                    break
                child = assigned[g]
                if child not in previous and child != origin:
                    previous[child] = (g, p)
                    queue.append(child)
            if matched:
                break
    return len(assigned)


def summarize(rows):
    n = len(rows)
    tp = sum(r["matched"] for r in rows)
    predicted = sum(r["predicted"] for r in rows)
    annotated = sum(r["annotated"] for r in rows)
    return {"images": n, "groups": len({r["group"] for r in rows}), "matched": tp,
            "annotated": annotated, "predicted": predicted,
            "unmatched_predictions": predicted - tp, "missed_annotations": annotated - tp,
            "annotation_precision": tp / predicted if predicted else 0.,
            "annotation_recall": tp / annotated if annotated else None,
            "count_mae_vs_annotations": sum(abs(r["predicted"] - r["annotated"]) for r in rows) / n if n else None,
            "count_bias_vs_annotations": (predicted - annotated) / n if n else None,
            "annotation_disagreements": predicted + annotated - 2 * tp}
