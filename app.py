# filepath: p:\Passport_MRZ\app.py
import os
import tempfile
import uvicorn
import base64
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging
import pytesseract
import platform
import uuid


# Import your existing, powerful extractor
from improved_mrz_extractor import MRZExtractor

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ISOLATE TESSERACT TEMP FILES ---
# Create a unique directory for this instance to prevent temp-file collisions.
# NOTE: this must NOT be assigned to TESSDATA_PREFIX. That variable tells Tesseract
# where to find its .traineddata language files, not where to put temp files.
# Pointing it at an empty directory makes `lang='mrz'` fail with "Failed loading
# language 'mrz'", which run_ocr() swallows, yielding an empty raw_text.
# TMPDIR is the variable that actually controls scratch files for the subprocess.
TESSERACT_TEMP_DIR = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
os.makedirs(TESSERACT_TEMP_DIR, exist_ok=True)
os.environ['TMPDIR'] = TESSERACT_TEMP_DIR

logger.info(f"Using isolated Tesseract temp directory: {TESSERACT_TEMP_DIR}")

# --- Environment-Aware Tesseract Path Configuration ---
if platform.system() == "Windows":
    tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    else:
        logger.error("Tesseract not found at default Windows path. Please install or update path.")
else:
    # Path for the Linux Docker container (installed via apt-get)
    pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

logger.info(f"Running on {platform.system()}. Pytesseract command set to: {pytesseract.pytesseract.tesseract_cmd}")
# ----------------------------------------------------------------

app = FastAPI(title="High-Performance MRZ Scanner API")

# Allow all origins for simplicity, can be locked down later
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Load Model on Startup ---
logger.info("Initializing MRZ Extractor Model...")
model_path = os.path.join(os.path.dirname(__file__), "fastmrz", "fastmrz", "model", "mrz_seg.onnx")
extractor = MRZExtractor(model_path=model_path)
logger.info(" Model loaded successfully. API is ready for requests.")

# Pydantic model for the Base64 request body
class Base64Request(BaseModel):
    image_base64: str

def process_and_cleanup(file_path: str):
    """Helper function to process a file and ensure it gets deleted."""
    try:
        logger.info(f"Processing file: {file_path}")
        result = extractor.process(file_path)

        if not result.get("success"):
            # This is correct: raise a 400 if extraction fails.
            raise HTTPException(status_code=400, detail=result)
        
        return result
    finally:
        # This cleanup happens regardless of success or failure.
        if os.path.exists(file_path):
            os.unlink(file_path)

@app.post("/api/mrz/process")
async def process_mrz_upload(image: UploadFile = File(...)):
    """Handles multipart/form-data image uploads for MRZ extraction."""
    temp_path = None
    try:
        # FIX: Handle the possibility of a missing filename to satisfy the type checker.
        filename = image.filename or ""
        suffix = os.path.splitext(filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await image.read())
            temp_path = tmp.name
        
        # Call the processing function
        return process_and_cleanup(temp_path)

    except HTTPException:
        # FIX: Re-raise the HTTPException to let FastAPI handle it correctly.
        raise
    except Exception as e:
        # This now only catches unexpected errors (e.g., file system errors).
        logger.error(f"An unexpected error occurred during file upload: {e}", exc_info=True)
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path) # Manual cleanup on unexpected error
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

@app.post("/api/mrz/process-base64")
async def process_mrz_base64(request: Base64Request):
    """Handles JSON Base64 image uploads for MRZ extraction."""
    temp_path = None
    try:
        img_data = base64.b64decode(request.image_base64.split(',')[-1])
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(img_data)
            temp_path = tmp.name

        return process_and_cleanup(temp_path)

    except HTTPException:
        # FIX: Re-raise the HTTPException.
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred during base64 processing: {e}", exc_info=True)
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

@app.get("/healthMrz")
def health_check():
    """A simple health check endpoint."""
    return {"status": "OK", "message": "MRZ Backend (FastAPI) is running"}

@app.get("/")
async def read_root():
    """This is what users see when they visit the main URL."""
    return {
        "message": "Welcome to the Passport MRZ API!",
        "docs_url": "Visit /docs to test the API"
    }

@app.get("/status")
async def check_status():
    """Reports real runtime state rather than a hardcoded value.

    Checks the two things that actually have to work for /api/mrz/process to
    succeed: the ONNX segmentation model, and Tesseract with the custom 'mrz'
    language pack. Returns 200 when healthy, 503 when degraded, so uptime
    checks and Render health checks see a genuine failure.
    """
    checks = {}

    # 1. ONNX segmentation model
    try:
        checks["model_loaded"] = bool(extractor) and os.path.isfile(model_path)
        checks["model_path"] = model_path
    except Exception as e:
        checks["model_loaded"] = False
        checks["model_error"] = str(e)

    # 2. Tesseract binary
    try:
        checks["tesseract_version"] = str(pytesseract.get_tesseract_version())
        checks["tesseract_available"] = True
    except Exception as e:
        checks["tesseract_available"] = False
        checks["tesseract_error"] = str(e)

    # 3. The 'mrz' language pack - the piece that silently breaks OCR when absent
    try:
        langs = pytesseract.get_languages(config="")
        checks["languages"] = sorted(langs)
        checks["mrz_language_available"] = "mrz" in langs
    except Exception as e:
        checks["mrz_language_available"] = False
        checks["languages_error"] = str(e)

    checks["tessdata_prefix"] = os.environ.get("TESSDATA_PREFIX", "(unset - using Tesseract default)")

    healthy = (
        checks.get("model_loaded")
        and checks.get("tesseract_available")
        and checks.get("mrz_language_available")
    )
    checks["status"] = "Online" if healthy else "Degraded"

    if not healthy:
        return JSONResponse(status_code=503, content=checks)
    return checks

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
