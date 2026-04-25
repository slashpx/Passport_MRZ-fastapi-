# MRZ Processing Flow Documentation

This document elaborates on the complete technical flow of a file uploaded by a user for MRZ (Machine Readable Zone) extraction within the containerized FastAPI application.

## 1. API Gateway & Load Balancer
**Endpoint:** `POST /api/mrz/process`

*   **Entry Point**: The user's request first hits the **Zuplo API Gateway**, which handles authentication (API key), rate limiting, and other security policies.
*   **Routing**: Zuplo forwards the validated request to the **AWS Application Load Balancer (ALB)**.
*   **Distribution**: The ALB distributes the request to one of the available, healthy **ECS Fargate tasks** running the application container.

## 2. FastAPI Application Entry
Inside the container, the request is received by the Uvicorn server running the FastAPI application (`app.py`).

*   **Input**: FastAPI receives a `multipart/form-data` request containing an image or PDF file in the `image` field.
*   **Temporary Storage**: The uploaded file is temporarily saved to a unique, isolated directory in the container's ephemeral storage. This prevents file collisions when multiple requests are processed concurrently.

## 3. Python Processing & Preprocessing
The `MRZExtractor` class from `improved_mrz_extractor.py` is invoked to process the file.

### A. Input Handling
*   **PDFs**: If the input is a PDF, it is converted into a list of images (one per page) using `pdf2image`.
*   **Images**: Loaded directly into memory using OpenCV.

### B. Image Preprocessing
Before attempting to read the MRZ, the image undergoes several enhancement steps to improve accuracy:
1.  **Deskewing**: Corrects the image rotation to align text horizontally.
2.  **Shadow Removal**: A custom algorithm normalizes brightness and removes shadows from the background, making the text clearer.
3.  **Contrast Enhancement**: Uses **CLAHE** (Contrast Limited Adaptive Histogram Equalization) to make text stand out.
4.  **Sharpening**: Convolves the image with a sharpening kernel to better define character edges.

## 4. MRZ Detection & Segmentation
Instead of scanning the whole image for text, the system locates the MRZ region first:

1.  **Neural Network Segmentation**:
    *   The preprocessed image is passed to a pre-trained **ONNX Segmentation Network** (`mrz_seg.onnx`).
    *   The model outputs a segmentation mask highlighting the MRZ region.
2.  **Region of Interest (ROI) Extraction**:
    *   Contours are found on the segmentation mask to create a bounding box.
    *   The original high-resolution image is cropped to this bounding box.
3.  **ROI Refinement**:
    *   The cropped MRZ region undergoes a second pass of thresholding and morphological operations to prepare it strictly for OCR.

## 5. OCR (Optical Character Recognition)
The processed MRZ crop is passed to **Tesseract OCR** (`pytesseract`).
*   **Configuration**: Uses the custom-trained `mrz` language model (`mrz.traineddata`) which is optimized for the OCR-B font.
*   **Output**: Raw text string from the image.

## 6. Parsing & Data Extraction
The raw text is cleaned and parsed:
1.  **Cleaning**: Removes whitespace and filters for lines that look like MRZ data (correct length, contains `<<<`).
2.  **Field Extraction**: The system parses the standard MRZ formats (TD1, TD2, TD3).
    *   **Document Type**: e.g., Passport (P), ID Card (I).
    *   **Issuer, Surname, Given Names, Document Number, Nationality, Birth Date, Sex, Expiry Date**.
3.  **Validation & Correction**:
    *   **Checksums**: Verification digits (weighted modulo 10) are calculated for numbers and dates to ensure they were read correctly.
    *   **Error Correction**: A Levenshtein distance-based algorithm (`correct_ocr_errors`) is used to fix common OCR mistakes by comparing the extracted fields against a known, valid character set.

## 7. Response Flow
1.  **Result Compilation**: The `MRZExtractor` returns a Python dictionary with all extracted fields and a success status.
2.  **JSON Output**: The FastAPI endpoint returns this dictionary as a JSON response with a `200 OK` status.
3.  **Cleanup**: The temporary directory and uploaded file are deleted from the container.
4.  **Client Response**: The JSON response travels back through the ALB and Zuplo to the end-user.
