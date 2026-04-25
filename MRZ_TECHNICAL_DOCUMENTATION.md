# MRZ Extraction & Dual-Bias OCR Technical Documentation

## Overview
This document details the technical architecture of the MRZ (Machine Readable Zone) extraction pipeline. The system employs a "Correctness-First" approach, utilizing deep learning for segmentation and a novel **Dual-Bias OCR Strategy** to maximize accuracy, particularly for ambiguous characters in name fields.

## Core Pipeline

### 1. Preprocessing & Enhancement
Before extraction, images undergo a rigoruous enhancement pipeline to normalize quality:
- **Deskewing**: Automatic rotation correction using `cv2.minAreaRect` on binary thresholds to align text horizontally.
- **Denoising**: Fast Non-Local Means Denoising to remove sensor noise and compression artifacts.
- **Contrast Enhancement**: CLAHE (Contrast Limited Adaptive Histogram Equalization) applied to the L-channel (Lab color space) or grayscale to maximize text readability.
- **Sharpening**: Custom kernel convolution to define character edges.

### 2. Intelligent MRZ Localization
The system uses a hybrid approach to locate the MRZ:
1.  **Primary Path**: A custom `PassportPreprocessor` attempts to detect and crop the passport ID page.
2.  **Fallback Path (Deep Learning)**: If heuristic cropping fails, the image is passed to a pre-trained **ONNX Segmentation Network**. This model outputs a pixel-wise mask identifying the exact location of the MRZ, which is then contoured and cropped.
3.  **Rotation Search**: The system automatically attempts 0°, 90°, 180°, and 270° rotations if the initial pass yields no valid data.

## The Dual-Bias OCR Engine

Standard OCR often confuses similar characters (e.g., `0`/`O`, `1`/`I`, `5`/`S`), especially in MRZ fonts where context is limited. Our system solves this with a multi-pass reconciliation engine.

### Pass 1: MRZ-Biased Recognition
*   **Engine**: Tesseract via `pytesseract`
*   **Configuration**: `lang="mrz"`, `--psm 6` (Assume uniform block of text)
*   **Purpose**: Optimized for the specific OCR-B font used in passports. Excellent at Structure (<) and Numbers.
*   **Weakness**: Often misidentifies alphabetic characters in names as numbers (e.g., "MICH4EL" instead of "MICHAEL").

### Pass 2: Alphabet-Biased Recognition
*   **Engine**: Tesseract via `pytesseract`
*   **Configuration**: `lang="eng"`, Whitelist `A-Z<`
*   **Purpose**: Forced to recognize only uppercase letters and separators.
*   **Strength**: Highly accurate for Name fields (Surname/Given Names).

### Pass 3: Confidence-Based Reconciliation
A custom algorithm merges the two OCR outputs character-by-character:

1.  **Alignment**: The two strings are aligned and padded to matching lengths.
2.  **Confidence Mapping**: Per-character confidence scores are extracted from Tesseract.
3.  **Deterministic Heuristics**:
    *   **Agreement**: If both passes agree, accept the character.
    *   **Structure Lock**: If the MRZ-biased pass detects a chevron (`<`), it is prioritized (crucial for field separation).
    *   **Type enforcement**: If a character position falls within a known alphabetic region (like a Name), the Alphabet-biased result is preferred if the MRZ pass detected a digit.
    *   **Homoglyph Correction**: Specific logic handles `0/O`, `1/I`, `8/B` swaps based on region context.
    *   **Confidence Voting**: If heuristics are inconclusive, the character with the higher confidence score is selected.

## Validation & Semantic Correction
Post-OCR, the data is validated against ICAO 9303 standards:
-   **Checksum Verification**: Modulo-10 weighted checksums (7, 3, 1 weights) are calculated for document numbers, birth dates, and expiry dates.
-   **Logic Checks**: Ensures Expiry Date > Birth Date.
-   **Semantic Cleaning**:
    -   Fixes common separator errors (e.g., `NAME<SURNAME` corrected to `NAME<<SURNAME`).
    -   Removes garbage lines based on character composition analysis.
-   **Levenshtein-based Error Correction**: The `correct_ocr_errors` function provides a final correction layer, using Levenshtein distance to fix single-character mistakes in fields by comparing them against a valid character set.

## Tech Stack
*   **Language**: Python 3.9
*   **Web Framework**: FastAPI
*   **Server**: Uvicorn
*   **Computer Vision**: OpenCV (`cv2`), NumPy
*   **Deep Learning**: ONNX Runtime
*   **OCR**: Tesseract 5.x (`pytesseract` wrapper)
*   **PDF Processing**: `pdf2image` (Poppler)
*   **Containerization**: Docker
*   **Cloud Deployment**: AWS ECS Fargate, Application Load Balancer
*   **API Gateway**: Zuplo
