# Handoff: reproducible walkable cow worlds

The reproducible HerdProof world pipeline is implemented and verified in:

`/Users/lucas/dev/personal-projects/herdproof`

## Goal

Given a drone photograph, frozen cattle detections, terrain and camera inputs,
and saved review corrections, generate the same walkable scene every time.
Each displayed cow must have a stable observation ID, the correct original
photo/crop, an approximate coat color, an estimated or reviewed direction,
and a position projected onto the terrain. Demonstrate two different fields
using the same core code, changing only input/configuration files.

Reproducible does not mean fully automatic. Camera alignment, mask corrections,
head selection and feature annotations may require review, provided every
decision is saved. Rebuilding must not depend on Codex making new decisions,
new inference, retraining, downloads or another photogrammetry run.

## Read first and reuse existing work

- `validation/world-viewer/README.md`: implemented CLI, inputs and limitations.
- `validation/REPRODUCIBLE_WORLD_PLAN.md`: original detailed design. Its opening
  statement that the commands do not exist is historical; inspect current code.
- `scripts/terrain/world.py`, `world_core.py`, `world_geometry.py`,
  `world_build.py`, `world_tests.py`, and `world_validate.py`.
- `validation/world-viewer/`: reusable viewer and persistent review editor.
- `validation/worlds/jalogny-south/` and `validation/worlds/jalogny-north/`:
  two configured examples with saved inputs, reviews, builds and evidence.

Preserve the older `validation/terrain-demo/` and unrelated work. Follow
applicable AGENTS.md instructions and existing dependency lockfiles. The
working tree contains unrelated staged and unstaged changes, including training
work. Do not reset, stage, commit or publish those changes.

## What should be reproducible

1. **Evidence and IDs.** Preserve source image hashes, detector provenance,
   boxes, confidence, exact crops and stable observation IDs. Bind corrections
   to their input snapshot. An observation ID is not a verified animal identity
   across flights.
2. **Shared cow asset and appearance.** Reuse one versioned 3D cow model with
   independent per-cow coat parameters. Estimate color from cow foreground
   pixels, with saved mask/color overrides. Preserve eyes, hooves, muzzle and
   surface detail. Exact coat patterns and unseen markings are out of scope.
3. **Direction.** Estimate a body axis from the mask; keep the ambiguous head
   end separate. Save rotation, head-click and 180-degree-flip corrections.
   Convert image direction through the camera/terrain mapping into world yaw.
4. **Placement and ground.** Use a calibrated camera and measured elevation
   raster. Reuse the same terrain triangles for rendering, placement and
   collision. Project imagery onto the ground and save cleanup masks that
   remove photographed cows beneath their 3D replacements.
5. **Vegetation and features.** Elevation data supplies terrain shape. Imagery
   can suggest grass-covered areas and visible feature locations, but it does
   not establish grass height/species or unseen geometry. Save procedural
   grass type, density, height and seed; save optional fence/tree annotations.
   Keep measured inputs and approximate decoration explicit.
6. **Review and replay.** Persist additions, rejections, duplicates, masks,
   colors, anchors, directions and vegetation settings. Provide prepare,
   review, build and verify commands, pinned dependencies, cached inputs and
   a private portable source/input bundle with hashes and asset licenses.

## Current progress and remaining plan

The CLI and editor already exist. Saved builds display 18 cows in the south
pasture and 15 in the north pasture. Ten Python tests pass in the recorded log.
Existing evidence covers repeat builds, geometry/material checks, browser
walking and a persisted single-cow color/heading edit. Treat these as evidence
to inspect, not proof that later edits were validated.

Update after implementation continuation: JAL-012 and JAL-020 now have saved
foreground corrections and white colors measured from those pixels. Both
fields pass fresh deterministic builds and an extracted private bundle has
passed full output-manifest comparison. Final browser checks also passed:
minimap selection, walking, greeting, hoof contact, boundaries, corrected
coat appearance and persisted vegetation edits, including zero vegetation.
Pasture settings were restored without changing any cow reviews. See
`validation/worlds/evidence/completion-audit.json` for the current audit and
`validation/worlds/deliverables/extracted-replay-verification.json` for the
exact verified archive hash. The checklist below records the work sequence;
use current evidence rather than repeating completed steps.

Work sequence:

1. Audit the actual implementation against the goal. Inspect accepted south
   observations JAL-012 and JAL-020: their original automatic masks had zero
   foreground pixels and fallback brown coloring. Their saved corrections are
   now verified in `jalogny-south/evidence/appearance-corrections.json`.
2. Freeze final source/configuration changes. Verify cache invalidation covers
   relevant algorithms and inputs. Rebuild both examples and rerun the tests
   and real-field replay audit against the final code.
3. Reload the final viewers and check correct crops/IDs, selection, minimap,
   walking, hoof contact, boundaries and saved review edits. Refresh browser
   evidence when changes affect the scene. Restart stale local review servers
   if needed; do not rely on an old browser or loaded Python module.
4. Create the private versioned ZIP with the existing `package` command.
   Extract it into a fresh directory and actually rebuild and verify both
   fields offline using a prepared Python environment. Check all archive
   hashes and confirm no inputs resolve back into the original workspace.
   Repeat extraction only if the final source or packaged inputs change; the
   linked extraction report identifies the archive that was actually tested.
5. Deliver the archive, reproduction commands, example configurations, final
   verification evidence and candid limitations. Correct any documentation
   that describes intended work as already verified.

## Completion criteria

- Two fresh builds per field preserve IDs, population, colors, headings,
  positions, crops and source links.
- Editing one cow affects only that observation and survives reload/rebuild.
- Invalid inputs, mismatched reviews and unsupported geometry fail clearly.
- Rendering and physics agree; walking, selection and minimap work.
- Both fields use identical core source code.
- An extracted private bundle rebuilds without original-workspace inputs.
- Document measured data, manual preparation and visual approximations.

Both examples are separate pastures on the same farm and predominantly white
cattle. They do not establish broad coat-color or geographic generalization.
The north camera has no independent north survey control. Some head directions
remain provisional. Report those limits, and do not confuse projection
self-consistency with surveyed position accuracy. Earlier manual preparation
was not fully timed; report measured replay timing separately.

Do not retrain models, reconstruct unique cows, infer persistent animal
identities, reconstruct exact vegetation, or silently change the repository's
training-only publication policy. Finish the bounded pipeline and its proof
of reproduction before pursuing additional automation.
