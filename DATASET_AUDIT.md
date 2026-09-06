# WAID dataset trust assessment

> Historical dataset audit. References to the original 250-head demo describe
> the former scope. Follow [PLAN.md](PLAN.md) and [FEASIBILITY.md](FEASIBILITY.md)
> for the current batch-review prototype and its claims.

**Status:** quarantined in Oscar scratch; do not train yet
**Reviewed:** 2026-09-02
**Repository:** <https://github.com/xiaohuicui/WAID>
**Paper:** <https://doi.org/10.3390/app131810397>

## Provenance findings

Evidence supporting authenticity:

- GitHub owner `xiaohuicui` identifies as Cui Xiaohui, matching paper coauthor
  Xiaohui Cui.
- The peer-reviewed paper explicitly identifies this exact GitHub URL in the
  body and Data Availability Statement.
- Repository creation predates publication, and the dataset upload commit is
  dated 2023-09-18, one day after publication.
- GitHub reports 38 stars and 5 forks; it is not an unreferenced zero-activity
  repository.
- Oscar's clone passed `git fsck --full --strict`.
- The working tree contains images, YOLO text labels, class names, and a README;
  no repository code has been executed.

Unresolved trust issues:

- The repository has no explicit license. The article's CC BY 4.0 license does
  not automatically establish the dataset's license.
- The paper says source material included YouTube and Roboflow Universe under
  unspecified “knowledge-sharing” licenses. Rights and attribution are not
  traceable per image.
- There is no versioned release, immutable archive DOI, or author-published
  checksum. Pin the Git commit before any experiment.
- The paper reports 14,375 images; the checkout contains 14,366.
- The paper reports a train/validation/test split of 11,118/2,054/1,203 images;
  the checkout contains 10,056/2,873/1,437.
- Many filenames contain Roboflow export hashes, and image dimensions differ
  from the paper's stated normalization. Near-duplicate or augmented source
  frames may cross splits even though exact byte hashes do not.

## Oscar structural audit

SLURM job `5667697` audited the checkout without executing repository content or
decoding image pixels through an imaging library.

- Images: 14,366
- Paired YOLO label files: 14,366
- Cattle boxes passing validation: 63,090
- Missing image/label pairs: 0
- Exact duplicate image hashes: 0
- Exact duplicate hashes across splits: 0
- Invalid label lines: 51
- Structural result: **FAIL**

The invalid lines contain non-positive or otherwise invalid normalized box sizes.
They are distributed across train, validation, and test. They must be inspected
and either corrected from source annotations or excluded by a deterministic
manifest; never silently clamp them during training.

## Cattle-subset usability audit

SLURM jobs `5668202`, `5668608`, and `5668828` performed metadata, label,
and perceptual-leakage analysis. No repository code or model was run.

- Cattle images: 4,665
- Structurally valid cattle boxes: 63,090
- Invalid cattle boxes: 0 (all 51 zero-width boxes belong to the sheep class)
- Median cattle per image: 11; 90th percentile: 26; maximum: 65
- Median cattle box: approximately 32×33 pixels
- 10th-percentile cattle box: approximately 15×16 pixels
- Minimum cattle box: 3×4 pixels
- JPEG decode failures in the cattle subset: 0

A deterministic visual review sampled random, smallest-target, densest, and
largest-resolution cases. The images are genuine aerial cattle imagery with
varied pasture, altitude, orientation, density, and lighting. Most reviewed boxes
aligned with visible cattle. Very small labels cannot be reliably verified from
contact sheets and should be excluded or separately reviewed.

### Published split leakage

Filename-family analysis initially found no exact cattle-family leakage because
most cattle files were renamed to opaque UUIDs. Perceptual hashing then compared
5,001,578 cross-split cattle-image pairs:

- 92 pairs met the strict dual-hash distance threshold of 8;
- 213 pairs met threshold 12;
- 0 pairs had identical resized-pixel hashes.

Manual review of the 24 closest pairs confirmed that they are near-identical
views—often the same cattle in the same positions—with color, compression, crop,
or small annotation differences across train, validation, and test. This is
material leakage, not merely similar-looking empty pasture. The repository's
published splits must not be used for evaluation.

## Decision

**Usable as a noisy pretraining/fine-tuning pool after cleaning; unusable as a
trusted benchmark or final validation set.** It also does not contain 250-head
frames: its maximum is 65 labeled cattle per image, so separately sourced dense
ranch footage remains necessary for the HerdProof claim.

Required before training:

1. pin commit `f6de7fb1fdd78cd794b31526dde0eb37fd321e38`;
2. build a cattle-only manifest and remove the other five classes;
3. exclude boxes below a reviewed minimum pixel size;
4. cluster near-duplicate images and place each cluster in only one split;
5. group recognizable video/flight sequences into one split;
6. reserve separately sourced, manually counted ranch footage for final testing;
7. request dataset-license and source-attribution clarification from the authors.

Do not use the paper's reported mAP as evidence that the resulting HerdProof
model generalizes to ranch footage. A model may still benefit from these 4,665
images, but the go/no-go metric must come from the actual demo capture geometry.
