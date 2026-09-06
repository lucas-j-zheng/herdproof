**Measured farm terrain and interactive cows — research and implementation plan**

Prepared 2026-09-06. This is the current plan and supersedes `WORLD_DEMO.md` for
implementation. External generative-world services are excluded from the pipeline
and runtime.

Build a small, accurately aligned field scene using IGN ground elevations,
drone imagery, Three.js and Rapier. Test the available flight with OpenDroneMap
(ODM) to improve image alignment and texture coverage. Use the same terrain
triangles for rendering, cow placement and walking. Start with the demo image's
visible pasture; extend to a whole property only after establishing its boundary
and image coverage.

The difficult part is establishing a trustworthy camera-to-ground transform.
Drawing a height grid in 3D is straightforward. A convincing scene additionally
needs ground-level vegetation, good cow assets, lighting and careful texture work.
These are separate work items with separate acceptance checks.

**What the existing data supports**

The local audit is saved in
[terrain-data-audit.json](/Users/lucas/dev/personal-projects/herdproof/validation/terrain-data-audit.json).
It inspected original JPEG metadata, saved detections, an existing overlap report,
and the cached ZIP central directory. It made no location queries or image downloads.

| Finding | Consequence |
| --- | --- |
| 127 downloaded photos across 25 flight groups | Do not combine them into one reconstruction. Separate dates and missions. |
| Demo: Jalogny, `46472379c810`, 5280 × 3956, DJI M3E, 2023-09-26 | Use this as the first frozen scene and preserve the original image. |
| Six downloaded photos in `Jalogny/DJI_202309261339_058`; capture gaps of 5–75 seconds | The local subset alone does not establish a connected, complete mapping flight. |
| The cached publisher archive index contains 53 JPEGs for that flight, approximately 800.4 MB compressed; 47 are missing locally | Fetch just that flight for the ODM experiment. The full archive is 16.6 GB. The publisher's flight contains numbering gaps, so even these 53 should not be called a complete capture sequence without a coverage check. |
| Existing background registration accepts the demo and preceding image: 331 inliers, about 50% image overlap, median residual 1.03 px at 1600-pixel working width | Useful evidence that this pair can align. This is a 2D fit, not a terrain measurement or proof of 3D reconstruction quality. |
| Saved demo output has 21 model candidates; reference annotation has 22 boxes | Preserve model provenance. Reference boxes can assess the demo; never silently replace detections with annotations. |
| Original images include GPS, gimbal attitude, altitude and lens metadata | Enough to initialize a camera model, subject to calibration checks. Review JPEGs have EXIF stripped. |
| No terrain raster, solved camera reconstruction or ground-control file found in the task's input paths | Ground heights, real field relief and absolute cow-position accuracy remain unverified. |

