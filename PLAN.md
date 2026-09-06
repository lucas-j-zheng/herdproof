# HerdProof — Build Plan

> Current experiment: [aerial validation results](validation/RESULTS.md). The fixed-camera batch proposal below is retained as an earlier scope.

**Reviewable cattle passage counts and batch reconciliation for agricultural lenders.**

Revised: 2026-09-05. Status: pre-build. This document defines the current scope
and supersedes the earlier whole-herd verification and automatic lending claims.
See [feasibility](FEASIBILITY.md) and [research](RESEARCH_2026-09-05.md) for
evidence, limitations, and validation still required.

## 1. Pitch

> HerdProof turns routine cattle-handling video into a reviewable batch count,
> flags differences from the submitted records, and shows how a reviewed quantity
> changes an illustrative collateral calculation.

The intended benefit is less work preparing and reviewing inventory evidence.
Reduced inspection costs, faster credit decisions, and additional financing are
customer-validation hypotheses, not demonstrated outcomes.

## 2. Initial customer and capture scope

The customer is an agricultural lender reviewing a defined cattle batch with an
operator or independent inspector. Start where cattle already pass through a
loading ramp or working alley during receiving, shipping, or routine handling.

A session describes one batch, one location, one time window, one camera view,
and one declared direction. A fixed phone or existing camera records the full
approach and departure zones. The operator records before the first passage and
until the batch has finished and the lane is empty.

A qualified operator determines handling and camera placement. The demo does
not require gathering a herd solely to film it. A 90-second recording is not a
promise that a complete inspection, animal handling, or upload takes 90 seconds.

**Unit of observation: filmed passage events.** A session becomes evidence about
a unique batch only if the handling process supports complete presentation,
separation of counted animals, and prevention of recirculation. Those conditions
are declared and reviewed; the video algorithm does not independently prove them.
A partial recording remains a partial observation.

Compare the recording with a manifest for that same batch. Do not compare a
six-passage clip with a 250-head ranch inventory. An internal pen transfer is
not automatically a purchase, sale, or change in total farm inventory.

## 3. Claims and evidence required

These are permitted descriptions of intended behavior. Use present-tense
capability claims only after the corresponding implementation passes its checks.

| Claim | Required evidence and boundary |
|---|---|
| Proposes directional passage events from supported fixed-camera footage | End-to-end results against independently labeled events, with camera geometry and evaluated clips disclosed |
| Lets a reviewer inspect, add, reject, merge, and correct events | Each action retains its evidence timestamp, reason, reviewer, and original model output |
| Compares a reviewed batch count with its manifest | Same batch, direction, and time scope; incomplete or unresolved sessions are flagged |
| Rejects exact duplicate media for a new submission and reused challenges | Byte-hash and server-state tests; limited to retained records within the authorized matching scope |
| Reports supplied time/location consistency | Metadata source and missing/conflicting values visible; editable assertions are not authenticated capture |
| Reproduces a quantity-based value illustration | Explicit price, weight, unit, eligibility assumptions, and advance rate; no credit approval |
| Makes later changes to a signed assessment detectable | Verification against a separately trusted public key; no claim about the truth of the original input |

Retired claims:

- “Any herd, any day,” “unannounced whole-herd verification,” and universal
  90-second capture.
- “Closes replay fraud outright,” “verifies when and where,” or “attestation
  closes the remaining gap.”
- A guaranteed minimum herd size inferred from detector confidence.
- Verified ownership, lien priority, animal health, live weight, pregnancy, or
  cow/calf/bull classification from this model.
- “Bank approved,” “evidence-grade,” “fraud-proof,” or automatic loan approval.
- Annual clipboard counting as a universal incumbent workflow; unverified market
  size, 10x savings, or claims that the product will rebuild the US cattle herd.

## 4. What makes the demo useful

The key interaction is tracing a discrepancy back to the footage and recording
the review decision. The dollar calculation makes the consequence visible.

The previous Uruguay annotation audit reported:

| Quantity from annotation tracks | Reported result |
|---|---:|
| Distinct annotated identities appearing somewhere in the clip | 9 |
| Annotated identities crossing the midpoint | 7 |
| Annotated identities completing the chosen terminal-zone traversal | 6 |

These are different quantities. They are not three model estimates of total herd
size, and six completed passages does not mean only six cattle exist. The audit
used ground-truth tracks; the detector/tracker still needs an end-to-end test.

Use this example to explain the observation definition, preferably in technical
Q&A. The main demo must carry its actual reviewed passage count consistently
through the manifest comparison and calculation.

## 5. Minimum build

1. **Session and manifest:** batch ID, purpose, expected passages, direction,
   declared location/time, capture source, and operator/inspector role.
2. **Video review:** fixed-camera detection and tracking, passage proposals,
   timeline, and corrections linked to footage.
