#!/bin/bash

# Ubuntu Server Deployment Script for MRZ Backend
# Run this script with: bash deploy.sh

set -e  # Exit on error

echo "=========================================="
echo "MRZ Backend - Ubuntu Deployment Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root and set SUDO prefix
if [ "$EUID" -eq 0 ]; then 
   echo -e "${YELLOW}Warning: Running as root. Sudo commands will be skipped.${NC}"
   SUDO=""
else
   SUDO="sudo"
fi

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
$SUDO apt update
$SUDO apt upgrade -y

echo -e "${GREEN}Step 2: Installing Python 3 and pip...${NC}"
$SUDO apt install -y python3 python3-pip python3-venv

echo -e "${GREEN}Step 3: Installing Tesseract OCR...${NC}"
$SUDO apt install -y tesseract-ocr tesseract-ocr-eng

# Check Tesseract installation
if command -v tesseract &> /dev/null; then
    echo -e "${GREEN}Tesseract installed: $(tesseract --version | head -n1)${NC}"
else
    echo -e "${RED}Tesseract installation failed!${NC}"
    exit 1
fi

# Copy MRZ traineddata
echo -e "${GREEN}Step 4: Copying MRZ traineddata...${NC}"
TESSDATA_DIR="/usr/share/tesseract-ocr"
if [ -d "$TESSDATA_DIR/5" ]; then
    TESSDATA_PATH="$TESSDATA_DIR/5/tessdata"
elif [ -d "$TESSDATA_DIR/4.00" ]; then
    TESSDATA_PATH="$TESSDATA_DIR/4.00/tessdata"
else
    TESSDATA_PATH="$TESSDATA_DIR/tessdata"
fi

if [ -f "fastmrz/tessdata/mrz.traineddata" ]; then
    $SUDO cp fastmrz/tessdata/mrz.traineddata "$TESSDATA_PATH/"
    echo -e "${GREEN}MRZ traineddata copied to $TESSDATA_PATH${NC}"
else
    echo -e "${YELLOW}Warning: fastmrz/tessdata/mrz.traineddata not found${NC}"
fi

echo -e "${GREEN}Step 5: Installing Node.js...${NC}"
if ! command -v node &> /dev/null; then
    if [ "$EUID" -eq 0 ]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    else
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    fi
    $SUDO apt install -y nodejs
else
    echo -e "${GREEN}Node.js already installed: $(node --version)${NC}"
fi

echo -e "${GREEN}Step 6: Installing OpenCV dependencies...${NC}"
$SUDO apt install -y libopencv-dev python3-opencv libjpeg-dev libpng-dev libtiff-dev

echo -e "${GREEN}Step 7: Setting up Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

echo -e "${GREEN}Step 8: Installing Python dependencies...${NC}"
cd fastmrz
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    pip install opencv-python>=4.9.0.80 pytesseract>=0.3.10 numpy Pillow
fi
cd ..

echo -e "${GREEN}Step 9: Installing Node.js dependencies...${NC}"
npm install

echo -e "${GREEN}Step 10: Creating necessary directories...${NC}"
mkdir -p uploads logs
chmod 755 uploads logs

echo -e "${GREEN}Step 11: Setting up environment file...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}.env file created from .env.example${NC}"
    else
        echo "PORT=3000" > .env
        echo -e "${GREEN}.env file created with default values${NC}"
    fi
else
    echo -e "${YELLOW}.env file already exists, skipping...${NC}"
fi

echo -e "${GREEN}Step 12: Installing PM2 globally...${NC}"
if ! command -v pm2 &> /dev/null; then
    $SUDO npm install -g pm2
else
    echo -e "${GREEN}PM2 already installed${NC}"
fi

echo -e "${GREEN}Step 13: Updating ecosystem.config.js with current path...${NC}"
CURRENT_DIR=$(pwd)
sed -i "s|/path/to/pdetest|$CURRENT_DIR|g" ecosystem.config.js 2>/dev/null || echo -e "${YELLOW}Could not update ecosystem.config.js automatically${NC}"
echo -e "${YELLOW}Please manually update the 'cwd' path in ecosystem.config.js to: $CURRENT_DIR${NC}"

echo ""
echo -e "${GREEN}=========================================="
echo -e "Deployment Complete!"
echo -e "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Update ecosystem.config.js with the correct path"
echo "2. Test the installation:"
echo "   source venv/bin/activate"
echo "   python3 -c 'from fastmrz import FastMRZ; print(\"OK\")'"
echo "3. Start the server:"
echo "   pm2 start ecosystem.config.js"
echo "   pm2 save"
echo "   pm2 startup"
echo ""
echo "4. (Optional) Setup Nginx reverse proxy (see DEPLOYMENT.md)"
echo ""

