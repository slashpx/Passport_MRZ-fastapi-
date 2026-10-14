# MRZ Processing Flow

End-to-end path of a file uploaded for MRZ extraction. This describes the code as
implemented; see `MRZ_TECHNICAL_DOCUMENTATION.md` for the algorithmic detail and
for the list of improvements that are *not* yet built.

---

## 1. Edge: gateway and load balancing

**Endpoint:** `POST /api/mrz/process`

- **Zuplo API gateway** is the public entry point. Policies run in order (`zuplo/policies.json`):
  1. `api-key-inbound` — validates `Authorization: Bearer <key>`, rejects with 401
  2. `rate-limit-inbound` — per-consumer quota (`rateLimitBy: user`), rejects with 429
  3. `add-aws-api-key-inbound` — injects `x-api-key` for AWS API Gateway
  4. `add-backend-secret-inbound` — injects `x-backend-secret` so the backend can confirm the request arrived via the gateway

  Auth precedes rate limiting because the limit is keyed on consumer identity, and
  both precede header injection so no work is spent on traffic about to be rejected.

- **AWS API Gateway** enforces the usage plan (quota and throttle) and proxies to the load balancer.
- **Application Load Balancer** routes to a healthy ECS Fargate task. Health is determined by polling `/healthMrz`.

> **Current deployment.** The AWS topology above is defined as infrastructure-as-code
> in `mrz-fargate-stack.yaml`. The live deployment runs on **Render's Docker
> runtime** (`render.yaml`), which is a single service with the same container and
> the same health check.

## 2. Application entry (`app.py`)

Uvicorn receives the request and FastAPI matches the route.

- **Multipart path** (`/api/mrz/process`) — `UploadFile` is awaited and written to a `NamedTemporaryFile`, preserving the original extension so PDF detection works downstream.
- **Base64 path** (`/api/mrz/process-base64`) — a Pydantic `Base64Request` body is decoded; `.split(',')[-1]` strips any `data:image/jpeg;base64,` prefix so clients can post a raw data URI.

Two entry formats exist to reduce integration friction: multipart is correct on the
wire, but many mobile SDKs and low-code clients can only send JSON.

**Temp-file isolation.** At startup the process creates a UUID-named directory and
sets `TMPDIR` to it. `pytesseract` shells out to the `tesseract` binary, which
writes scratch files, so concurrent requests need isolated scratch space.

> `TMPDIR` is the correct variable for this. `TESSDATA_PREFIX` tells Tesseract where
> to find `.traineddata` language files — pointing it at an empty directory makes
> `lang='mrz'` fail with "Failed loading language 'mrz'", which `run_ocr` catches
> and silently falls back to `lang='eng'`, returning near-empty text while the API
> still responds 200. This was a real defect; see §6.

## 3. Load and normalise

`MRZExtractor.process` is invoked.

1. **PDF** → first page rendered via `pdf2image` (Poppler), RGB → BGR for OpenCV. **Image** → `cv2.imread`.
2. **Upscale** if width < 1800px, using `INTER_CUBIC`, so characters are tall enough for Tesseract's LSTM recogniser.

## 4. MRZ localisation — three-tier cascade

| Tier | Method | Mechanism |
|---|---|---|
| 1 | `CNN` | `mrz_seg.onnx` segmentation via `cv2.dnn` → mask threshold at 0.5 → largest contour → `boundingRect` + padding |
| 2 | `MORPH` | Sobel `grad_x - grad_y` → blur → threshold → `MORPH_CLOSE` (21×7 kernel) → aspect-ratio filter 5–20 → bottom-most contour |
| 3 | `FALLBACK` | Bottom 40% crop, relying on ICAO 9303 placing the MRZ at the page bottom |

Tiers 1 and 2 must pass an aspect-ratio validation (3.0–30.0) to be accepted; tier 3
is returned unconditionally so the cascade always terminates with something to OCR.
The tiers have **independent failure modes** — the learned model fails on unfamiliar
layouts, the morphological path fails on low contrast — which is what makes the
cascade worth having. The winning tier is reported as `roi_method`.

## 5. Preprocessing variants and OCR

Up to six candidate binarisations are generated from the ROI (`otsu`, `blur_otsu`,
`shadow_otsu`, plus inverted copies when the white-pixel share is under 40%).

Each candidate is passed to **Tesseract** with `lang='mrz'` (an MRZ-specific OCR-B
model), `--oem 3 --psm 6`, and a character whitelist of `A–Z0–9<` — the only
characters ICAO 9303 permits.

No single preprocessing strategy wins on all inputs, so rather than choosing one,
all candidates are scored and the best result is kept.

## 6. Parsing, validation and scoring

1. **Clean and normalise** — keep lines over 30 characters containing `<`; normalise both to exactly 44 characters, since all field extraction is positional slicing.
2. **Field extraction** — TD3 layout by index: document type, issuing state, surname, given names, document number, nationality, birth date, sex, expiry date.
3. **Type-directed correction** — date fields are all-digit by definition, so letters are mapped to their digit lookalikes before validation.
4. **Checksum validation** — ICAO 9303 weighted mod-10 (weights 7, 3, 1) over document number, birth date and expiry date.
5. **Checksum correction** — on mismatch, confusion-guided single-character substitution first (`0↔O`, `1↔I`, `5↔S`, …), then bounded exhaustive search for short fields.
6. **Confidence score (0–100)** — 75% from checksum validity, 20% from field completeness, 5% from date sanity, **−15 if any field was brute-force corrected** (so a possibly-coincidental correction cannot pass as high-confidence).

## 7. Escalation

```
score >= 95  → accept immediately (early exit)
score <= 60  → retry at 90°, 180°, 270°
score <  95  → AI fallback
```

The **AI fallback** first asks `gpt-4o-mini` to correct the noisy OCR text given the
ROI crop; if confidence is still short, `gpt-4o` performs a full vision extraction
of both the MRZ lines and the printed visual fields for cross-verification.

The model's output is **not trusted** — it is re-parsed, re-scored, and accepted
only if it beats the existing best score. The checksum stays the arbiter.

The AI tier is optional: without `OPENAI_API_KEY` the client is `None`, the methods
return `None`, and the service runs normally without it.

## 8. Response and cleanup

1. **Success** — HTTP 200 with the parsed fields plus `overall_confidence`, `roi_method`, `preprocessing_method`, the per-field checksum flags, and `rotation` if one was applied.
2. **Extraction failure** — HTTP **400**, because an unreadable image is a client-side condition, not a server fault. Keeping this distinct from 500 is what keeps error-rate alerting meaningful.
3. **Unexpected error** — HTTP 500, logged with a stack trace.
4. **Cleanup** — the temporary upload is deleted in a `finally` block, so it is removed on both the success and failure paths. No submitted document is retained.

---

## Health endpoints

| Endpoint | Type | Behaviour |
|---|---|---|
| `/healthMrz` | Liveness | Returns 200 whenever the process is up. Used by the ALB target group and by Render's health check. |
| `/status` | Readiness | Actively verifies the ONNX model file, the Tesseract binary, and that `"mrz"` is present in `pytesseract.get_languages()`. Returns **503** when any check fails. |

`/status` exists because the most damaging failure mode in this system is silent:
if the `mrz` language pack is missing, Tesseract does not crash — OCR quietly
degrades to the generic English model and the API keeps answering 200 with wrong
data. A readiness check that asserts on the *dependency* rather than on process
liveness turns that invisible failure into a visible 503.

The deploy gate deliberately uses `/healthMrz` rather than `/status`: a degraded
build returning 503 would cause the platform to refuse to promote the deployment at
all. `/status` is for observability and alerting.