3. **Comparison and illustration:** manifest discrepancy, review state, and a
   deterministic value calculation under explicit assumptions.
4. **Evidence export:** original media hash, model/config version, event ledger,
   corrections, limitations, and a JSON/HTML or PDF report.
5. **Submission checks:** one-use challenges and exact-media duplicate handling.

Prioritize pieces 1–4. Challenges support submission integrity but are not the
main demonstration. Maps, PDF styling, signatures, and generated prose are
optional after the count-review flow works.

Use Python, Streamlit, SQLite, and the existing detector/tracker candidates.
Choose and pin the actual dependencies before building. Ultralytics licensing
requires an explicit distribution decision; YOLOX is a code-license alternative,
not a demonstrated equal-performing replacement. See the research notes.

## 6. Passage detection and review

Define two terminal zones separated by a band:

- ENTRY -> BAND -> EXIT: proposed forward traversal.
- ENTRY -> BAND -> ENTRY: reversal without a completed forward traversal.
- EXIT -> BAND -> ENTRY: reverse traversal, separately recorded.
- Track beginning or ending inside the band: incomplete evidence.
- Dropout, overlap, camera motion, or association ambiguity: review or recapture.

Require stable observations at terminal zones, not just a line intersection.
Record every completed directional traversal with a unique event ID. Suppress
duplicate emissions of the same event; do not suppress all subsequent movement
of a tracker ID, since a real completed return needs to be recorded.

A tracker ID is a temporary association, not an animal's persistent identity.
Unobserved recirculation and a new ID for the same animal remain unresolved.
Net flow is not automatically a count of distinct animals.

Display separately:

- model-proposed forward and reverse events;
- unresolved intervals and reasons;
- reviewer-accepted events and corrections;
- session coverage: complete under declared procedure, partial, or unknown.

Do not output a statistical interval or a claimed lower/upper bound. The model
can miss animals without flagging them, or confidently double-count one. For
the prototype, the reviewer watches the full clip, including unflagged intervals.
A later exception-only review mode requires a measured missed-event rate.

If ambiguity or coverage cannot be resolved, output “Additional evidence needed.”
Do not turn an incomplete count into automatic financing authority.

## 7. Submission checks and trust boundaries

For each check, show PASS, FAIL, INCONCLUSIVE, or NOT TESTED and its evidence
source. No global “Authenticity verified” badge.

- Server-issued challenge: opaque random token, bound to the session, with
  server-side expiry and single-use state.
- Optional visible QR: observe whether the expected token appears in the file.
  A current QR over old footage does not establish freshness.
- File hash: SHA-256 of original bytes before transformations, matched against
  prior retained media within the authorized tenant. It detects exact reuse.
- Server receipt time: authenticated as a server observation; distinct from
  the file's claimed capture time.
- File time/location: consistency checks on editable metadata. If absent,
  leave unknown. A geofence checks an asserted camera point, not cattle identity
  or full parcel coverage.
- Decode/continuity checks: report detected defects. Monotonic timestamps do
  not establish that no edits occurred.

Consume the challenge atomically when a valid submission is bound to its media,
not when a loan decision is made. A transport retry with the same idempotency key
returns the existing submission. A repeated upload is not itself proof of fraud.
Reusing media for a new session produces a duplicate-evidence finding for review.

A controlled capture app, signed manifests, device attestation, and a supervising
inspector could strengthen particular signals. They do not prove scene truth,
ownership, or completeness. The local synthetic probe is reproducible via:

```sh
python3 scripts/probe_video_metadata.py research/2026-09-05/provenance_probe.json
```

Historical dataset footage has no newly issued challenge. Keep real footage
evaluation distinct from explicitly synthetic challenge/metadata tests.

## 8. Records and value calculation

For the MVP, compare the reviewed batch with its own submitted manifest:

```text
discrepancy_passages = reviewed_forward_passages - expected_forward_passages
```

This is a discrepancy in observed movement relative to records, not an assertion
that collateral was stolen or that the ranch is missing the same number of head.
Unresolved reverse movement or recirculation prevents unique-batch interpretation.

The calculation is an illustration under supplied assumptions:

```text
per_head_value = price_per_unit
# or, only when the quotation is per hundredweight:
per_head_value = weight_lb / 100 * price_per_cwt

illustrative_value = assumed_eligible_head_count * per_head_value
illustrative_advance = illustrative_value * assumed_advance_rate
```

A reviewer must explicitly supply/accept the unique-batch and eligibility
assumptions. Keep class, weight, condition, ownership, and lien status labeled
as record-derived or unverified. Retain separate quantities for observed passages,
assumed eligible animals, and manifest head count.

Use a clearly synthetic one-class fixture initially. Example arithmetic only:
six assumed eligible cattle at $2,000 each and 65% gives $7,800; eight gives
$10,400. These are not current cattle prices, actual video results, or credit
decisions. Replace six/eight with the selected clip's actual reviewed count and
a labeled synthetic manifest; never edit model output to force the story.

