# MRZ Extraction Configuration
import os

# Detect operating system
IS_WINDOWS = os.name == 'nt'

# ROI Extraction Settings
ROI_INPUT_SIZE = (256, 256)
ROI_PADDING = 10
ROI_MIN_ASPECT_RATIO = 5.0  # MRZ is usually wide
ROI_MAX_ASPECT_RATIO = 20.0
ROI_MIN_CONFIDENCE = 0.5    # Threshold for neural net mask

# Tesseract OCR Settings - PLATFORM AWARE
if IS_WINDOWS:
    TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  
    TESSDATA_PREFIX = r'C:\Program Files\Tesseract-OCR\tessdata' 
else:
    # Use standard Linux path and point it to your local mrz.traineddata package
    TESSERACT_CMD = '/usr/bin/tesseract' 
    TESSDATA_PREFIX = None

OEM_MODES = [3]  
PSM_MODES = [6]

# Configuration
TEST_IMAGES_DIR = "./test_images"       # Point to the new image folder
GROUND_TRUTH_FILE = "./ground_truth.json" # Point to the new answer key


# Preprocessing Settings
MIN_IMAGE_WIDTH = 1800
MORPH_KERNEL_SIZE = (3, 3)
BW_THRESHOLD_BLOCK_SIZE = 11
BW_THRESHOLD_C = 2

# Correction Settings
CONFIDENCE_THRESHOLD_HIGH = 80
CONFIDENCE_THRESHOLD_LOW = 50
MAX_CHECKSUM_CORRECTION_ATTEMPTS = 36 # A-Z + 0-9

# Character Whitelists
WHITELIST_NUMERIC = "0123456789<"
WHITELIST_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ<"
WHITELIST_ALPHANUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"

# Common OCR Confusions (Map FROM -> TO)
# We use this for bruteforce correction and initial sanitization
OCR_CONFUSIONS = {
    '0': ['O', 'Q', 'D'],
    'O': ['0', 'Q', 'D'],
    '1': ['I', 'L', '7'],
    'I': ['1', 'L', '7'],
    '5': ['S'],
    'S': ['5'],
    '8': ['B', '3'],
    'B': ['8', '3'],
    '2': ['Z'],
    'Z': ['2'],
    '6': ['G'],
    'G': ['6'],
    '4': ['A'],
    'A': ['4']
}

# Parameters for weighted scoring
SCORE_WEIGHT_CHECKSUM = 75
SCORE_WEIGHT_COMPLETENESS = 20
SCORE_WEIGHT_LOGIC = 5

# AI Fallback Configuration
AI_FALLBACK_ENABLED = os.getenv("AI_FALLBACK_ENABLED", "true").lower() == "true"
AI_CONFIDENCE_THRESHOLD = int(os.getenv("AI_CONFIDENCE_THRESHOLD", 95))
OPENAI_MODEL_CORRECTION = os.getenv("OPENAI_MODEL_CORRECTION", "gpt-4o-mini")
OPENAI_MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o")
