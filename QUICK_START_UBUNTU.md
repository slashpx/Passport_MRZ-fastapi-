# Quick Start Guide - Ubuntu Server

## Quick Installation (Automated)

```bash
# 1. Clone or upload your project to the server
cd /opt  # or your preferred directory
# Upload your project files here

# 2. Run the deployment script
bash deploy.sh

# 3. Update ecosystem.config.js with your project path
nano ecosystem.config.js
# Change: cwd: '/path/to/pdetest' to your actual path

# 4. Start the application
pm2 start ecosystem.config.js
pm2 save
pm2 startup  # Follow instructions
```

## Manual Installation (Step by Step)

### 1. System Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-eng
sudo apt install -y libopencv-dev python3-opencv libjpeg-dev libpng-dev
```

### 2. Node.js
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### 3. Copy MRZ Trained Data
```bash
sudo cp fastmrz/tessdata/mrz.traineddata /usr/share/tesseract-ocr/5/tessdata/
# Or: sudo cp fastmrz/tessdata/mrz.traineddata /usr/share/tesseract-ocr/4.00/tessdata/
```

### 4. Python Setup
```bash
python3 -m venv venv
source venv/bin/activate
cd fastmrz
pip install -r requirements.txt
cd ..
```

### 5. Node.js Setup
```bash
npm install
```

### 6. Environment
```bash
cp .env.example .env
# Edit .env if needed (usually not required)
```

### 7. PM2 Setup
```bash
sudo npm install -g pm2
# Edit ecosystem.config.js with your path
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## Verify Installation

```bash
# Test Python
source venv/bin/activate
python3 -c "from fastmrz import FastMRZ; print('OK')"

# Test Tesseract
tesseract --version

# Test Node.js
node --version
npm --version

# Test API
curl http://localhost:3000/health
```

## Common Commands

```bash
# Start/Stop/Restart
pm2 start ecosystem.config.js
pm2 stop mrz-backend
pm2 restart mrz-backend
pm2 logs mrz-backend

# View status
pm2 status

# Check if running
curl http://localhost:3000/health
```

## Troubleshooting

**Tesseract not found:**
```bash
which tesseract
# Add to .env: TESSERACT_PATH=/usr/bin/tesseract
```

**Port in use:**
```bash
sudo lsof -i :3000
# Or change PORT in .env
```

**Permission denied:**
```bash
chmod 755 uploads
chown -R $USER:$USER .
```

## Package Summary

### System Packages
- `python3`, `python3-pip`, `python3-venv`
- `tesseract-ocr`, `tesseract-ocr-eng`
- `nodejs`, `npm`
- `libopencv-dev`, `python3-opencv`
- `libjpeg-dev`, `libpng-dev`

### Python Packages (via pip)
- `opencv-python>=4.9.0.80`
- `pytesseract>=0.3.10`
- `numpy`
- `Pillow`

### Node.js Packages (via npm)
- `express`
- `multer`
- `cors`
- `dotenv`
- `pm2` (global)

### Files to Copy
- `fastmrz/tessdata/mrz.traineddata` → `/usr/share/tesseract-ocr/5/tessdata/`

