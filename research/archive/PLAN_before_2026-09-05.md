> HISTORICAL SNAPSHOT — superseded on 2026-09-05. Contains withdrawn claims.
> Follow the current root PLAN.md, FEASIBILITY.md, and RESEARCH_2026-09-05.md.

# HerdProof — Build Plan

**Unannounced, evidence-grade livestock collateral verification for ag lenders.**

Status: pre-build. Derived from `FEASIBILITY.md`, `DATASET_SEARCH.md`, and
`DATASET_AUDIT.md`. Every number below is either measured locally or cited.

---

## 1. One-sentence pitch

> Lenders hold cattle collateral they count once a year with a clipboard;
> HerdProof verifies any herd on any day from a 90-second phone video — and tells
> you honestly how much of that count it will let you lend against.

## 2. What it is

A lender-side tool. The loan officer issues a one-time challenge; the rancher
films the herd with a phone; the system checks the video's provenance, counts the
animals with a stated uncertainty range, reconciles against the lien file, values
the collateral at dated class prices, and produces a signed report the officer
attaches to the loan file.

---

## 3. The core idea — the number you choose IS the loan decision

This is the pitch. Everything else supports it.

A single clip yields three different, defensible "counts":

| Method | Count | What it actually means |
|---|---:|---|
| Unique tracker IDs | 9 | animals the tracker ever saw — the naive answer |
| Midpoint line crossings | 7 | things that touched the line — the obvious answer |
| **Completed traversals** | **6** | **the only one that is an animal that went through** |

Measured on the Uruguay Cattle MOT annotated sequence. The failure mode is not
hypothetical — on a free-moving drone clip, unique tracker IDs gave **51
(ByteTrack) and 72 (BoT-SORT) for a herd of roughly 20–25**, a ~3x overcount.

Downstream, the choice is worth **$29,000 of lending capacity** on a $400K
request that clears by **$3,558**. Most demos print one number with unearned
confidence. This one prints three, explains why they differ, and lends against
the conservative one.

---

## 4. Claims

### What we claim

- **Closes replay fraud outright** — one-time server-side nonce plus byte-level
  SHA-256 matching against every previously accepted report. Deterministic, no
  model involved.
- **Raises the cost of location and timing fraud**, and shows precisely where
  device attestation closes the remaining gap.
- **Counts the herd with a stated uncertainty range**, and values only the bottom
  of that range.
- **Produces an evidence trail where today there is a memo.**

### What we explicitly do NOT claim

- **Ownership.** We verify when, where, and how many — not whose. EID/brand
  reconciliation is a roadmap slot, shown mocked.
- **Attested capture.** Container metadata is editable. The UI says "provenance
  checks passed," never "capture authenticity proven."
- **Animal class from vision.** Class composition comes from the lien file, and
  the report says so on its face. COCO has one `cow` class; no candidate dataset
  carries an adult/calf label.

### Framing

Track: Energy & Industrialization — capital formation for rebuilding the US
cattle herd from a 75-year low. The fraud angle carries the policy room; the
provenance + CV depth carries "Best use of AI."

### Citations (verify before using any number on stage)

- **Easterday**: $244M, **265,000 ghost cattle**, 11-year sentence.
  US DOJ — <https://www.justice.gov/opa/pr/rancher-sentenced-running-244-million-ghost-cattle-scam>
- **McClain**: ~$100M in investor and lender losses.
- **UNSOURCED — do not use as-is**: the "$60B of cattle-collateralized lending"
  figure could not be verified. Farm Credit System held ~$373B total and ~$210B
  in farm loans (2022), with no public breakdown isolating cattle collateral.
  Either source it or reframe.
- **UNSOURCED — do not use as-is**: "10x cheaper than a site visit." Needs a
  per-inspection cost basis or downgrade to "an order of magnitude."

---

## 5. Data decision

**Primary asset: Uruguay Cattle MOT** — "Counting cattle: Supporting Livestock
Multi Object Tracking," Universidad Tecnológica del Uruguay.

- DOI: <https://doi.org/10.17632/dk54zg67dd.1>
- License: **CC BY 4.0** (confirmed in both Mendeley and DataCite metadata)
- Archive: 275,216,868 bytes,
  SHA-256 `1fcb101ac83eb917f492e00f10b8b67d912fbb1bc881e40b11713a078868e01b`
