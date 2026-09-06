import { DetectionExplorer } from '@/components/demo/detection-explorer';
import { BrowserDetector } from '@/components/demo/browser-detector';

// Mirrors training/default_model.json so the browser pass matches the Python pipeline.
const DETECT_CONFIG = {
  tile_size: 1024, tile_overlap: 0.2, model_imgsz: 1024,
  tile_nms_iou: 0.9, global_nms_iou: 0.5,
  inference_confidence_floor: 0.05, max_detections_per_tile: 1000,
};

const Arrow = () => <span aria-hidden="true">↗</span>;

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <a className="wordmark" href="#main" aria-label="HerdProof home"><span className="brand-mark" aria-hidden="true">H</span>HerdProof<span className="wordmark-dot">.</span></a>
        <nav aria-label="Main navigation"><a href="#workflow">The approach</a><a href="#evidence">The evidence</a><a href="#demo">See the model</a><a className="nav-cta" href="#pilot">The next step <Arrow /></a></nav>
      </header>
      <main id="main">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <h1 id="hero-title">Get closer to<br />the farm behind<br /><em>the loan.</em></h1>
            <p className="hero-description">Drone-assisted livestock review for agricultural lending.</p>
            <p className="hero-detail">Turn aerial photos into cattle observations, reviewable evidence, and a clearer picture of what needs a closer look.</p>
            <a className="button button-yellow" href="#review">See a review example <Arrow /></a>
            <p className="hero-note">An independent prototype by Lucas Zheng · 2026</p>
          </div>
          <figure className="hero-image">
            <img src="/images/survey-flight.jpg" alt="A real drone photograph of cattle gathered in a farm enclosure, with fields and agricultural buildings around it." width="1600" height="1199" fetchPriority="high" />
            <div className="image-topline"><span>01 / SURVEY PHOTO</span><span>ICAERUS DATASET</span></div>
            <figcaption><span className="photo-caption-label">The starting point</span><strong>A field, as the camera saw it.</strong><span>Actual prototype input · November 7, 2023</span></figcaption>
          </figure>
        </section>
        <section className="purpose section-shell" aria-labelledby="purpose-title">
          <p className="eyebrow section-index">01 / WHY HERDPROOF</p>
          <div><h2 id="purpose-title">A count is more useful<br />when you can inspect the evidence.</h2>
          <p>I built HerdProof to explore whether drone imagery could give agricultural lenders more context during remote livestock reviews. The question is simple: what was observed, where is the evidence incomplete, and what should a reviewer check next?</p>
          <p>The industrialization opportunity is a repeatable inspection workflow: capture, review, and export a record that can be checked again. Its value for lenders still needs to be measured in a real pilot.</p></div>
        </section>
        <section className="workflow section-shell" id="workflow" aria-labelledby="workflow-title">
          <div className="section-heading"><div><p className="eyebrow">02 / THE APPROACH</p><h2 id="workflow-title">From a flight to a review.</h2></div><p>Keep the original evidence close.<br />Keep uncertainty visible.</p></div>
          <ol className="workflow-steps">
            <li><span className="step-number">01</span><h3>Capture the field</h3><p>Bring in survey photos, their capture metadata, and the field boundary.</p><span className="step-output">Photos + field context</span></li>
            <li><span className="step-number">02</span><h3>Find the cattle</h3><p>A cattle detector proposes observations across full-resolution image tiles.</p><span className="step-output">Traceable observations</span></li>
            <li><span className="step-number">03</span><h3>Connect the views</h3><p>Align overlapping photos and merge repeated sightings, including clipped views.</p><span className="step-output">Estimated distinct sightings</span></li>
            <li><span className="step-number">04</span><h3>Review what remains</h3><p>Inspect uncertain observations, check photo consistency, and export an assessment.</p><span className="step-output">A record + a next action</span></li>
          </ol>
          <p className="context-note"><strong>Where the walkable scene fits:</strong> it adds field context, using measured elevation with approximate photo alignment and cow appearance. It is a visualization, not an independently verified digital twin.</p>
        </section>
        <section className="review-section" id="review" aria-labelledby="review-title">
          <div className="section-shell review-layout">
            <div className="review-intro"><p className="eyebrow">03 / A CONCRETE REVIEW</p><h2 id="review-title">“Do we have enough<br />evidence to move<br /><em>this review forward?</em>”</h2><p>Imagine a loan officer reviewing a livestock survey. HerdProof&apos;s role is to organize the observations and bring unresolved evidence to the surface.</p><p className="small-copy">The lending scenario is illustrative. The figures alongside it come from an actual two-photo run of the prototype, completed September 6, 2026.</p><a className="text-link" href="/evidence/sample-assessment.json" download>Download this example record <Arrow /></a></div>
            <article className="assessment" aria-labelledby="assessment-title">
              <div className="assessment-heading"><div><p className="eyebrow">SURVEY REVIEW RECORD</p><h3 id="assessment-title">Two photos. One review.</h3></div><span className="status">Follow-up needed</span></div>
              <div className="observed-total"><strong>18</strong><div><span>estimated distinct<br />cattle sightings</span><small>Unreviewed model output</small></div></div>
              <dl className="assessment-details"><div><dt>Capture date</dt><dd>Nov 7, 2023</dd></div><div><dt>Photos processed</dt><dd>2</dd></div><div><dt>Raw observations</dt><dd>30</dd></div><div><dt>Repeated sightings removed</dt><dd>12</dd></div><div><dt>Unresolved clipped sighting</dt><dd className="warning-text">1</dd></div><div><dt>Whole-property coverage</dt><dd className="warning-text">Not verified</dd></div></dl>
              <div className="next-action"><span aria-hidden="true">↳</span><p><strong>Next action</strong>Review the proposed sightings and obtain a clearer view of the unresolved edge capture before relying on the count.</p></div>
              <p className="assessment-footnote">18 is an estimate of distinct observed animals. It is not a verified herd inventory, ownership check, or loan recommendation.</p>
            </article>
          </div>
        </section>
        <section className="evidence section-shell" id="evidence" aria-labelledby="evidence-title">
          <div className="section-heading"><div><p className="eyebrow">04 / THE ENGINEERING</p><h2 id="evidence-title">Show the work.<br />Name the limits.</h2></div><p>Two different tests answer<br />two different questions.</p></div>
          <div className="evidence-grid">
            <article className="detector-evidence"><p className="eyebrow">CATTLE DETECTION</p><h3>Can the model find visible cattle?</h3><div className="metric-pair"><div><strong>81.92<span>%</span></strong><span>Precision</span></div><div><strong>77.91<span>%</span></strong><span>Recall</span></div></div><p>Corrected YOLOv8n v2, evaluated on 77 images at a 0.70 confidence cutoff.</p><div className="evidence-limit"><strong>What these figures mean</strong><p>Provisional agreement with 1,041 source annotations. Some labels omit visible cows, and this benchmark had already been inspected. These are exploratory diagnostic results; independent validation is still needed.</p></div><a className="text-link" href="/evidence/model-validation.md">Read the model notes <Arrow /></a></article>
            <article className="overlap-evidence"><p className="eyebrow">OVERLAPPING PHOTOS</p><h3>Can two views become one sighting?</h3><div className="overlap-preview"><img src="/images/overlap-evidence.jpg" width="1200" height="1700" loading="lazy" alt="Validation evidence showing a partially clipped cow matched with another view across separate drone photos. Green boxes are supplied annotations." /></div><div className="overlap-result"><strong>192 / 192</strong><span>controlled crop cases passed<br />1,293 known duplicate links</span></div><p>The fix compares observations only inside their shared visible area, so a clipped cow can match a fuller view. Unresolved edges remain flagged for recapture.</p><p className="small-copy">These tests use supplied annotation boxes. They assess overlap handling, separately from detector accuracy and whole-herd validation.</p><div className="evidence-links"><a className="text-link" href="/evidence/overlap-validation.md">Read the overlap results <Arrow /></a><a className="text-link" href="/images/overlap-evidence.jpg">View all six photo pairs <Arrow /></a></div></article>
          </div>
          <div className="limits-line"><strong>Evidence has boundaries.</strong><p>The prototype does not establish animal ownership, authenticated capture, complete property coverage, loan eligibility, or lender acceptance. No human time-saving claim has been established.</p></div>
        </section>
        <section className="demo-section" id="demo" aria-labelledby="demo-title">
          <div className="section-shell">
            <div className="section-heading"><div><p className="eyebrow">05 / SEE THE MODEL</p><h2 id="demo-title">Every box below<br />came out of the model.</h2></div><p>Saved output from the shipped detector.<br />Then the same detector, in your browser.</p></div>
            <p className="demo-lead">Everything above this point is a number I am asking you to take on trust. Here the detector&apos;s actual output is on the photograph, at whatever confidence you choose.</p>
            <DetectionExplorer />
            <div className="demo-divider"><span className="eyebrow">NOW WITHOUT THE SAFETY NET</span></div>
            <div className="detector-intro"><h3>Run the model on your own photo.</h3><p>The same 12 MB checkpoint, downloaded into this page and executed on your hardware. Nothing is uploaded, and there is no backend to fall back on — if it does badly, you will see it do badly.</p></div>
            <BrowserDetector config={DETECT_CONFIG} />
          </div>
        </section>
        <section className="pilot-section" id="pilot" aria-labelledby="pilot-title"><div className="section-shell"><div className="section-heading"><div><p className="eyebrow">06 / FROM PROTOTYPE TO PRACTICE</p><h2 id="pilot-title">Start with one lender.<br />One ranch. A real review.</h2></div><p>A proposed pilot, with success<br />defined before the first flight.</p></div><div className="pilot-grid"><div><span className="pilot-label">WHO USES IT</span><h3>The livestock reviewer.</h3><p>An agricultural loan officer or collateral reviewer, working with a ranch and its existing inspection process.</p></div><div><span className="pilot-label">HOW IT FITS</span><h3>Evidence in. Record out.</h3><p>Capture agreed survey areas, review the observations, and export an assessment into the lender&apos;s current workflow. A person remains responsible for the decision.</p></div><div><span className="pilot-label">WHAT TO MEASURE</span><h3>Useful, after correction?</h3><p>Compare independently checked counts, correction time, missed cattle, recapture frequency, and total review time. Track capture and processing costs.</p></div></div><div className="pilot-requirements"><span>Before deployment</span><p>Independently checked reference data · Secure access to farm imagery · Agreed capture protocol · Measured operating costs</p></div></div></section>
      </main>
      <footer className="site-footer"><div className="footer-main"><a className="wordmark" href="#main"><span className="brand-mark" aria-hidden="true">H</span>HerdProof<span className="wordmark-dot">.</span></a><p>Closer to the field.<br />Clearer about the evidence.</p><a href="#main" className="back-top">Back to top ↑</a></div><div className="footer-bottom"><p>Built by Lucas Zheng · Independent research prototype · 2026</p><p>Imagery: Louise Helary &amp; Adrien Lebreton / Institut de l&apos;Elevage. <a href="https://doi.org/10.5281/zenodo.11048412">ICAERUS grazing-cow v2</a>, CC BY 4.0. Public dataset examples; no lender pilot is represented.</p></div></footer>
    </>
  );
}