The publisher describes these as nadir cattle-monitoring photographs, taken at
altitudes relative to takeoff, with a directory per flight. It does not establish
survey-grade ground control for our selected flight.
[Dataset description](https://zenodo.org/records/11048412)

**Choose the elevation source in this order**

| Route | What to acquire | Role in this demo |
| --- | --- | --- |
| IGN LiDAR HD MNT | Numeric ground-elevation raster, nominal 0.5 m grid | First choice where published for the field. Avoid processing raw point clouds when the derived ground raster is sufficient. |
| IGN RGE ALTI | Prefer the 1 m ground raster; 5 m is a lower-detail fallback | Build broad hills if LiDAR HD MNT is unavailable. Inspect age, source and quality metadata. |
| ODM from the selected flight | Solved cameras, orthophoto, DTM, DSM and textured mesh | Evaluate for image alignment and current surface detail; promote its ground model only after comparison with reference terrain and independent checks. |

IGN's current product catalogue distinguishes 0.5 m LiDAR HD MNT, MNS and MNH
from the historical RGE ALTI 1 m/5 m terrain products. MNT/DTM describes ground;
MNS/DSM includes objects above it; MNH describes object height. These are not
interchangeable. Grid spacing is not a vertical-accuracy guarantee.
[IGN relief products](https://cartes.gouv.fr/aide/fr/partenaires/ign/observations-regulieres-territoire/relief/decouverte-offre-produit/)

Use the numeric downloadable product. A shaded-relief WMS/WMTS image contains
display colours, not recoverable elevation values. IGN distributes LiDAR-derived
models under an open licence.
[IGN downloads and display-layer distinction](https://cartes.gouv.fr/aide/fr/partenaires/ign/generalites-ign/actualites/2025-03-lidarhd-et-produits-derives/)

Acquisition work should:

1. Establish the working footprint locally from the camera and available field
   boundary; include a margin for calibration error and the planned walk area.
2. Resolve intersecting tiles through the current IGN catalogue. Prefer a small
   raster extract or the few intersecting tiles. Record acquisition date, edition,
   source precision, horizontal and vertical reference systems, licence and hashes.
3. Mosaic and crop locally. Preserve missing-data cells and create a valid-area
   mask; do not turn missing data into zero-height craters or extrapolated hills.
4. If no suitable MNT is published, evaluate RGE ALTI before obtaining raw
   classified LiDAR. Raw-point processing is a later fallback with additional
   classification and memory costs.

Exact tile coverage has not been checked. Earlier geoservices URLs now redirect
to cartes.gouv.fr, and IGN renamed its model tile-index WFS resources in late
2025. Discover current identifiers instead of copying an old endpoint.
[Catalogue migration detail](https://cartes.gouv.fr/aide/fr/partenaires/ign/generalites-ign/actualites/2025-12-mises-a-jour/)

**Establish coordinates before adding detail**

Keep geographic processing in double precision. Preserve the raster's actual
CRS definition, including its RGF93 realization; use a suitable local metric
projection for processing. Do not assume all French tiles can be relabelled with
one EPSG code. Use GDAL/Rasterio and PROJ/pyproj for explicit transforms, raster
alignment and missing-data handling.
[GDAL raster reprojection](https://gdal.org/en/stable/programs/gdalwarp.html)

For the browser, subtract a common origin and use one metre per scene unit:

```text
x = easting - origin_easting
y = ground_altitude - origin_altitude
z = -(northing - origin_northing)
```

This makes east +X, up +Y and north -Z. Export the inverse transform, source CRS,
vertical datum, origin and units in `scene.json`. Map north and true north may
differ by projection convergence; account for that when converting camera yaw.
Do not rotate a mesh by eye and then try to recover its geographic alignment.

Resolve the camera's altitude reference explicitly. The demo's approximately
99.9 m DJI relative altitude is measured relative to takeoff, not the ground below
each pixel. Its absolute-altitude field is not sufficient evidence of its vertical
datum. IGN uses a conversion surface such as RAF20 to relate compatible RGF93
ellipsoidal heights to mainland NGF-IGN69 normal altitudes. Apply the appropriate
conversion only after identifying the source reference; reject a missing required
grid instead of silently accepting a low-quality transform.
[IGN conversion grids](https://geodesie.ign.fr/grilles-de-conversion) ·
[PROJ vertical transforms](https://proj.org/en/stable/operations/transformations/vgridshift.html)

The image metadata needs a sanity check: all six selected images contain
`CalibratedFocalLength=24000` with optical-centre fields of zero, whereas
`DewarpData` contains plausible focal terms around 3713.29. Treat these as
conflicting metadata, not ready-to-use pixel intrinsics. Validate the dewarp field
layout, principal-point offsets, image orientation and correction state; never
apply lens correction twice. Prefer calibrated intrinsics and optimized camera
poses from a successful reconstruction. If that fails, refine a camera prior
against well-distributed stationary landmarks with known map coordinates and
terrain heights. Hold some landmarks out of fitting.

**Turn the grid into the visible field**

Produce a canonical Float32 height grid and an indexed triangle mesh. Honour the
raster affine transform, pixel-centre convention, row direction and missing-data
mask. Keep measured heights unchanged and vertical exaggeration at 1.0. Compute
normals for lighting. Three.js `BufferGeometry` directly supports these vertex,
index and texture-coordinate buffers.
[Three.js geometry](https://threejs.org/docs/pages/BufferGeometry.html)

A proposed first scene of roughly 200 × 200 m at 0.5 m spacing has 160,801 vertices
and 320,000 triangles before cropping. This is a sizing example, not the measured
extent of our field. Use smaller chunks and distance-based levels of detail as
coverage grows. Keep full-resolution geometry near the walker and cows; verify
coarser versions do not visibly diverge from collision geometry.

Ground texture must be orthorectified or camera-projected onto terrain. Stretching
the raw photograph over a rectangle would misplace features on slopes. Preferred
input is a checked orthophoto. With one camera, project terrain points through
that camera to obtain texture coordinates, accounting for lens distortion and
visibility. Save an observation mask so unseen land is not presented as captured.

Remove cow pixels and their shadows from the ground texture before placing 3D
cows. Prefer a clean observation from another photo; otherwise fill small masked
patches from nearby ground texture and record them as inferred appearance. Keep
original images immutable. Trees and fences also need separate geometry or a
reconstruction; draping their top-view colours on ground produces flat silhouettes.

For realism, blend the aerial image's broad colour variation with detailed ground
materials, then distribute grass clumps near the camera and cheaper vegetation
farther away. Use farmer-specified pasture/crop type, growth height and row
direction as editable inputs. Add coherent daylight, sky illumination, cow contact
shadows and modest vegetation motion. Normal maps can add small visual detail
without changing the measured hill shape. Poly Haven provides CC0 materials and
lighting assets suitable for this layer.
[Asset licence](https://polyhaven.com/license)

**Project cows onto terrain and preserve their identities**

Convert each detection back to original-image pixels, reversing resize, crop,
rotation and detector letterboxing. Use a body-centre or visible-foot anchor when
available; an axis-aligned box centre is an initial approximation. Undistort the
pixel using the matching calibration, form a camera ray and transform it to the
scene frame. Invert world-to-camera poses correctly: for `Xcamera = R Xworld + t`,
the camera origin is `-transpose(R) t`. OpenSfM has additional documented pose
and image-coordinate conventions that its importer must respect.
[OpenCV projection model](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) ·
[OpenSfM conventions](https://opensfm.org/docs/cam_coord_system.html)

Intersect that ray with the terrain triangles. Save the observation pixel,
camera, intersection method and uncertainty alongside the resulting position.
Reject skyward rays, missing terrain and hits outside valid coverage.

A top-view cow detection usually lies on the cow's back, above the ground. Directly
intersecting that ray with the ground creates a horizontal displacement away from
the camera's nadir. For better placement, intersect with an estimated body-height
surface `terrainHeight(x,z) + bodyHeight`, take its horizontal location, then put
the hooves on the actual terrain. As a geometry example, a 1.4 m height assumption
at 35° off-nadir changes horizontal placement by about 0.98 m. Keep body height
as an assumption unless independently measured. Where feet are actually visible,
use those contacts instead.

Use a segmentation mask or oriented body outline to estimate the body axis. It
still has a 180° head/tail ambiguity: resolve that with head/tail keypoints or a
reviewer flip. Project the axis endpoints through the camera model before computing
world heading; image angle alone is insufficient on rotated, sloped views. The
current detector supplies boxes, so mask/keypoint estimation or manual demo
annotation is additional work. Low-confidence headings should remain marked unknown.

Give each frozen-scene animal a stable `sceneCowId`, linked to source observations.
Store a tentative cross-photo `trackId` separately from a farmer's real `animalId`.
The existing overlap associations can suggest tracks; they are not validated animal
identities. Start at the demo photo's timestamp, with other frames used as evidence.
Do not triangulate a moving cow as a static landmark or silently mix observations
several minutes apart into one simultaneous herd.

Use a realistically textured, rigged GLB cow with an explicit metre scale and hoof
contact markers. Reuse geometry and texture resources; give animated nearby cows
independent skeletons. Three.js provides GLB loading and skeleton-aware cloning.
Adjust observed coat colours while keeping the actual source crop in each cow's
card; unseen markings remain estimated.
[GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html) ·
[SkeletonUtils](https://threejs.org/docs/pages/module-SkeletonUtils.html)

**Use identical geometry for walking and contact**

Construct a fixed Rapier triangle-mesh collider from the exact terrain vertex and
index buffers used by the renderer. This avoids an initial mismatch between the
triangle interpolation seen on screen and a separately interpolated heightfield.
Heightfield colliders are a later optimization only after verifying axis order,
scale and cell diagonals against the visible mesh.
[Rapier terrain colliders](https://rapier.rs/docs/user_guides/javascript/colliders/)

Define one `sampleTerrain(x,z)` operation returning the hit triangle, barycentric
height, normal and validity. Use it for static cow placement, vegetation roots and
contact checks. Cow root placement should consider all four hoof locations; nearby
cows need simple leg adjustment on uneven ground so a single centre-height sample
does not leave individual feet floating.

For walking, use a kinematic capsule and Rapier's character controller with gravity,
slope limits and ground snapping. Run physics at a fixed timestep and interpolate
the camera. Keep the camera upright, at an eye offset from the capsule; stop at
unmapped boundaries and use obstacle colliders for fences and trees. Avoid camera
Y-clamping, which does not handle obstacles or falling.
[Rapier character controller](https://rapier.rs/docs/user_guides/javascript/character_controller/)

The first interaction loop is overhead view → select cow ID → enter walking mode
at a validated nearby spawn → walk over → greet. A head turn and moo can be local
animation/audio. Keep cattle stationary in the initial survey scene so their
locations continue to match the selected timestamp.

**Run a bounded OpenDroneMap experiment**

Retrieve the 47 missing photos for the target flight using the existing archive
range-fetch approach. Verify member CRCs and sizes and save SHA256 hashes; a partial
archive download does not verify the full publisher archive checksum. Preserve
original filenames and EXIF in an isolated terrain workspace. Do not change the
training/evaluation dataset split.

Inspect sharpness, actual spatial overlap and camera connectivity before dense
reconstruction. Mask moving cows from reconstruction using black exclusion regions
in same-sized image masks. Keep the originals and unmasked detections for the cow
layer. Review orthophoto/textured outputs separately for baked-in or duplicated
animals; do not assume a reconstruction mask guarantees clean texture.
[ODM masks](https://docs.opendronemap.org/masks/)

Run a pinned ODM release/container on a workstation or a SLURM compute allocation.
Start with camera alignment, inspect its report, then request DTM, DSM, orthophoto
and textured mesh. An initial parameter experiment can use `--dtm --dsm
--dem-resolution 50 --orthophoto-resolution 5`: those resolutions are in **cm/pixel**,
so they request 0.5 m terrain and 5 cm imagery, subject to source resolution. Confirm
flags against the installed pinned version before running.
[DEM units](https://docs.opendronemap.org/arguments/dem-resolution/) ·
[Orthophoto units](https://docs.opendronemap.org/arguments/orthophoto-resolution/)

Import solved cameras, geographic transform, orthophoto and terrain products into
the same scene contract. ODM's documented outputs include georeferenced textured
meshes, orthophotos and optional DTM/DSM rasters.
[ODM outputs](https://docs.opendronemap.org/outputs/)

Compare ODM ground elevations against IGN on open, stable ground after resolving
datum differences. Diagnose global offset, scale, tilt, local warping and canopy
artefacts. Do not deform good reference terrain to hide a camera error. A derived
DTM cannot recover hidden soil accurately from photographs of dense crops merely
because it is named DTM. If reconstruction fails or gives poor coverage, retain
the IGN terrain and calibrated-photo path; the interactive demo can still proceed.

For a new capture, plan around 80% front and side overlap for this vegetation-heavy
case, with some oblique views if ground-level structures matter. Keep original
images and flight metadata, use RTK/PPK or well-distributed measured control where
absolute accuracy matters, and reserve independent checkpoints. ODM recommends
70–80% overlap for terrain products, increasing overlap for complex vegetation;
its full-3D guidance adds oblique cross-grid imagery.
[Capture guidance](https://docs.opendronemap.org/flying/) ·
[Ground control and accuracy](https://docs.opendronemap.org/map-accuracy/)

**Implementation sequence and deliverables**

These are proposed files and work packages, not implemented components. Keep
preprocessing separate from the viewer and the existing detector/training code.

| Step | Deliverable | Completion gate |
| --- | --- | --- |
| 1. Terrain and camera audit | `terrain/source-manifest.json`, cropped `dtm.tif`, `cameras.json`, footprint and coverage masks | Real raster values obtained; datum resolved or explicitly limited; image/terrain alignment assessed with held-out landmarks. |
| 2. Geometry preview | `scene.json`, terrain buffers, source-camera overlay and elevation view | Measured slopes render at 1:1 scale; controls and geometry pass numerical checks. |
| 3. Cow placement | `cows.json`, original crops, editable heading/position review | Every accepted cow links to a real observation; no invented heading or identity; positions reproject correctly. |
| 4. Walkable scene | Three.js viewer, shared Rapier collider, overhead/walk modes and greetings | Walker follows slopes and stops at boundaries/obstacles; cows rest on the same mesh. |
| 5. Realism | Ground materials, grass/crop layer, rigged cow asset, shadows and ambient lighting | Close-up review looks convincing; no baked-in duplicate cows or floating hooves. |
| 6. Flight expansion | ODM quality report, solved cameras, expanded orthophoto/terrain where accepted | Coverage and accuracy justify expanding beyond the first view; moving observations remain timestamped. |

Start acquisition and the bounded ODM alignment experiment early, because their
results influence calibration. Steps 2–5 can use IGN plus a calibrated single image
while the flight experiment is evaluated. They do not depend on a successful dense
ODM reconstruction.

Suggested local layout is `validation/terrain-demo/` for the viewer and exported
assets, with preprocessing scripts under `scripts/terrain/`. Add GIS dependencies
in a separate environment; Rasterio, pyproj and GDAL are currently absent from
the task's Python environment. Reuse the already pinned Three.js version where
possible, add Rapier with a version satisfying the user's release-age rule, and
use pnpm with a lockfile. No remote one-shot package execution is needed.

The scene contract should record `terrainSource`, `terrainVersion`, `horizontalCRS`,
`verticalDatum`, `origin`, `metresPerUnit`, `validArea`, `textureCoverage`, cameras,
cow observations and asset attribution. Cow records should include the selected
timestamp, source image/pixel, detection confidence, position method, heading
method, assumed body height and uncertainty. Missing values remain null rather
than becoming plausible-looking zeroes.

**Verification and accuracy budget**

These are proposed acceptance criteria, not measured achievements:

| Check | Proposed gate |
| --- | --- |
| Coordinate transform | Known control points and axis directions pass; local round trip is below 1 cm numerical error. This does not measure GPS accuracy. |
| Terrain preservation | Exported mesh vertices agree with the chosen canonical grid within 1 cm; test row order, pixel centres, tile seams and missing data. |
| Render/physics agreement | Terrain height queries and collider hits differ by less than 1 cm at random interior locations and cell diagonals. |
| Camera alignment | Evaluate at least 8–12 well-distributed static landmarks when available, reserving some from fitting. Report pixel residuals and map-reference uncertainty separately. A same-ray round trip is only an implementation check. |
| Absolute position | Report independent horizontal/vertical checkpoint errors when available. Without them, label positions approximate even if the visual overlay is excellent. |
| Cow grounding | Check four-hoof contacts on representative slopes, targeting less than 3 cm visible penetration/floating in the close-up demo. |
| Identity and heading | Every ID resolves to its source; manual flips persist; ambiguous associations and directions remain explicit. |
| Visual review | Source-camera overlay, overhead view and human-height view agree; no duplicated cows, horizon holes, texture swimming or major material seams. |
| Runtime | Aim for at least 30 FPS at 1080p on the demo machine with the selected herd visible; measure loading, memory and frame time before expanding coverage. |

Model error, elevation-source error, camera calibration error and detection/body
height error should remain separate in the report. Propagate plausible camera and
anchor uncertainty through projection to estimate a cow-position region. Do not
turn a 0.5 m source grid into a claim of 0.5 m real-world accuracy.

The first experiment should answer two questions before substantial visual polish:
does the downloaded terrain represent this field adequately, and can the original
photo be aligned to it well enough to place cows credibly? If either fails, adjust
data/calibration or scope; decorative grass cannot repair geographic errors.

**Resources, remaining inputs and current status**

No generative API credits are required. The mapping data and software route can
use open resources. The main costs are engineering, any chosen commercial cow
asset, and optional reconstruction compute. Budget an initial ODM workstation job
with roughly 16 GB RAM and ample scratch space, then measure actual usage before
scaling. On Oscar, all reconstruction, decompression and large data processing
must run in SLURM compute jobs, never on a login node.

As an engineering estimate, allow roughly 4–8 focused days for a convincing first
field demo once terrain access, workable camera alignment and a suitable cow asset
are in place. A poor reconstruction or absent ground reference can extend this;
the initial acquisition/alignment experiment is the point to revise the estimate.

For this public demo dataset, enough information exists to begin that experiment.
For a farmer's own field, request original photos, any RTK/PPK/control data, field
boundary and desired crop/grass type and height. Ground-level cow photographs help
appearance; ear-tag mappings are needed only if scene IDs must identify actual
farm records.

This research did not download terrain, reconstruct a flight, run new detections,
spend credits or change the active browser demo. A prior exact-coordinate IGN
query was rejected by automatic approval review because it would send the photo's
precise GPS to IGN without destination-specific approval. That query was not
retried here. Resolve that specific access step before an equivalent location
request, or use a terrain extract supplied locally. It does not prevent completing
the research and implementation plan.

The plan and audit follow the repository's existing private, ignored `validation/`
workflow. Existing training changes remain untouched.
