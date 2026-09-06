**Reproducible cow worlds — implementation plan**

Prepared 2026-09-06 from the existing local terrain viewer and preprocessing code. This is the original design plan; the implementation now exists. See `world-viewer/README.md` for the actual commands and `worlds/evidence/completion-audit.json` for verification. The first release provides repeatable scene construction with saved review inputs. The detailed geometry cautions in `TERRAIN_PLAN.md` remain relevant.

**Target outcome**

Given an original drone image, a frozen detection result, a terrain/camera configuration, and optional saved corrections, build a portable scene containing the same observation IDs, source crops, estimated colors, orientations, positions, and walking geometry on every replay. Demonstrate the same builder on two fields without editing Python or JavaScript between them. Loading or rebuilding a scene does not require Codex, a language-model call, model retraining, or a new photogrammetry run.

Distinguish three operations: replay cached inputs; prepare a new field with some review; and infer everything automatically. Deliver the first two. Record manual preparation time so automation decisions follow evidence.

**What is worth making repeatable**

| Component | First release | Difficulty and limits |
| --- | --- | --- |
| Photo, crop, ID, confidence and timestamp | Generate directly from each frozen observation and preserve source links | Small; an observation ID does not establish the same animal across flights |
| Cow geometry, materials and animation | Reuse one versioned cow asset; vary coat parameters per cow | Small renderer change; current code shares a fixed cream material |
| Approximate coat color | Estimate from foreground pixels; store raw estimate, quality flags and reviewer override | Moderate extraction work; appearance includes illumination and shadows |
| Body orientation | Suggest an axis from a foreground mask; save head-end review separately | Moderate; an axis has a 180-degree ambiguity |
| Cow position | Project each observation through a supplied calibrated camera onto terrain | Existing algorithm reusable; obtaining a trustworthy camera is the larger preparation step |
| Ground appearance | Project the photograph; remove photographed cow pixels beneath 3D replacements | Existing method reusable; preserve repair masks and flag unresolved photographed animals |
| Terrain, collisions, walking, minimap and selection | Drive all dimensions and transforms from scene data | Mostly refactoring; use identical terrain triangles for rendering and physics |
| Corrections and rebuilds | Save acceptance, mask/color edits, position anchors and heading changes | Essential; a reproducible review file replaces hard-coded choices |
| Trees, fences, grass and sky | Reuse visual defaults; accept optional per-field feature annotations | Approximate decoration is sufficient; recorded obstacles must agree with collisions |

Defer unique 3D cow reconstruction, exact hidden-side markings, age/breed/body-size inference, automatic persistent animal identity, cow behavior simulation, detailed vegetation reconstruction and universal terrain-provider discovery. Simple two-tone coat presets can follow the solid-color version; their unobserved pattern must remain illustrative. Do not require full ODM reconstruction for every scene build.

**Existing work to retain and refactor**

- `scripts/terrain/export_scene.py`: keep projection, crops, texture cleanup and grid export; replace the fixed image, cow-heading/rejection dictionaries, feature coordinates and map dimensions with data inputs. Its use of publisher annotations to clean ground texture must become an explicit optional mask input with provenance; a new field must work without annotation files.
- `scripts/terrain/solve_camera.py`: move the selected image, intrinsics, origin and manually selected landmarks into configuration. Support importing an already solved camera or fitting saved landmarks. Its current ODM reconstruction dependency belongs to preparation, with solved intrinsics cached for replay.
- `scripts/terrain/acquire_terrain.py`: isolate acquisition from building; retain provider metadata, numerical raster validation and checksums. Start with supplied DEMs and the existing IGN route for compatible French fields.
- `validation/terrain-demo/app.js`: load a selected scene URL, per-cow material parameters and configurable extents. Remove fixed 200 m texture/minimap mappings, candidate 18 default selection and per-field title assumptions. Derive camera framing, grass area, spawn checks and boundary colliders from the valid footprint. Material state must be independent per cow while geometry/textures remain reusable.
- `validation/terrain-demo/terrain.js`: retain the canonical grid and triangle sampling convention; extend invalid-cell handling where necessary.
- `validation/terrain-demo/server.mjs`: accept a scene/output directory and persist local review files. The current heading flip only survives within the browser session. Static scene viewing should still work without review-writing endpoints.
- Dependency lockfiles already exist. The root `.gitignore` intentionally excludes the viewer and preprocessing sources from the training publication. Deliver a versioned private source bundle or private companion repository for the scene builder/viewer, with licenses and asset manifests; local ignored files alone are not a reproducible release. Preserve the existing training-only publication policy.