Do not carry forward the unsupported 247 / 241–253 vision fixture. The old
$400,000 scenario is withdrawn from the main demo. Its approximately $29,000
change was a collateral-value change; the change in the 65% advance calculation
was approximately $18,805.

A future inventory ledger needs purchases, births, deaths, sales, and external
transfers, with internal transfers distinguished. It also needs a trusted starting
inventory and coverage of changes outside filmed sessions. It is outside this MVP.

## 9. Footage and evaluation

Primary candidate: [Uruguay Cattle MOT](https://data.mendeley.com/datasets/dk54zg67dd/1),
whose publisher lists CC BY 4.0 and phone-video data. The prior local audit
reported 10 unique clips, about 3.26 minutes, and one labeled sequence with
479 frames, 1,775 rows, and nine IDs; this differs from the publisher's summary.

Before use:

- Independently verify each chosen clip's passage definition and events.
- Preserve source attribution and hashes. Exclude the visibly watermarked clip
  pending source clarification.
- Clip the 206 previously reported out-of-bounds boxes for spatial evaluation;
  retain original annotations. Ignore detector scores left in ground truth.
- Keep the duplicate Toros video out of separate evaluation groups.
- Freeze development and evaluation clips before tuning. Retain failed clips in
  reported results; a curated demo clip is not a generalization benchmark.

Three experiments separate failure causes:

1. Ground-truth boxes and IDs -> event rules: event-definition correctness.
2. Ground-truth boxes -> tracker -> rules: association error.
3. Pixels -> detector -> tracker -> rules: end-to-end error.

Report event matches by direction and time, false/missed passages, clip count
error, human corrections, unresolved sessions, and review minutes. A zero net
count error can hide one false and one missed event.

CattleEyeView remains a literature benchmark with restricted dataset access
previously documented in [dataset research](DATASET_SEARCH.md). No new permission
has been obtained. Sheep footage can test event rules, not cattle accuracy.

## 10. Demonstration

1. Open a defined batch and its labeled synthetic manifest.
2. Play the licensed clip with actual passage proposals and evidence timestamps.
3. Show a genuine reversal, incomplete passage, or model error if one exists.
   Do not manufacture an error; use a separately labeled synthetic logic example
   if the real clip has none.
4. Review the full clip, correct the ledger, and retain the original proposals.
5. Compare the final reviewed count with the manifest and show the illustrative
   value impact under visible assumptions.
6. Export the evidence record.
7. Briefly show an idempotent retry and a duplicate-evidence finding for a new
   session using the exact same file.

Final status: “Batch review complete” or “Additional evidence needed.”
Never “Loan approved” or “Fraud confirmed.”

## 11. Build sequence and gates

Budget nine focused hours for the core if that is the team's available time.
This is an internal timebox, not the event's official duration.

- **First hour:** independently label the demo clip, run the complete vision
  pipeline, and record the baseline. Freeze a separate evaluation clip if possible.
- **Hours 1–4:** implement event review, manifest comparison, and one shared
  assessment object. Store actual baseline failures rather than hiding them.
- **Hours 4–6:** integrate provenance observations and export.
- **Hours 6–7:** implement/test duplicate and retry behavior; sign exports only if
  time remains.
- **Hours 7–9:** run the scenarios offline, verify every displayed number against
  the shared assessment, and rehearse.

Proceed with an automatic-count demonstration only when its advertised clip
has zero false and zero missed passage events against independent labels.
For very small clips, report errors in head/events, not a misleading percentage.
An assisted-count demo may contain errors if they are visible, corrected, and
the final reviewed ledger matches independent labels.

If the count cannot be resolved by viewing the footage, abstain and request a
new capture. If review is slower than manually watching and counting, reconsider
the claimed efficiency benefit before adding features.

Minimum checks: reversal; complete return; dropout/ID switch; overlapping cattle;
partial clip; camera movement; wrong manifest scope; missing metadata; exact
duplicate; new encoding of old content; retry; expired/reused challenge; per-unit
versus per-cwt arithmetic; correction audit history; offline export. A re-encoded
old file can evade the byte-match test and must not be reported as fresh.

## 12. Industrialization story and pilot

Frame the project around agricultural inventory evidence and operational review.
The [DNHacks category](https://dnhacks.org/) explicitly includes agriculture.

Potential pilot: one lender or inspection firm and one operator with existing
handling footage. Compare manual counting/report preparation with assisted review
on the same held-out batches. Measure total human time, recording/setup burden,
mistakes, recaptures, and how the lender uses the result. Existing EID readers and
manual video review are comparison baselines, not just site visits.

The initial business question is whether this supplemental evidence saves enough
work to be useful. Broader credit access and replaced inspections require further
evidence and lender acceptance.
