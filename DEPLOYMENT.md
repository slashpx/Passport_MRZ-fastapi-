# Ubuntu Server Deployment Guide

Complete guide for deploying the MRZ Backend on Ubuntu server.

## Prerequisites

- Ubuntu 18.04+ (20.04 or 22.04 recommended)
- Root or sudo access
- Internet connection

## Step 1: System Updates

```bash
sudo apt update
sudo apt upgrade -y
```

## Step 2: Install Python 3.8+ and pip

```bash
sudo apt install -y python3 python3-pip python3-venv
python3 --version  # Should be 3.8 or higher
```

## Step 3: Install Tesseract OCR

```bash
# Install Tesseract OCR engine
sudo apt install -y tesseract-ocr

# Install additional language data (optional but recommended)
sudo apt install -y tesseract-ocr-eng

# Verify installation
tesseract --version

# Copy the MRZ trained data file
# The mrz.traineddata file should be in fastmrz/tessdata/
# Copy it to Tesseract's tessdata directory
sudo cp fastmrz/tessdata/mrz.traineddata /usr/share/tesseract-ocr/5/tessdata/
# Or for older versions:
# sudo cp fastmrz/tessdata/mrz.traineddata /usr/share/tesseract-ocr/4.00/tessdata/
```

## Step 4: Install Node.js and npm

### Option A: Using NodeSource (Recommended - Latest LTS)

```bash
# Install Node.js 20.x LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify installation
node --version
npm --version
```

### Option B: Using Ubuntu Repository

```bash
sudo apt install -y nodejs npm
```

## Step 5: Install System Dependencies for OpenCV

```bash
# Install OpenCV dependencies
sudo apt install -y libopencv-dev python3-opencv
# Or if the above doesn't work:
sudo apt install -y python3-opencv libopencv-contrib-python

# Install additional image processing libraries
sudo apt install -y libjpeg-dev libpng-dev libtiff-dev
sudo apt install -y libavcodec-dev libavformat-dev libswscale-dev
sudo apt install -y libv4l-dev libxvidcore-dev libx264-dev
```

## Step 6: Setup Python Environment

```bash
# Navigate to project directory
cd /path/to/pdetest

# Create virtual environment (recommended)
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
cd fastmrz
pip install --upgrade pip
pip install -r requirements.txt

# If requirements.txt doesn't exist, install manually:
pip install opencv-python>=4.9.0.80
pip install pytesseract>=0.3.10
pip install numpy
pip install Pillow

# Go back to project root
cd ..
```

## Step 7: Install Node.js Dependencies

```bash
# Make sure you're in the project root directory
cd /path/to/pdetest

# Install Node.js dependencies
npm install
```

## Step 8: Configure Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env file (optional - Tesseract is usually in PATH on Ubuntu)
nano .env
```

**`.env` file content:**
```env
# Port for the Express server
PORT=3000

# Tesseract path (usually not needed on Ubuntu as it's in PATH)
# TESSERACT_PATH=/usr/bin/tesseract
```

## Step 9: Test the Installation

```bash
# Test Python FastMRZ
cd fastmrz
python3 -c "from fastmrz import FastMRZ; print('FastMRZ imported successfully')"

