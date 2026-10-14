# elMRZ — Passport MRZ Extraction API

A containerized FastAPI service that extracts and **validates** passport data from
photos and PDFs. Send an image, get structured JSON back — plus a confidence
score telling you how much to trust it.

**Measured accuracy** on a 37-document benchmark of real passports
(24 photos, 13 scanned PDFs — see [`accuracy_report.md`](accuracy_report.md)):

| Metric | Result |
|---|---|
| Documents correct on **every** field | **33 / 37 (89.2%)** |
| Mean field-level accuracy | **97.6%** |
| Given names · birth date · expiry date · sex | 100% |
| Document number · issuer | 97.3% |
| Nationality | 94.6% |
| Surname | 91.9% |

---

## Why this is more than an OCR wrapper

Reading clean scans is easy. Real uploads are crooked, shadowed, low-resolution
and sometimes sideways. Two design decisions carry most of the weight:

**1. The system validates its own output.** ICAO 9303 embeds weighted mod-10
check digits in the MRZ. The service recomputes them, so it can tell whether its
own read is correct — offline, per request, with no database lookup. That is
what makes the confidence score meaningful rather than cosmetic.

**2. Nothing is decided by guesswork.** Rather than picking one preprocessing
strategy, the pipeline generates several competing candidates, scores each
against the check digits, and keeps the winner. The checksum is the referee.

A consequence worth noting: **cost scales with difficulty.** A clean image exits
after a single OCR pass; a hard one escalates through more variants, then
rotations, then an optional AI tier.

---

## Pipeline

```
image / PDF
    │
    ├─ 1. Load & upscale ─────── PDFs via Poppler; upscale below 1800px (INTER_CUBIC)
    │
    ├─ 2. Locate the MRZ ─────── three-tier fallback:
    │        ├─ CNN       ONNX segmentation model, pixel mask → contour → crop
    │        ├─ MORPH     Sobel gradient + 21×7 morphological close + aspect filter
    │        └─ FALLBACK  bottom 40% crop (ICAO mandates MRZ at page bottom)
    │
    ├─ 3. Preprocess ────────── up to 6 competing variants (Otsu, blur+Otsu,
    │                           shadow-removed, plus inverted copies)
    │
    ├─ 4. OCR ───────────────── Tesseract, MRZ-specific OCR-B model,
    │                           --psm 6, charset restricted to A-Z 0-9 <
    │
    ├─ 5. Parse & validate ──── positional field slicing (TD3),
    │                           ICAO 9303 checksums, confusion-guided correction
    │
    ├─ 6. Score 0–100 ───────── 75% checksums, 20% completeness, 5% date logic,
    │                           −15 if any field needed brute-force correction
    │
    └─ 7. Escalate if needed ── <60: retry at 90°/180°/270°
                                <95: optional AI vision fallback
```

The three localisation tiers matter because they have **independent failure
modes** — the learned model fails on unfamiliar layouts, the morphological path
fails on low contrast. A cascade of methods that fail on the same inputs would
be worthless.

Full algorithmic detail, including the shadow-removal method and the known
limitations: [`MRZ_TECHNICAL_DOCUMENTATION.md`](MRZ_TECHNICAL_DOCUMENTATION.md).
Request lifecycle: [`MRZ_FLOW_EXPLANATION.md`](MRZ_FLOW_EXPLANATION.md).

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/mrz/process` | Multipart upload (`image` field) — JPG, PNG or PDF |
| `POST` | `/api/mrz/process-base64` | JSON body `{"image_base64": "..."}`, data-URI prefix accepted |
| `GET` | `/healthMrz` | Liveness — 200 whenever the process is up |
| `GET` | `/status` | Readiness — verifies the ONNX model, the Tesseract binary and the `mrz` language pack; returns **503** if degraded |
| `GET` | `/docs` | Interactive Swagger UI |

Two upload formats exist to reduce integration friction: multipart is correct on
the wire, but many mobile SDKs and low-code clients can only send JSON.

### Request

```bash
curl -X POST http://localhost:5000/api/mrz/process \
  -F "image=@passport.jpg"