**Cow appearance and direction**

1. Normalize image orientation once and record the pixel transform. Validate detection dimensions and image hash. Save an unchanged source and a padded crop for every observation.
2. Estimate a foreground mask inside the padded crop. Start with the installed OpenCV GrabCut implementation, initialized using the detection rectangle and surrounding background; allow foreground/background brush corrections. This is a baseline to evaluate, not an assumption that every cow segments correctly. Border clipping, neighboring cows, too little foreground and unstable masks must trigger review. OpenCV documents rectangle initialization and corrective foreground/background marks in its [GrabCut tutorial](https://docs.opencv.org/4.12.0/d8/d83/tutorial_py_grabcut.html).
3. Estimate coat color from the mask interior rather than averaging the entire bounding box. Store a robust representative color and a small color distribution, along with visible-pixel count, clipping and mask-quality flags. Do not discard all dark pixels: black coats and shadows need review when ambiguous. Allow a manual swatch override. Label this apparent coat color, not a lighting-independent measurement of fur reflectance.
4. Prepare the shared cow asset once with a coat-region mask and neutral base texture, retaining normal/roughness detail and separate eyes, hooves and muzzle. Apply each cow's coat color only to that region. A colored texture affects the final tint—Three.js describes the map as modulated by the material color—so a neutral base avoids carrying the original coat into every cow. See [MeshStandardMaterial](https://threejs.org/docs/pages/MeshStandardMaterial.html). Share immutable geometry and texture resources, with separate color state per animal.
5. Compute a principal body axis from the foreground mask, with a quality score based on elongation and mask reliability. PCA is an established orientation baseline described in the [OpenCV tutorial](https://docs.opencv.org/4.10.0/d1/dee/tutorial_introduction_to_pca.html). Its application here supplies an undirected axis; it does not identify the head. The current axis-aligned detector rectangle is insufficient for reliable diagonal body orientation.
6. In review, overlay an arrow on the source crop. Allow rotate/drag, click the head, or flip 180 degrees. Store axis status and head-end status separately. Unresolved cows may display a stable provisional direction with an uncertainty indicator. Project axis endpoints through the same camera/terrain transform used for position before computing world yaw.
7. Evaluate a stronger mask or head-keypoint model only if measured review burden warrants it. Freeze its weights, inputs and outputs when added. No external inference service is required for the initial design.

**Input and output contract**

Use one field configuration referencing an immutable input snapshot, with relative paths inside a project bundle. Store field-specific values as JSON; keep the algorithms field-independent.

| File | Contents |
| --- | --- |
| `field.json` | Scene ID, image/detection paths, camera and terrain paths, coordinate convention, asset version, quality mode, feature annotations and visual defaults |
| `inputs.json` | Image hashes, original and normalized pixel dimensions, orientation transform, detector/model identity, selected thresholds, terrain/camera sources and hashes |
| `observations.json` | Frozen IDs, source image and box, confidence, mask/color/axis proposals, quality flags and estimation methods |
| `review.json` | Versioned accepted/rejected/added observations, merge references, manual masks, coat overrides, image-space anchors, headings and reviewer metadata |
| `scene.json` | Effective cows, source links, derived positions/yaws, terrain dimensions, valid-area mask, observation coverage, optional obstacles and assumptions |
| `build-manifest.json` | Source-bundle version/hash, dependency lock hashes, asset/input/review hashes, algorithm parameters, seeds, output hashes and validation summary |

Assign IDs at ingestion and preserve them through review; never renumber by current confidence or array position. Bind corrections to an input/observation version. A new inference snapshot must not inherit corrections just because it reuses an index. Keep cross-image tracks and farm tag identities as separate optional fields. Save manual additions with their own IDs and provenance. Automatic proposals remain immutable; review is an overlay.

Require real terrain and a usable camera for the measured-field mode. A separate explicit illustrative mode may use a flat plane and a documented scale assumption; its coordinates and distances must not be presented as surveyed measurements. Never silently substitute a flat scene after alignment failure. Preserve missing terrain and stop walking at unsupported boundaries.

**Pipeline and review loop**

```text
Photo + saved detections + camera/terrain inputs
                    |
          Normalize and assign IDs
                    |
       Masks, coat and axis proposals
                    |
     Saved review: accept, correct, orient
                    |
  Project positions + prepare ground texture
                    |
       Scene bundle + validation report
                    |
       Existing reusable walking viewer
```

Expose four proposed CLI operations: `prepare --config field.json`, `review --config field.json`, `build --config field.json --offline`, and `verify --scene <output>`. The review operation opens the local editor; a build can use existing review or preserve unreviewed flags. Exports with unresolved required geometry errors fail with actionable reports. Build never prompts interactively, silently downloads inputs, or trains a model.

Run detection as an upstream versioned step and accept its saved results through an adapter. Cache masks, camera solves and imagery separately so a coat correction does not rerun inference or photogrammetry. Rebuild only affected outputs; use temporary outputs and atomic completion manifests so interrupted builds are never mistaken for complete scenes. Keep operational timestamps outside deterministic scene content. Target stable semantic outputs in a pinned runtime, not pixel-identical browser screenshots across GPUs.

Texture cleanup must include accepted cows and reviewed duplicate observations. Use a separate cleanup-mask channel for additional photographed cows absent from detections; these masks do not create scene animals. Save synthesized regions and flag remaining ground-image cows during visual review. Do not promise that detected boxes alone remove every photographed animal.

**Implementation order and completion gates**

1. **Replay the existing field.** Extract current manual choices into fixtures, parameterize export and loading, cache camera calibration and freeze assets. Complete when a new output directory reproduces the reviewed population, IDs, poses and source links from only the documented input bundle. Run frozen installs without changing package managers or relaxing the 14-day release-age floor.
2. **Add persistent per-cow appearance and review.** Implement foreground proposals, solid coat colors, body-axis suggestions, review saving and per-cow rendering. Complete when editing one cow's color or heading changes only that cow, survives reload, and reappears after a fresh build.
3. **Prepare a second real field.** Choose suitable imagery with available terrain/reference alignment, preferably including visibly different coats. Keep manual camera picks and feature annotations in configuration. Complete when switching fields requires only configuration/input files and both scenes have reviewed source-to-cow correspondence. A second photo of the same field is a useful intermediate check but does not establish portability to a different field.
4. **Package and demonstrate.** Deliver the private code bundle, dependency locks, asset licenses/checksums, example configurations, review files, expected outputs and a replay guide. Demonstrate offline replay and record cold/warm build time, review time, unresolved cases and actual browser performance. Fresh acquisition and optional reconstruction are timed separately.

Engineering estimate, not measured: existing-field replay is roughly 1–2 focused days; cow appearance/review another 2–4; second-field preparation and packaging another 2–4 if compatible inputs are available. Allow roughly one to two working weeks for the complete demonstration. Earlier estimates of a few days covered a narrower configurable replay, not this full appearance/review/portability scope. Camera/terrain availability and mask failure rates can extend the schedule.

**Verification that matters**

- Two fresh offline builds from identical inputs preserve semantic scene output, accepted population, IDs, material parameters and transforms. Source crops resolve to the correct image/box; no missing asset may silently fall back.
- Changes to detection ordering or snapshot version cannot attach another cow's review. Add/reject/merge/flip/color operations persist through reload and rebuild.
- A fixture with several coat colors verifies independent materials. Review real masked crops for grass/shadow leakage; report color/axis acceptance and correction rates separately. Uniform cream cows alone cannot establish color generalization. Numerical proposal-quality scores are not calibrated probabilities.
- Validate pixel-orientation and normalization transforms, terrain bounds/missing cells, camera direction and the shared render/collision surface. Keep the existing 1 cm collider and 3 cm hoof-contact checks as engineering tolerances. Separately report held-out map-alignment residuals; geometric self-consistency does not establish real-world accuracy.
- Reject skyward/out-of-coverage placement; represent occlusion/failed observations explicitly. Empty scenes, edge detections, neighboring cows and failed spawn attempts must have usable outcomes.
- Visually check both scenes for doubled cows, incorrect source links, directional errors and texture seams. Exercise selection, minimap, walking, obstacle/boundary stops and greetings; report performance at a fixed resolution on the actual machine.
- A new field requires no edits to core source code. This is the central demonstration of repeatability; saving manual inputs is compatible with it.