# Test Node.js server (in project root)
cd ..
node server.js
# Or in background:
# nohup node server.js > server.log 2>&1 &
```

## Step 10: Setup as a System Service (PM2 - Recommended)

### Install PM2

```bash
sudo npm install -g pm2
```

### Create PM2 Ecosystem File

Create `ecosystem.config.js`:

```javascript
module.exports = {
  apps: [{
    name: 'mrz-backend',
    script: 'server.js',
    instances: 1,
    exec_mode: 'fork',
    env: {
      NODE_ENV: 'production',
      PORT: 3000
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G'
  }]
};
```

### Start with PM2

```bash
# Create logs directory
mkdir -p logs

# Start the application
pm2 start ecosystem.config.js

# Save PM2 configuration
pm2 save

# Setup PM2 to start on system boot
pm2 startup
# Follow the instructions it provides
```

### PM2 Useful Commands

```bash
pm2 status              # Check status
pm2 logs mrz-backend    # View logs
pm2 restart mrz-backend # Restart
pm2 stop mrz-backend    # Stop
pm2 delete mrz-backend  # Remove from PM2
```

## Step 11: Setup Nginx Reverse Proxy (Optional but Recommended)

### Install Nginx

```bash
sudo apt install -y nginx
```

### Configure Nginx

Create `/etc/nginx/sites-available/mrz-backend`:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain or IP

    # Increase body size limit for image uploads
    client_max_body_size 10M;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Timeout settings
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

### Enable and Start Nginx

```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/mrz-backend /etc/nginx/sites-enabled/

# Test Nginx configuration
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx

# Enable Nginx to start on boot
sudo systemctl enable nginx
```

## Step 12: Setup SSL with Let's Encrypt (Optional)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is set up automatically
```

## Step 13: Firewall Configuration

```bash
# Allow SSH (if not already configured)
sudo ufw allow 22/tcp

# Allow HTTP
sudo ufw allow 80/tcp

# Allow HTTPS (if using SSL)
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

## Step 14: Directory Structure and Permissions

```bash
# Set proper permissions
sudo chown -R $USER:$USER /path/to/pdetest
chmod -R 755 /path/to/pdetest

# Create uploads directory with proper permissions
mkdir -p uploads
chmod 755 uploads
```

## Step 15: Verify Everything Works

```bash
# Test the API endpoint
curl http://localhost:3000/health

# Test with an image (if you have one)
curl -X POST http://localhost:3000/api/mrz/process \
  -F "image=@fastmrz/data/passport_uk.jpg"
```

## Troubleshooting

### Tesseract Not Found

```bash
# Find Tesseract path
which tesseract

# Update .env file with correct path
echo "TESSERACT_PATH=$(which tesseract)" >> .env
```

### OpenCV Import Error

```bash
# Install OpenCV for Python
pip install opencv-python-headless
# or
sudo apt install python3-opencv
```

### Port Already in Use

```bash
# Find process using port 3000
sudo lsof -i :3000

# Kill the process or change PORT in .env
```

### Permission Denied

```bash
# Make sure uploads directory is writable
chmod 777 uploads
# Or better, set proper ownership
chown -R $USER:$USER uploads
```

### Python Module Not Found

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r fastmrz/requirements.txt
```

## Monitoring and Maintenance

### View Logs

```bash
# PM2 logs
pm2 logs mrz-backend

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Application logs (if using PM2)
tail -f logs/out.log
tail -f logs/err.log
```

### Update Application

```bash
# Pull latest code
git pull  # if using git

# Update dependencies
source venv/bin/activate
pip install -r fastmrz/requirements.txt --upgrade
npm install

# Restart application
pm2 restart mrz-backend
```

## Security Considerations

1. **Firewall**: Only open necessary ports
2. **SSL**: Use HTTPS in production
3. **Environment Variables**: Never commit `.env` file
4. **File Uploads**: Regularly clean the `uploads/` directory
5. **Updates**: Keep system and dependencies updated
6. **User Permissions**: Run Node.js as non-root user

## Quick Deployment Checklist

- [ ] System updated
- [ ] Python 3.8+ installed
- [ ] Tesseract OCR installed and MRZ traineddata copied
- [ ] Node.js installed
- [ ] OpenCV dependencies installed
- [ ] Python virtual environment created and dependencies installed
- [ ] Node.js dependencies installed
- [ ] Environment variables configured
- [ ] Application tested
- [ ] PM2 configured (optional)
- [ ] Nginx configured (optional)
- [ ] Firewall configured
- [ ] SSL certificate installed (optional)
- [ ] Monitoring setup

## Support

For issues, check:
1. Application logs: `pm2 logs mrz-backend`
2. System logs: `journalctl -u nginx` or `journalctl -xe`
3. Python errors: Check if virtual environment is activated
4. Tesseract: Verify `tesseract --version` and MRZ traineddata location

