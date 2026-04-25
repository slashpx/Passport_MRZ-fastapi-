# MRZ Backend - Node.js Express API

A Node.js Express backend that processes images to detect and extract Machine Readable Zone (MRZ) data from passports and other documents using the FastMRZ Python library.

## Features

- 🖼️ Accept image uploads via multipart/form-data
- 📤 Accept base64 encoded images via JSON
- 🔍 Automatic MRZ detection and OCR text extraction
- 📋 Returns parsed user details in JSON format
- ✅ Includes checksum validation
- 🚀 RESTful API endpoints

## Prerequisites

1. **Node.js** (v14 or higher)
2. **Python 3.8+** with FastMRZ installed
3. **Tesseract OCR** installed and configured
4. FastMRZ Python package installed in the `fastmrz` directory

## Installation

1. Install Node.js dependencies:
```bash
npm install
```

2. Install Python dependencies (if not already done):
```bash
cd fastmrz
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and configure if needed:
```bash
cp .env.example .env
```

Edit `.env` if Tesseract is not in your PATH:
```
TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

## Running the Server

### Development mode (with auto-reload):
```bash
npm run dev
```

### Production mode:
```bash
npm start
```

The server will start on `http://localhost:3000` (or the port specified in `.env`).

## API Endpoints

### 1. Health Check
```
GET /health
```
Returns server status.

**Response:**
```json
{
  "status": "OK",
  "message": "MRZ Backend is running"
}
```

### 2. Process Image (File Upload)
```
POST /api/mrz/process
Content-Type: multipart/form-data
```

**Request:**
- Form field: `image` (file)
- Query params (optional):
  - `ignore_parse` (boolean): Return raw MRZ text instead of parsed JSON (default: false)
  - `include_checkdigit` (boolean): Include checkdigit in response (default: true)

**Example using curl:**
```bash
curl -X POST http://localhost:3000/api/mrz/process \
  -F "image=@path/to/passport.jpg" \
  -F "ignore_parse=false" \
  -F "include_checkdigit=true"
```

**Example using JavaScript (FormData):**
```javascript
const formData = new FormData();
formData.append('image', fileInput.files[0]);

fetch('http://localhost:3000/api/mrz/process?ignore_parse=false&include_checkdigit=true', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => console.log(data));
```

**Success Response:**
```json
{
  "status": "SUCCESS",
  "mrz_type": "TD3",
  "document_code": "P",
  "issuer_code": "GBR",
  "surname": "PUDARSAN",
  "given_name": "HENERT",
  "document_number": "707797979",
  "nationality_code": "GBR",
  "birth_date": "1995-05-20",
  "sex": "M",
  "expiry_date": "2017-04-22",
  "optional_data": "",
  "mrz_text": "P<GBRPUDARSAN<<HENERT<<<<<<<<<<<<<<<<<<<<<<<\n7077979792GBR9505209M1704224<<<<<<<<<<<<<<00"
}
```

**Error Response:**
```json
{
  "status": "ERROR",
  "status_message": "No MRZ detected"
}
```

### 3. Process Image (Base64)
```
POST /api/mrz/process-base64
Content-Type: application/json
```

**Request Body:**
```json
{
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
}
```

**Query params:** Same as `/api/mrz/process`

**Example using JavaScript:**
```javascript
const base64Image = 'data:image/jpeg;base64,/9j/4AAQSkZJRg...';

fetch('http://localhost:3000/api/mrz/process-base64?ignore_parse=false', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ image: base64Image })
})
.then(response => response.json())
.then(data => console.log(data));
```

## Response Fields

When `ignore_parse=false` (default), the response includes:

- `status`: "SUCCESS" or "FAILURE"
- `mrz_type`: "TD1", "TD2", "TD3", "MRVA", or "MRVB"
- `document_code`: Document type code
- `issuer_code`: Issuing country code
- `surname`: Last name
- `given_name`: First name(s)
- `document_number`: Document number
- `nationality_code`: Nationality code
- `birth_date`: Date of birth (YYYY-MM-DD)
- `sex`: Gender (M/F)
- `expiry_date`: Expiry date (YYYY-MM-DD)
- `optional_data`: Optional data field
- `mrz_text`: Raw MRZ text
- `*_checkdigit`: Checkdigit fields (if `include_checkdigit=true`)

## Error Handling

The API returns appropriate HTTP status codes:
- `200`: Success
- `400`: Bad request (invalid file, missing data, etc.)
- `500`: Server error

All error responses include:
```json
{
  "status": "ERROR",
  "status_message": "Error description",
  "error": true
}
```

## File Size Limits

- Maximum file size: 10MB
- Supported formats: JPEG, PNG, GIF, BMP, WebP

## CORS

CORS is enabled by default. To restrict origins, modify the CORS configuration in `server.js`.

## Project Structure

```
.
├── server.js              # Express server and routes
├── python_bridge.py        # Python script bridge
├── package.json           # Node.js dependencies
├── .env                   # Environment variables
├── uploads/               # Temporary upload directory (auto-created)
└── fastmrz/               # FastMRZ Python library
```

## Troubleshooting

1. **Python script not found**: Ensure Python is in your PATH
2. **Tesseract errors**: Check that Tesseract is installed and `TESSERACT_PATH` is set correctly
3. **FastMRZ import errors**: Ensure FastMRZ is properly installed in the `fastmrz` directory
4. **File upload errors**: Check file size and format restrictions

## License

Same as the FastMRZ project.

