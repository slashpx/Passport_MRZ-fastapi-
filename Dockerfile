# Debian bookworm: bullseye is EOL and its security mirrors now 404 on
# libglib2.0-0 / poppler / tiff, which breaks `apt-get install` at build time.
FROM python:3.9-slim-bookworm

# Prevent prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install System Dependencies: Tesseract, OpenCV, and Poppler
# NOTE: on bookworm, libgl1-mesa-glx no longer exists - it is now libgl1.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# --- Install the custom Tesseract MRZ model ---
# The tessdata directory is version-dependent (4.00 on bullseye, 5 on bookworm),
# so locate it at build time instead of hardcoding the path.
COPY ./fastmrz/tessdata/mrz.traineddata /tmp/mrz.traineddata
RUN TESSDATA_DIR="$(dirname "$(find /usr/share -name eng.traineddata -print -quit)")" \
    && [ -n "$TESSDATA_DIR" ] || { echo "FATAL: tessdata dir not found"; exit 1; } \
    && mv /tmp/mrz.traineddata "$TESSDATA_DIR/mrz.traineddata" \
    && echo "Installed mrz.traineddata into $TESSDATA_DIR" \
    && tesseract --list-langs

WORKDIR /app

# Copy Python requirements first to leverage Docker caching
COPY requirements.txt .

# Install all Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Fail the build now, not at runtime, if the ONNX segmentation model is missing
RUN test -s fastmrz/fastmrz/model/mrz_seg.onnx \
    || { echo "FATAL: fastmrz/fastmrz/model/mrz_seg.onnx missing or empty"; exit 1; }

ENV PYTHONUNBUFFERED=1

# Render injects its own $PORT; default to 5000 for local runs.
ENV PORT=5000
EXPOSE 5000

# Shell form so $PORT is expanded at runtime rather than baked in.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-5000}
