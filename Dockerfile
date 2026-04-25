# Use a lightweight Debian-based image with Python pre-installed
FROM python:3.9-slim-bullseye

# Prevent prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install System Dependencies: Tesseract, OpenCV, and Poppler
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# --- ⭐️ FINAL FIX: CORRECTED PATH TO THE CUSTOM TESSERACT MRZ MODEL ⭐️ ---
# Tesseract in this container looks for data in /usr/share/tesseract-ocr/4.00/tessdata
# We copy our custom model from its correct location into that directory.
COPY ./fastmrz/tessdata/mrz.traineddata /usr/share/tesseract-ocr/4.00/tessdata/mrz.traineddata

WORKDIR /app

# Copy Python requirements first to leverage Docker caching
COPY requirements.txt .

# Install all Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Set environment variables
ENV PORT=5000
ENV PYTHONUNBUFFERED=1

# Expose the API port
EXPOSE 5000

# Command to run the FastAPI server using Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]