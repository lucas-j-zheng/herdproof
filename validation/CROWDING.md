# Crowded-cattle review follow-up

The first reviewer reported two separate problems: the AI misses or merges
bunched cows, and adding a marker can change a nearby one.

## Interface correction

The v1 click handler removed the first marker within 14 screen pixels. At fit
zoom, adjacent cattle can fall inside that radius. This directly prevents marking
both animals, even when they are individually visible.

Interface v2 uses separate Add and Remove tools. Add always creates a marker;
Remove deletes only the nearest marker within 7 screen pixels. Smaller hollow
markers, a visibility toggle, a 1:1 pixel button, and up to 1600% zoom support
inspection. The toolbar remains available while scrolling. Original review data
is preserved; summaries distinguish interface versions and retain the feedback.

Three regression checks cover adjacent additions, nearest-marker removal, and
empty-space clicks. Browser QA also verified adjacent additions, removal, Undo,
and full-resolution zoom. QA does not count as a human measurement.

## Detector probe

The weights and original benchmark are unchanged. A separate, fixed probe tested
two inference adjustments on the existing **five calibration images**, containing
62 supplied annotations. The confidence threshold stayed at 0.5.

| Configuration | Matched labels | Unmatched predictions | Unmatched labels |
|---|---:|---:|---:|
| Current: 1024 px tiles, NMS IoU 0.5 | 48 | 25 | 14 |
| Less suppression: 1024 px tiles, NMS IoU 0.7 | 48 | 29 | 14 |
| Closer crops: 512 px tiles enlarged to 1024, NMS IoU 0.7 | 25 | 32 | 37 |

Neither adjustment improved this check. Neither was deployed. These are
provisional comparisons with incomplete source labels, not a validated crowded
scene benchmark or proof that these approaches cannot work with other training.

The detector's crowded-animal problem remains unresolved. The next defensible
model experiment needs independently checked crowded scenes, consistent handling
of partially visible animals, and a fresh flight-separated test set. More compute
alone does not repair missing annotations or establish reliable counts.

Run `.venv/bin/python scripts/probe_crowded_cattle.py` to reproduce the local probe.
Its frozen configuration and raw outputs are in `runs/crowding-probe/`.
