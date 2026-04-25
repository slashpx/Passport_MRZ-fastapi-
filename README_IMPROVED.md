
# Improved MRZ Extractor Module

This module replaces the logic in `fastmrz` with a robust, multi-pass extraction engine designed to increase accuracy from ~50% to 85%+.

## Features

1.  **Multi-Pass OCR & Voting**: Runs 4 different preprocessing variants (Otsu, Blur, Adaptive, Shadow Removal) and votes on the best result based on checksum validation and field completeness.
2.  **Character Correction**: Uses brute-force checksum validation to repair single-character OCR errors (e.g., 'O' vs '0', 'I' vs '1') contextually.
3.  **Robust ROI Extraction**: improved `cv2.dnn` usage with morphological fallbacks if the neural network fails.
4.  **Confidence Scoring**: Returns a confidence score (0-100) allowing you to flag uncertain extractions for manual review (recommend threshold: 60).
5.  **TD3 Support**: Optimized for standard passport MRZ (2 lines, 44 characters).

## Files

*   `improved_mrz_extractor.py`: The main module containing all classes.
*   `config.py`: Configuration file for tuning thresholds, paths, and weights.
*   `integration_example.py`: Examples of how to call the new extractor from Python or Node.js.
*   `test_accuracy.py`: A script to run against a directory of images and compare with ground truth.

## Usage

### Python

```python
from improved_mrz_extractor import MRZExtractor

# Path to the ONNX model (same as existing project)
model_path = "./fastmrz/fastmrz/model/mrz_seg.onnx"

extractor = MRZExtractor(model_path)
result = extractor.process("path/to/passport.jpg")

if result['success']:
    print(f"Document Number: {result['document_number']}")
    print(f"Confidence: {result['overall_confidence']}")
else:
    print("Extraction failed")
```

### Node.js Integration

Replace your current `python_bridge.py` logic or point `server.js` to use `integration_example.py`.

The input/output format remains JSON-based for easy compatibility.

## Tuning

Edit `config.py` to adjust:
*   `CONFIDENCE_THRESHOLD_LOW/HIGH`: Adjust strictness of validation.
*   `TESSERACT_CMD`: If Tesseract is not in your system PATH.
*   `ROI_INPUT_SIZE`: Resolution for the segmentation neural network.

## Testing

1.  Create a folder `test_images/`.
2.  (Optional) Create `ground_truth.json`.
3.  Run:
    ```bash
    python3 test_accuracy.py
    ```

## Requirements
*   opencv-python-headless (or opencv-python)
*   pytesseract
*   numpy