- 10 unique videos, ~3.26 min decoded, 93 Brangus cattle stated
- **Ground truth already exists**: 479 frames, 1,775 manually corrected box rows,
  9 persistent IDs (documented as 478/1,774/8 — the audit found otherwise; trust
  the audit)
- Geometry: lateral, mostly-fixed phone camera, cattle moving past at 30 fps

**Why this and not the others.** The binding constraint on the whole build is
licensed footage with manual ground truth available in hour one. This dataset
removes that constraint entirely. It is also the *easy* detection case — large,
close, side-on cattle — which is the opposite of every measured failure (the
feedlot clip gave 63 detections at conf 0.10, 33 at 0.25, 9 at 0.50 for hundreds
of animals). **Expect stock COCO YOLOv8 to be sufficient. Verify in hour one.**

### Known defects to handle

- `Toros.mp4` is duplicated across the video and ground-truth directories
- 206 boxes extend past an image boundary — clip during conversion
- Detector confidence values remain in the ground truth — these are NOT
  annotation confidence; ignore them
- No machine-readable per-video table of the stated 93 counts — count each
  selected clip independently before using it
- One clip carries a visible social-media watermark — **do not use that clip**

### Secondary / backup

| Asset | License | Use |
|---|---|---|
| ICAERUS passing-sheep crossing videos ([10.5281/zenodo.12094356](https://doi.org/10.5281/zenodo.12094356)) | CC BY 4.0 | Cross-species stress test for the state machine — crowding, reversals, occlusion, dog/human distractors. **Never** cite as cattle detector accuracy. |
| ICAERUS grazing cows v2 ([10.5281/zenodo.11048412](https://doi.org/10.5281/zenodo.11048412)) | CC BY 4.0 | Aerial detector training if the census fallback is ever revived |
| New Zealand Cattle Detection ([10.5281/zenodo.5908869](https://doi.org/10.5281/zenodo.5908869)) | CC BY 4.0 | Dense point-count supervision — roadmap only |

### Excluded, with reasons

- **WAID** — no dataset license at all (`license: null`); near-identical cattle
  views confirmed across its published train/valid/test splits (all 5 DJI source
  clips appear in all 3 splits). Aerial-only. Not needed.
- **CattleEyeView** — closest true gate benchmark, but non-commercial terms
  restricting display and redistribution. Do not touch without personally
  accepting the terms or obtaining written permission.
- **Cows2021 / OpenCows2020** — non-commercial license.
- **Wikimedia CC drone clips** — no pledged-parcel metadata, no ground truth.

---

## 6. Licensing of the software stack

Ultralytics is **AGPL-3.0**, which is a genuine blocker for a proprietary
lender-facing deployment. Verified alternatives, should it matter:

| Project | Code license | Notes |
|---|---|---|
| SAHI (`obss/sahi`) | **MIT** | Sliced inference, +5–7 AP on aerial with no retraining |
| RF-DETR (`roboflow/rf-detr`) | **Apache-2.0** | Clean AGPL-free detector |
| YOLOX | **Apache-2.0** | Older, clean |
| HerdNet | MIT code | **Weights are CC BY-NC-SA-4.0** |
| MegaDetector-Overhead / OWL | MIT code | Weights license unstated; OWL-D pulls in Meta's bespoke DINOv3 license — prefer OWL-C |
| POLO | **AGPL-3.0** | Ultralytics fork — inherits the problem, no help |

For the hackathon, Ultralytics is fine (open project, AGPL-compliant). Have the
Apache-2.0 answer ready for the "could a bank actually deploy this?" question.

---

## 7. The five pieces

1. **Lender portal (Streamlit)** — create request, define approved grazing
   polygons, issue nonce/QR.
2. **Provenance checker** — SHA-256 of original bytes, QR decode, challenge
   lookup, capture-window check, geofence.
3. **Counter** — detection + tracking + `ENTRY -> BAND -> EXIT` state machine,
   outputs `[N_min, N_max]` with annotated keyframes.
4. **Reconcile + value engine** — expected count from records, variance flags,
   `V = sum(n_i * p_i)`, `max_loan = r * V`.
5. **Report** — signed PDF with evidence, flags, hashes, and a Claude-written
   narrative explaining anomalies.

### Counting state machine (piece 3)

- Detect a single `cattle` class. **Do not** count raw geometric line
  intersections.
- Count only a completed traversal into the opposite terminal zone.
- `ENTRY -> BAND -> ENTRY` is a reversal: no count.
- Keep separate `IN` and `OUT` ledgers if two-way movement is allowed.
- Remember completed tracker IDs; tolerate only bounded dropouts.
- A track lost inside the band is `UNCERTAIN`, never guessed.
- Flag reversals, prolonged occlusion, ID switches, and simultaneous crossings
  for manual review.
- Sample every third frame only after confirming a fast animal stays visible in
  enough sampled frames to hold a track. Do not blindly skip five.

### Uncertainty band (not a confidence interval)

Label it `algorithmic uncertainty range`. Raw YOLO confidence is not a confidence
interval for herd size, and tracking errors are correlated across frames, so no
binomial formula applies either.

- **Lower bound** — high-confidence, stable, direction-valid completed traversals
- **Upper bound** — lower-confidence candidate traversals after duplicate
  suppression
- **Point estimate** — reviewed threshold selected on held-out labeled footage

### Provenance checks (piece 2)

Each returns its own `PASS` / `FAIL` / `INCONCLUSIVE`. Missing metadata is
`INCONCLUSIVE` or `FAIL`, **never** silently accepted.

1. QR decodes within the first configured time window
2. Challenge exists, matches this loan, unexpired, unused
3. Capture timestamp after issuance (explicit clock skew) and before expiry
4. GPS parses unambiguously and falls inside the pledged parcel
5. Original uploaded bytes have a SHA-256 digest
6. Container/frame timestamps monotonic, no obvious discontinuity

Challenge record schema (SQLite):

```text
challenge_id, nonce_hash, loan_id, parcel_id, issued_at, expires_at,
used_at, accepted_video_sha256
```

Use an opaque 128-bit random nonce rendered as `HP1:<base32 nonce>`. Store only
its hash. Mark it used atomically, only on acceptance.

Geofence notes: use `polygon.covers(point)`, not `contains`, so boundary points
are not rejected by definition. Shapely is Cartesian — fine for point-in-polygon
on a small parcel with `(longitude, latitude)` ordering, but project to a local
CRS before any distance or tolerance math. Use ffprobe for video tags, not
`exifread`. iPhone files may use `com.apple.quicktime.location.ISO6709`.

### Records + reconciliation (piece 4)

```text
inventory_snapshot(as_of, animal_class, head_count)
inventory_event(event_at, event_type, animal_class, head_count, document_id)
```

Events: `birth`, `sale`, `death`. Per class and in total:

```text
expected       = last_count + births - sales - deaths
variance_heads = observed_point - expected
variance_pct   = variance_heads / expected
```

Reject duplicate document IDs, negative head counts, events before the selected
snapshot, and an expected count below zero.

### Valuation (piece 4)

USDA AMS quotes are commonly **dollars per hundredweight**, not per animal.

```text
per_head_value   = average_live_weight_lb / 100 * price_per_cwt
collateral_value = sum(head_count_i * per_head_value_i)
max_loan         = advance_rate * collateral_value
```

Replacement cattle may be quoted directly `Per Unit` — do not multiply those by
weight.

**The worked $400K scenario** (USDA AMS report 2069, Mid-South Livestock Regional
Center, Unionville TN, dated 2026-08-31 — a pinned demo fixture, not a live
appraisal):

| Record-derived class | Head | Quote basis | Per head | Extended |
|---|---:|---|---:|---:|
| Bred cows | 180 | 2–4 yr, T2, Per Unit | $2,800.00 | $504,000.00 |
| Feeder calves | 65 | 533 lb x $369.63/cwt | $1,970.13 | $128,058.31 |
| Slaughter bulls | 5 | 1,803 lb x $196.68/cwt | $3,546.14 | $17,730.70 |
| **Total** | **250** | | | **$649,789.02** |

At a 65% advance rate, all 250 head support **$422,362.86**.

Visual estimate of 247, range 241–253. Value the **lower bound only**.
Conservative allocation removes the highest-value animals first: 5 bulls and
4 cows. Collateral becomes **$620,858.31**; max loan **$403,557.90**.

**The $400K request clears by $3,558.** That is the whole point — uncertainty is
consequential, not decorative.

Required caveats in the report: class counts are record-derived not
vision-derived; the market report's date, region, grade, weight, and source URL;
the bred-cow line has a small sample and is illustrative; the advance rate is
lender policy, not USDA; transport, health, lien priority, and concentration
haircuts are omitted. Pin the price snapshot in code with `as_of`, report ID,
source URL, unit, weight, and retrieval hash.

### Report (piece 5)

ReportLab for the PDF. Matplotlib for the static parcel polygon + GPS point +
legend — Folium is JavaScript-driven and will not reliably render into a PDF; use
it only in the interactive UI.

Signing flow:

1. Build canonical assessment JSON
2. Sign with an Ed25519 demo key
3. Render report ID, signature, public-key fingerprint, and a verification QR
4. Sign the final PDF hash; store the detached signature in the verification
   record

Do **not** claim PAdES or certificate signing unless actually implemented and
verified with a PDF signature tool.

### Claude's role

Sanitized aggregate JSON in, constrained JSON schema out, validated. Never send
videos, ranch coordinates, borrower names, or raw receipt text. Claude never
invents a price, clears a failed check, or makes the credit decision. Keep a
deterministic template fallback and precompute the demo response.

---

## 8. Hour-by-hour

### Hour 0–1 — asset gate (nothing else starts until this passes)

- Select the demo clip from Uruguay MOT (**not** the watermarked one)
- Independently count it; reconcile against the MOT ground truth
- Run stock COCO YOLOv8 and the traversal state machine
- **Enforce the kill criterion** (section 9)
- Freeze: parcel GeoJSON, record events, price snapshot, attribution strings,
  model weights, both scenario files
- Test the actual capture device with ffprobe, or commit to labelling the
  provenance fixture as synthetic in the UI

If the criterion fails, change the claim or the clip. Do not spend the day hoping
stock YOLO improves.

### Hours 1–4 — parallel

- **A:** detector, tracker, `ENTRY -> BAND -> EXIT` state machine, uncertainty
  band, annotated output
- **B:** challenge store, QR scan, ffprobe normalization, freshness, SHA-256,
  geofence, replay rules
- **C:** Streamlit shell, SQLite fixtures, deterministic reconciliation,
  unit-correct valuation
- **D (if a fourth person):** report template, static map, keyframes, signature
  verifier

### Hours 4–6 — integrate on one typed assessment object

Every layer consumes the same immutable assessment JSON. UI, Claude, and PDF must
never independently recompute a business value.

### Hours 6–7 — report and fraud queue

Generate the accepted report. Submit the exact replay. Verify it creates a linked
high-severity alert.

### Hours 7–8 — failure rehearsal and caching

Run the test matrix. Cache annotations and Claude prose. Disable
network-dependent paths by default. One button loads each precomputed scenario.

### Hours 8–9 — pitch and rehearsal

Five slides:

1. Livestock collateral is expensive to verify
2. Challenge-bound visual inventory workflow
3. The accepted 250-head scenario and transparent math
4. The exact replay, rejected and linked to the prior hash
5. Path from metadata checks to controlled, attestable capture

Rehearse twice.

---

## 9. Kill criteria — decide before building, not after

- On the exact demo clip, the count method must put manual ground truth **inside**
  its uncertainty range **and** keep point error **at or below 5%**.
- If it fails: use a different clip, or change the claim to a manually corrected
  estimate. **Never** show a live model result that missed the criterion.
- Never alter a model result to manufacture the fraud case. Alter only the
  controlled test fixture, and label it as such.

---

## 10. The demo

Two runs on the same herd footage.

**Run one — accepted.** Valid challenge, inside geofence, within capture window,
count reconciles against records. Report approves a $400K line at $403,557.90
maximum. Show the three-numbers slide here: 9 / 7 / 6, and why only 6 counts.

**Run two — rejected.** Resubmit the **exact accepted file**. Two deterministic
failures, both auditable:

- `challenge: FAIL — already used`
- `file hash: FAIL — exact match to accepted report HP-…`

A new high-severity replay case appears in the alert queue, linked to the prior
report.

**Why exact replay and not a stack of failures.** Stacking replay + expired code +
off-parcel GPS muddies which check actually fired, and an off-parcel fixture is
weak when its GPS is merely synthetic. Two clean deterministic failures, with no
model involvement, are unarguable. Keep off-parcel as a prerecorded secondary
test in the matrix.

---

## 11. Test matrix

| Area | Cases |
|---|---|
| QR / challenge | valid; absent; blurred; wrong loan; appears too late; expired; already used |
| Video | unsupported codec; corrupt/truncated; zero frames; very large; metadata stripped; non-monotonic timestamps |
| GPS | inside; outside; exactly on boundary; missing; malformed ISO-6709; lat/lon swapped; multiple conflicting tags |
| Freshness | capture before challenge; within window; expired; missing timezone; clock-skew boundary |
| Replay | exact accepted hash; same nonce on a different file; same file renamed |
| Count | no cattle; crowded crossing; two simultaneous animals; occlusion; reversal; animal stops on the line; camera moves; detection drops and reappears |
| Records | no snapshot; duplicate receipt; negative event; events before snapshot; expected count zero; variance threshold boundary |
| Valuation | per-cwt conversion; per-unit quote; stale price; missing class; uncertainty lower bound; rounding only at presentation |
| Report | deterministic fallback without Claude; Claude timeout/malformed JSON; special characters; long explanation; signature verification; keyframe and map present |

---

## 12. Operational constraints

- Streamlit's upload default is 200 MB. Set a deliberate maximum and reject
  oversized files early rather than loading them into memory.
- Use chunked hashing and temp files. Never `uploaded_file.read()` a
  multi-gigabyte video and hold multiple copies in RAM.
- Hash the **original** bytes before any transcoding. Transcoding destroys GPS
  and timestamps while leaving a QR readable — this was tested and confirmed.
- Pin and pre-cache all dependencies and model weights. Ultralytics tried to
  auto-install `lap` on first tracker use.
- Tested YOLOv8n weights SHA-256:
  `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`
- Runtime measured: 101 frames at 1280 inference took 11.4 s; two 226-frame
  tracking passes took 55.4 s total. Precomputed demo is comfortable; live
  upload processing needs a progress UI and a cached fallback.
- Business-use drone flying implicates FAA Part 107. Use licensed existing
  footage.
- Ranch coordinates, inventory, and financing data are sensitive. Keep exact GPS
  and borrower identity out of any LLM request. Define demo-file deletion.
- Honor CC BY attribution in both the app and the report.

---

## 13. Cut from scope — and what to say about each

| Cut | Why | Roadmap line |
|---|---|---|
| Drone visual census | Different model, labels, and uncertainty logic; can't do two geometries in nine hours | "Aerial census for extensive range operations" |
| Adult/calf/bull from vision | COCO has one `cow` class; no candidate dataset carries the label; contradicts the go/no-go checklist | "Class-aware counting with a purpose-built model" |
| Any model training | Stock COCO is expected to suffice on this geometry | — |
| WAID / OWL / point-label pipelines | Aerial-only; irrelevant to the chosen geometry | "Point-supervised dense counting (OWL-C, MIT) for feedlots" |
| Ownership / EID / brand | Out of scope by design | Show the mocked slot |
| Device attestation, C2PA | Production-only | Slide 5 |

---

## 14. Go / no-go checklist

Do not begin the full build until all are true:

- [ ] Final footage license documented (Uruguay MOT CC BY 4.0, attribution string written)
- [ ] Demo clip selected, not the watermarked one, independently counted
- [ ] Point error <= 5% and ground truth inside the reported range
- [ ] Device GPS/timestamp extraction tested, **or** the UI clearly labels
      provenance data as a synthetic fixture
- [ ] Challenge and replay behavior deterministic and pretested
- [ ] Price units, weights, date, region, and source displayed
- [ ] The $403,557.90 result reproduced from a single deterministic function
- [ ] No UI or prose claims automatic cow/calf/bull classification
- [ ] No UI claims editable metadata proves capture authenticity
- [ ] The demo runs with the network and Claude unavailable
- [ ] Both scenarios precomputed and rehearsed twice
