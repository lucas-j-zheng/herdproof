# Explorable farm demo feasibility — 2026-09-06

Superseded for implementation by [TERRAIN_PLAN.md](/Users/lucas/dev/personal-projects/herdproof/validation/TERRAIN_PLAN.md).
This earlier feasibility note is retained as historical research, not the
implementation plan.

Build a custom terrain-and-cow scene. The aim is to move from a drone image
to an overhead 3D view, select
a cow by a scene-local ID, then walk over and greet that cow while retaining a
link to the source photograph.

## What is available locally

Inspected `validation/runs/finetuned/demo.json`, its original JPEG, and the
existing overlap pipeline. No model inference or paid generation was run.

- The current demo image is `46472379c810`, an ICAERUS Jalogny pasture photograph
  captured on 2023-09-26. It is 5280 × 3956 pixels.
- The saved model output contains 21 candidate cow detections. These are
  normalized axis-aligned boxes plus confidence, not segmentation polygons,
  verified cattle counts, or persistent animal identities.
- The original JPEG contains GPS, camera optics, and DJI camera attitude.
  Gimbal pitch is -89.9°, so it is nearly nadir. The review JPEG has had EXIF
  deliberately removed.
- DJI relative altitude is approximately 99.9 m. This is not sufficient to
  establish height above every point of the ground. Resolve takeoff reference,
  vertical datum, camera calibration, and terrain before calling distances
  measured. Do not subtract an IGN ground elevation from DJI absolute altitude
  without first checking that their vertical references agree.
- `scripts/aerial_survey.py` already registers overlapping photographs and
  proposes cow associations. Its image homographies do not reconstruct terrain
  height. Its tracks have not been validated against animal-identity labels.

## Recommended implementation

1. **Scene data:** give each detection a stable ID within the frozen scene;
   store its source image, box, confidence, original crop, estimated position,
   appearance, orientation, and uncertainty. Use human-corrected detections
   when available. Preserve the distinction between a scene ID, a tentative
   cross-photo track, and a farm's actual tagged animal.
2. **Terrain:** obtain a small ground-elevation grid near the photo GPS, then
   generate a terrain mesh. IGN RGE ALTI is the geographically relevant source
   for this French sample. Project camera rays onto that terrain using camera
   intrinsics and attitude; validate alignment against landmarks. Start with
   an explicitly approximate footprint if that calibration is incomplete.
3. **Ground appearance:** project image colors onto the terrain. Mask cows out
   of the ground texture before adding their 3D replacements to prevent double
   cows. Treat filled texture under those masks as synthesized. Trees, hedges,
   and fences require separate geometry or a surface reconstruction; a ground
   elevation model alone cannot recover their shapes.
4. **Vegetation:** start with a farmer-selectable pasture/crop type and growth
   height. An image classifier can suggest broad cover, with farmer override.
   Exact species, crop variety, and hidden structure are not established by
   one overhead photograph. Procedural grass/crops can supply ground-level
   detail in the selected style.
5. **Cow appearance and heading:** instance a reusable 3D cow model, adjusting
   coat colors/patterns from a segmented crop. Keep the actual photograph in
   its detail card. Unseen sides remain approximations. Estimate the body
   axis from a segmentation mask or oriented box; resolve the 180° direction
   ambiguity with head/tail keypoints or a manual flip. A bounding rectangle
   alone does not specify facing direction.
6. **Interaction:** use Three.js for terrain and individual cow objects,
   raycasting for selection, and a first-person controller that follows the
   terrain. Provide overhead/walk modes, a source-image minimap, clickable
   IDs, and a greeting action. A head turn, moo, and short greeting can be
   deterministic; no language-model API is needed.
7. **Multiple images:** use verified overlap and camera poses to build a
   common coordinate frame. Reconcile moving cows at a chosen survey time;
   don't bake every sighting into the scenery. A full-area claim also needs
   coverage and boundary information. The current single image supports only
   its visible footprint.

For accurate reconstruction from an overlapping flight, OpenDroneMap is a
stronger fit than a generative world model: it can produce georeferenced
orthophotos, textured meshes, and digital surface/terrain models. Sparse
selected images and moving cattle need additional care. Use the DEM plus a
custom renderer for the lightweight first pass.

## Elevation probe status

A nine-point query over a 100 m square centered at the original photo GPS
was prepared to check IGN coverage. It was not executed successfully: local
network access failed, and automatic approval review rejected the escalated
request because it would transmit precise image GPS to IGN without explicit
destination-specific approval. No elevation values were obtained and no
terrain-height range is established. Approval to send that photo location to
IGN is the remaining step for this specific coverage check.

## Sources

- [IGN elevation API](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/calcul-altimetrique/)
- [OpenDroneMap outputs](https://docs.opendronemap.org/outputs/)

Image attribution: Louise Helary and Adrien Lebreton / Institut de l'Elevage,
ICAERUS grazing cows v2, CC BY 4.0.