```

### Response

```json
{
  "status": "SUCCESS",
  "success": true,
  "type": "P",
  "issuer": "GBR",
  "surname": "SMITH",
  "given_names": "JOHN MICHAEL",
  "document_number": "AB1234567",
  "nationality": "GBR",
  "birth_date": "900101",
  "sex": "M",
  "expiry_date": "300101",

  "overall_confidence": 100,
  "number_check_valid": true,
  "birth_check_valid": true,
  "expiry_check_valid": true,
  "any_corrected": false,

  "roi_method": "CNN",
  "preprocessing_method": "otsu"
}
```

Every response reports **how** the answer was obtained, not just what it is:

- `overall_confidence` — 0–100. Clients can auto-approve above a threshold and route the rest to manual review.
- `roi_method` — `CNN`, `MORPH` or `FALLBACK`. A rising share of the latter two in production is the signal that the segmentation model is degrading against real-world input.
- `any_corrected` — whether a field needed brute-force checksum repair, which carries a confidence penalty.

An unreadable image returns **400**, not 500 — a client-side condition is kept
distinct from a server fault so error-rate alerting stays meaningful.

Dates are returned in raw MRZ `YYMMDD` form. The uploaded file is deleted in a
`finally` block on both the success and failure paths; no submitted document is
retained.

---

## Running it

### Docker (recommended)

The app depends on **system** packages, not just Python ones — the `tesseract-ocr`
binary, a custom `mrz.traineddata` language file, and Poppler for PDF rendering.
Docker is the supported path because of this; a plain Python runtime cannot
install them.

```bash
docker build -t elmrz .
docker run -p 5000:5000 elmrz
```

Then open http://localhost:5000/docs

Verify the dependencies resolved correctly:

```bash
curl http://localhost:5000/status
# {"model_loaded": true, "tesseract_available": true,
#  "mrz_language_available": true, "status": "Online"}
```

> `/status` exists because the most damaging failure in this system is silent: if
> the `mrz` language pack is missing, Tesseract does not crash — OCR quietly
> degrades to the generic English model and the API keeps answering 200 with
> wrong data. A readiness check that asserts on the *dependency* turns an
> invisible failure into a visible 503.

### Local (without Docker)

Requires Tesseract and Poppler installed and on `PATH`, plus
`fastmrz/tessdata/mrz.traineddata` copied into your Tesseract `tessdata`
directory.

```bash
pip install -r requirements.txt
python app.py              # serves on :5000
```

Run the pipeline directly on one file:

```bash
python improved_mrz_extractor.py path/to/passport.jpg
```

### Optional AI fallback

Set `OPENAI_API_KEY` to enable the vision fallback for low-confidence results.
Without it the service logs a warning and runs normally — the tier is optional by
design, never a hard dependency. See [`.env.example`](.env.example).

Note that this tier transmits a crop of the submitted document to a third-party
processor, which is a disclosure obligation and not only a technical choice.

---

## Testing

```bash
python test_accuracy.py    # runs the 37-document benchmark against ground_truth.json
k6 run load_test.js        # staged ramp to 20 concurrent users
```

`load_test.js` defines thresholds (`http_req_failed < 1%`, `p95 < 2500ms`) so it
exits non-zero on breach and can gate CI. Percentile rather than average,
because this pipeline's latency is deliberately bimodal: clean images exit early,
hard images pay for the full escalation.

Set `ZUPLO_URL` and provide a `passport.jpg` before running it.

---

## Deployment

### Current

Runs as a Docker service on **Render**, configured as code in
[`render.yaml`](render.yaml) — `autoDeploy` on push, health-checked at
`/healthMrz`. The blueprint pins `runtime: docker` deliberately: Render's native
Python runtime cannot install `apt` packages, so `/status` reported
`tesseract is not installed or it's not in your PATH`.

### AWS topology (infrastructure-as-code)

[`mrz-fargate-stack.yaml`](mrz-fargate-stack.yaml) is a CloudFormation template
defining the full production topology. It provisions an ECS Fargate service
(2 vCPU / 4 GB, `DesiredCount: 1`), an Application Load Balancer health-checking
`/healthMrz`, two security groups, an IAM task execution role, a CloudWatch log
group, and an API Gateway with a usage plan.

```
Client
  │
  ▼
Zuplo gateway ───── API-key auth, per-consumer rate limiting
  │
  ▼
AWS API Gateway ─── usage plan: quota + throttle, requires x-api-key
  │
  ▼
Application Load Balancer ─── health check: /healthMrz
  │
  ▼
ECS Fargate task ─── Docker container: Uvicorn + FastAPI
```

The service is **stateless** — no sessions, no shared state, nothing written to
disk that outlives a request — so scaling out is a change to `DesiredCount`
rather than a code change. The template does not currently define an autoscaling
policy; adding one is the remaining step for elastic scaling.

### API gateway

Gateway configuration is version-controlled in [`zuplo/`](zuplo/) —
`routes.oas.json` (routes as an OpenAPI 3.1 spec) and `policies.json` (four
policies, applied in order):

1. `api-key-inbound` — validates `Authorization: Bearer <key>`, rejects 401
2. `rate-limit-inbound` — per-consumer quota (`rateLimitBy: user`), rejects 429
3. `add-aws-api-key-inbound` — injects `x-api-key` for AWS API Gateway
4. `add-backend-secret-inbound` — injects `x-backend-secret` so the backend can confirm the request arrived via the gateway

Auth precedes rate limiting because the limit is keyed on consumer identity.
`rateLimitBy` is `user` rather than `ip` deliberately: IP-based limiting is wrong
for a B2B API, where one corporate customer behind a single NAT gateway would
throttle itself while an attacker rotating IPs would not be limited at all.

Pushing auth and rate limiting to the edge keeps the application free of auth
logic and means rejected traffic never consumes OCR compute.

---

## Tech stack

Python 3.9 · FastAPI · Uvicorn · OpenCV · NumPy · ONNX Runtime (via `cv2.dnn`) ·
Tesseract 5 (`pytesseract`) · Poppler (`pdf2image`) · OpenAI (optional) · Docker ·
Render · AWS ECS Fargate + ALB + API Gateway (CloudFormation) · Zuplo · k6

Inference runs through OpenCV's `dnn` module rather than a framework runtime,
which avoids a 1–2 GB TensorFlow/PyTorch dependency in the image — faster cold
starts, smaller registry footprint, smaller attack surface.

---

## Known limitations

Honest list; detail and proposed fixes in
[`MRZ_TECHNICAL_DOCUMENTATION.md`](MRZ_TECHNICAL_DOCUMENTATION.md#planned-improvements).

- **TD3 only.** Passports work; TD1/TD2 ID cards are not yet parsed.
- **Surname is the weakest field (91.9%)** — and structurally so. Document number, birth date and expiry each carry their own check digit; names carry none, so errors in them are undetectable by the standard's own mechanism.
- **The composite check digit is parsed but not validated.** Lowest-effort accuracy win available.
- **Only 90° rotations are corrected.** Genuine skew is not deskewed.
- **Processing is CPU-bound and synchronous**, so it blocks the event loop; one slow image can stall concurrent requests on the same worker.
- **No upload size or MIME-type enforcement**, despite the OpenAPI spec documenting a 10 MB cap.
- **Only the first page of a PDF is processed.**
- **No unit tests or CI.** `ChecksumValidator` is pure and deterministic and is the obvious place to start.
