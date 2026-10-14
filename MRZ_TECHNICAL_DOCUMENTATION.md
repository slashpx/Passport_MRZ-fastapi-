# MRZ Extraction — Technical Documentation

## Overview

This document describes the MRZ (Machine Readable Zone) extraction pipeline as
**implemented** in `improved_mrz_extractor.py`. It reflects the code as it
actually runs. Ideas that were considered but are not implemented are listed at
the end under [Planned Improvements](#planned-improvements), so the two are never
confused.

The design goal is **correctness-first**: the system is built to know when it is
wrong. Every extraction is scored 0–100 against the check digits that ICAO 9303
embeds in the document itself, and that score drives all of the pipeline's
control flow.

---

## Pipeline

### 1. Input handling (`ImagePreprocessor.load_image`)

| Input | Handling |
|---|---|
| `.pdf` | First page rendered via `pdf2image` (Poppler), converted RGB → BGR for OpenCV |
| Image file | Loaded directly with `cv2.imread` |
| `numpy.ndarray` | Copied as-is |

**Note:** only the first page of a PDF is processed.

### 2. Upscaling (`upscale_image_if_needed`)

If image width is below `MIN_IMAGE_WIDTH` (1800px), the image is upscaled with
`INTER_CUBIC` interpolation. Tesseract's LSTM recogniser needs roughly 30+
pixels of character height; below that, strokes merge and accuracy collapses.
Cubic interpolation is used rather than nearest-neighbour because character
*shape* fidelity matters here — nearest-neighbour would produce jagged edges.

### 3. MRZ localisation — three-tier cascade (`ROIExtractor.extract_roi`)

Each tier is attempted in order. Tiers 1 and 2 must pass `_validate_roi`
(non-empty, aspect ratio between 3.0 and 30.0) to be accepted. The method that
succeeded is reported in the response as `roi_method`.

**Tier 1 — `"CNN"` (`_extract_via_cnn`)**

- Image resized to 256×256, normalised to float32 `[0,1]`, reshaped to NHWC `(1,256,256,3)`
- Forward pass through `mrz_seg.onnx` via `cv2.dnn` (no ML framework dependency)
- Output probability mask thresholded at `ROI_MIN_CONFIDENCE` (0.5), resized to original dimensions
- `findContours` (`RETR_EXTERNAL`), largest contour by area, `boundingRect`, 10px padding
- Most accurate and most general: robust to coloured backgrounds, holograms and varying layouts
- Wrapped in `try/except` so an inference failure falls through rather than erroring the request

**Tier 2 — `"MORPH"` (`_extract_via_morphology`)**

- Sobel `grad_x - grad_y` isolates dense *vertical* strokes (MRZ characters) while suppressing horizontal lines such as page borders
- `blur(9,9)`, fixed threshold at 225
- `MORPH_CLOSE` with a **21×7 rectangular** kernel — wide and flat, so it bridges inter-character gaps on a line into one blob without bridging upward to unrelated text
- Candidate contours filtered by aspect ratio 5.0–20.0, then the **bottom-most** is selected
- Purely geometric with no learned weights, so its failure mode is **independent** of Tier 1's. That independence is the point of the cascade.

**Tier 3 — `"FALLBACK"` (`_extract_fallback`)**

- Crops the bottom 40% of the image (`image[int(h*0.60):h, :]`)
- No detection at all; relies on ICAO 9303 mandating the MRZ at the bottom of the data page
- Returned unconditionally, guaranteeing the cascade terminates with something to OCR

### 4. Preprocessing variants (`get_preprocessing_variants`)

Rather than selecting one preprocessing strategy, the pipeline generates several
competing candidates and lets the confidence score pick the winner. No single
strategy wins on all inputs — shadow removal helps a shadowed photo and thins
strokes on a clean scan; blurring helps a noisy image and merges characters on a
small one.

| Variant | Method |
|---|---|
| `otsu` | Otsu's automatic threshold on grayscale |
| `blur_otsu` | Gaussian blur (5×5) then Otsu — suppresses JPEG/sensor noise |
| `shadow_otsu` | Shadow removal then Otsu |
| `*_inverted` | `bitwise_not` of any variant whose white-pixel share is under 40% |

**Shadow removal (`remove_shadows`)** estimates and divides out the illumination
field, converting a global thresholding problem into a locally uniform one:

1. `dilate` with a 7×7 kernel — erases thin dark text, leaving mostly background
2. `medianBlur` (21) — yields a background/illumination estimate; the median is robust to residual text pixels in a way a mean is not
3. `255 - absdiff(gray, bg)` — flat page areas cancel; only text survives
4. `normalize` to full 0–255 dynamic range

This matters because a photo with a shadow across half the page has no single
valid global threshold: the shadowed side's "white paper" is darker than the lit
side's "black ink". Flattening the illumination first makes Otsu valid again.

The **inversion heuristic** rests on a statistical prior: text is a minority of
pixels, so if white is in the minority, polarity is probably reversed. Rather
than decide, the flipped image is added to the candidate pool.

### 5. OCR (`OCREngine.run_ocr`)

- Engine: Tesseract 5.x via `pytesseract`
- Config: `--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<`
- Language: `lang='mrz'` (an MRZ-specific OCR-B model, `mrz.traineddata`, vendored from the upstream fastmrz project). Falls back to `lang='eng'` only if the `mrz` result is empty.
- `PSM_MODES` and `OEM_MODES` are lists in `config.py`, so a multi-mode sweep is a config change. Currently both hold a single value.

**Why `--psm 6`** ("assume a single uniform block of text"): layout analysis has
already been done upstream by the ROI cascade. Letting Tesseract re-run its own
page segmentation on a cropped two-line strip is wasted work and can split the
strip incorrectly. The localisation quality upstream is what permits the
cheaper, more constrained OCR mode downstream.

**Why the character whitelist** is one of the highest-value changes in the
pipeline: ICAO 9303 permits only `A–Z`, `0–9` and `<`. Whitelisting makes it
structurally impossible to emit lowercase, punctuation or Unicode lookalikes, so
every misread lands on a *plausible* character — which materially improves the
odds that downstream checksum correction can repair it.

Candidate selection among OCR results uses `max(results, key=lambda x: (x.count('<'), len(x)))`.
A valid MRZ is dense in `<` (name padding and filler), so chevron count is a
cheap proxy for MRZ-likeness. This is only a tie-breaker within `run_ocr`; the
authoritative arbiter is the confidence score.

### 6. Parsing (`MRZExtractor.parse_mrz`)

Currently **TD3 only** (passports, 2 lines × 44 characters).

Lines longer than 30 characters and containing `<` are retained; the parser then
looks for a line whose first character is in `PIACV` with a `<` in its first five
characters. Both lines are normalised to exactly 44 characters
(`correct_line_structure`) because all field extraction is positional slicing —
a wrong line length shifts every subsequent field.

| Line 1 field | Slice |
|---|---|
| Document type | `[0:2]` |
| Issuing state | `[2:5]` |
| Surname / given names | `[5:]`, split on `<<` |

| Line 2 field | Slice |
|---|---|
| Document number | `[0:9]`, check digit `[9]` |
| Nationality | `[10:13]` |
| Birth date | `[13:19]`, check digit `[19]` |
| Sex | `[20]` |
| Expiry date | `[21:27]`, check digit `[27]` |
| Personal number | `[28:42]`, check digit `[42]` |
| Composite check | `[43]` |

### 7. Validation and correction

**Checksums (`ChecksumValidator`)** implement the ICAO 9303 algorithm: character
values (digit = itself, `A`=10 … `Z`=35, `<`=0) multiplied by repeating weights
**7, 3, 1**, summed, `mod 10`. The non-uniform weights make the checksum
positional, so transposition errors are detected — a plain sum would not catch
them.

**Type-directed date correction (`correct_date`)** runs first. Date fields are
`YYMMDD` and therefore all-digit by definition, so any letter is a known error
with a known cause: `O/D/Q`→`0`, `I/L`→`1`, `S`→`5`, `B`→`8`, `Z`→`2`. Cheap,
deterministic, and it gives the checksum search a better starting point.

**Checksum correction (`brute_force_correct`)** runs in two tiers:

1. **Confusion-guided.** `config.OCR_CONFUSIONS` maps each character to its known visual lookalikes (`0↔O,Q,D`; `1↔I,L,7`; `5↔S`; `8↔B,3`; `2↔Z`; `6↔G`; `4↔A`). Each position tries only those substitutions, with backtracking.
2. **Bounded exhaustive.** If no confusion fixes it, every whitelist character is tried at every position — but only when `len(text) <= 15`, to bound cost.

Confusion-guided ordering comes first because OCR errors are not uniformly
distributed: `S`→`5` is common, `S`→`W` essentially never happens. Searching the
high-probability neighbourhood first is both faster and **safer**.

**Known limitation.** A mod-10 check digit has only ten possible values, so
roughly 1 in 10 arbitrary single-character substitutions will satisfy it by
coincidence. Confusion-first ordering mitigates but does not eliminate this.
Accordingly, a successful correction is **not** treated as a clean pass — see the
−15 penalty below.

### 8. Confidence scoring (`ConfidenceScorer`)

| Component | Weight |
|---|---|
| Fraction of check digits that validate | 75 |
| Field completeness (7 expected fields) | 20 |
| Date logic / format sanity | 5 |
| **Penalty if any field was brute-force corrected** | **−15** |

Checksums dominate because they are the only *externally verifiable* signal:
completeness proves the parse produced output, checksums prove the output is
correct. The −15 penalty is deliberately sized to push a corrected result below
the 95 threshold, so a possibly-coincidental correction never passes as
high-confidence and instead triggers verification.

The score is returned to the caller as `overall_confidence`, letting clients set
their own policy — auto-approve above a threshold, route the remainder to manual
review. For an identity-verification use case a calibrated confidence value is
more useful than a marginally higher raw accuracy figure, because it identifies
*which* results to trust.

### 9. Control flow driven by the score

```
load → upscale → process at 0°
  │
  ├── for each preprocessing variant: OCR → parse → score
  │     └── early exit if score >= 95
  │
  ├── if score <= 60: retry at 90°, 180°, 270° (cv2.rotate)
  │
  └── if score < AI_CONFIDENCE_THRESHOLD (95): AI fallback
```

Rotation search exists because phone photos of passports are frequently sideways
and EXIF orientation is unreliable. `cv2.rotate` at multiples of 90° is a
lossless transpose, so it is cheap and adds no interpolation artefacts.

The gating means **cost scales with difficulty**: a clean image exits after a
single OCR pass, while a hard image escalates through up to six variants and
four rotations before any external call is made.

### 10. AI fallback (`ai_engine.AIExtractor`)

Enabled by `AI_FALLBACK_ENABLED` and requires `OPENAI_API_KEY`. If the key is
absent the client is `None`, every method returns `None`, and the service runs
normally without this tier — an optional enhancement is never a hard dependency.

1. **`correct_mrz`** (`gpt-4o-mini`, `temperature=0.0`) — sends the noisy OCR text plus the cropped ROI image, requests corrected MRZ lines.
2. **`extract_full_data`** (`gpt-4o`, JSON mode with a non-JSON-mode retry) — full extraction of both the MRZ lines and the human-readable printed fields, enabling cross-verification between the two.

**The AI output is not trusted.** It is re-parsed through `parse_mrz`, re-scored
by `ConfidenceScorer`, and accepted only `if ai_score > best_score`. The checksum
remains the arbiter; the model is a generator of candidates, not an oracle.

Prompts explicitly forbid placeholder data and permit empty fields, because the
observed failure mode was confidently-formatted fabricated values — which is the
dangerous case, and which checksum validation independently catches.

**Privacy note:** this tier transmits a crop of the submitted document to a
third-party processor. That is a disclosure obligation, not only a technical
choice.

**The ROI crop is never written to disk.** It is handed to `AIExtractor` as an
in-memory numpy array and JPEG-encoded with `cv2.imencode` at the point of the
API call. An earlier version wrote it to a fixed filename in the working
directory and passed that path, which was both a PII leak onto the container
filesystem and a race: concurrent requests overwrote each other's crop between
the write and the read, so one caller's document could be sent to the vision API
inside another caller's request. A diagnostic dump is still available behind
`DEBUG_SAVE_ROI=true`, which writes UUID-named files to `DEBUG_ROI_DIR` and is
off by default.

---

## Response fields

Beyond the parsed MRZ fields, every response reports how the answer was obtained:

| Field | Meaning |
|---|---|
| `overall_confidence` | 0–100 score |
| `roi_method` | `CNN`, `MORPH` or `FALLBACK` |
| `preprocessing_method` | Winning variant, or `OpenAI-Correction` / `OpenAI-Vision` |
| `number_check_valid`, `birth_check_valid`, `expiry_check_valid` | Per-field checksum results |
| `any_corrected` | Whether brute-force correction was applied |
| `rotation` | Present if a non-zero rotation succeeded |

Reporting `roi_method` is deliberate observability: a rising share of `MORPH` or
`FALLBACK` in production is the signal that the segmentation model is degrading
against real-world input.

---

## Measured accuracy

See `accuracy_report.md`. Across 37 real documents (24 photos, 13 scanned PDFs):

- **33 of 37 files (89.2%) correct on every field**
- Field-level accuracy: given names, birth date, expiry date and sex **100%**; document number and issuer 97.3%; nationality 94.6%; surname 91.9%

**Surname is the weakest field, and this is structural rather than incidental.**
Document number, birth date and expiry date each carry their own check digit, so
errors there are detectable and correctable. Names are covered only by the
composite check digit over line 2 — and the name sits on line **1**. There is no
checksum over the name at all, so errors in it are undetectable by the standard's
own mechanism. The observed errors are exactly the expected homoglyph confusions
(`NOOTTIPPADATH` → `NGOTTIPPADATH`, `THOMAS` → `7HORAS`).

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.9 |
| Web framework | FastAPI |
| Server | Uvicorn (ASGI) |
| Computer vision | OpenCV (`opencv-python-headless`), NumPy |
| Model inference | ONNX via `cv2.dnn` — no ML framework dependency |
| OCR | Tesseract 5.x via `pytesseract` |
| PDF | `pdf2image` (Poppler) |
| AI fallback | OpenAI `gpt-4o-mini` / `gpt-4o` |
| Container | Docker (`python:3.9-slim-bookworm`) |
| Deployment | Render (Docker runtime); AWS ECS Fargate + ALB defined in `mrz-fargate-stack.yaml` |
| API gateway | Zuplo (API-key auth, per-consumer rate limiting) |

Running inference through `cv2.dnn` rather than a framework runtime avoids a
1–2 GB TensorFlow/PyTorch dependency in the image, which means faster cold
starts, smaller registry footprint and a reduced attack surface.

---

## Planned Improvements

Not implemented. Listed to keep intent separate from reality.

1. **Dual-bias OCR for name fields.** Names have no check digit, which is why they are the weakest field. A second OCR pass restricted to `A–Z<` would structurally prevent digit substitutions in names, reconciled against the MRZ-biased pass per character using Tesseract's own confidence data (`image_to_data`).
2. **Validate the composite check digit.** `line2[43]` is parsed but never verified; `ConfidenceScorer` already has a slot for `final_check_valid`. Lowest-effort accuracy win available.
3. **Arbitrary-angle deskew.** Only 90° rotations are handled. `cv2.minAreaRect` on the thresholded text blob plus `warpAffine` would correct genuine skew.
4. **CLAHE contrast enhancement** as an additional preprocessing variant.
5. **Non-blocking processing.** OCR and CV work are CPU-bound and synchronous, so they block the event loop. `run_in_executor` (or a plain `def` endpoint) would stop one slow image stalling concurrent requests.
6. **TD1/TD2 support.** Dispatch on line length plus a second field-offset table; the preprocessing, OCR and checksum layers are already format-agnostic.
7. **Replace `pytesseract` with `tesserocr`** to eliminate per-call subprocess spawn and temp-file I/O — likely the largest single latency win available.
8. **Upload validation.** No size or MIME-type limit is enforced; the OpenAPI spec documents a 10 MB cap that nothing implements.
9. **Unit tests and CI.** `ChecksumValidator` is pure and deterministic and should be unit-tested against known ICAO examples, with `test_accuracy.py` wired into CI as a regression gate.
