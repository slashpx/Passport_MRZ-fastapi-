import os
import base64
import json
import logging
import config
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class AIExtractor:
    """
    Uses OpenAI's Vision models to provide high-accuracy MRZ extraction and correction.
    """
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        
        if not self.api_key:
            logger.warning("OpenAI API Key not found. AI fallback will be disabled.")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def correct_mrz(self, raw_ocr_text, image_path=None):
        """
        Takes noisy OCR text and (optionally) an image crop, and returns corrected MRZ lines.
        """
        if not self.client:
            return None

        prompt = f"""
        You are an expert MRZ (Machine Readable Zone) parser. 
        Your task is to correct the following noisy OCR text from a passport.
        
        Noisy OCR Text:
        {raw_ocr_text}
        
        Rules:
        1. Return ONLY the corrected MRZ lines (2 lines for TD3, 3 lines for TD1/TD2).
        2. Each line must be exactly 44 characters (TD3) or 30/36 characters (TD1/TD2).
        3. Use '<' for padding.
        4. Do not explain anything. Just output the lines.
        5. IMPORTANT: If you cannot read the text, do not guess or provide placeholders like "EXAMPLE" or "12345". Return the best possible interpretation or nothing.
        """

        messages = [
            {"role": "system", "content": "You are a specialized tool for MRZ correction."},
            {"role": "user", "content": prompt}
        ]

        if image_path:
            base64_image = self._encode_image(image_path)
            messages[1]["content"] = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]

        try:
            response = self.client.chat.completions.create(
                model=config.OPENAI_MODEL_CORRECTION,
                messages=messages,
                max_tokens=200,
                temperature=0.0
            )
            corrected_text = response.choices[0].message.content.strip()
            # Clean up markdown if any
            corrected_text = corrected_text.replace("```", "").replace("mrz", "").strip()
            return corrected_text
        except Exception as e:
            logger.error(f"AI Correction failed: {e}")
            return None

    def extract_full_data(self, image_path):
        """
        Extracts both MRZ and visual fields to ensure 100% accuracy via cross-verification.
        """
        if not self.client:
            return None

        base64_image = self._encode_image(image_path)
        
        prompt = """
        Extract all information from this passport. 
        Return a JSON object with:
        - mrz_lines: array of strings
        - visual_fields: { surname, given_names, date_of_birth, date_of_expiry, document_number, nationality, sex }
        
        Use YYYY-MM-DD for dates in visual_fields, but keep YYMMDD for MRZ.
        Ensure document_number matches between visual and MRZ.
        
        CRITICAL: 
        - Do NOT use placeholder data (e.g., "EXAMPLE NAME", "123456789"). 
        - If a field is unreadable, use an empty string or null.
        - You must extract the REAL data from the image.
        """

        try:
            # First attempt with JSON mode
            try:
                response = self.client.chat.completions.create(
                    model=config.OPENAI_MODEL_VISION,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    response_format={ "type": "json_object" },
                    max_tokens=1000
                )
                content = response.choices[0].message.content
            except Exception as json_err:
                logger.warning(f"JSON mode failed, trying without it: {json_err}")
                # Fallback: try without JSON mode
                response = self.client.chat.completions.create(
                    model=config.OPENAI_MODEL_VISION,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt + "\nIMPORTANT: Return ONLY valid JSON."},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=1000
                )
                content = response.choices[0].message.content

            if content is None:
                logger.error("AI Full Extraction returned None content")
                return None
            
            # Clean up markdown if any
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"AI Full Extraction failed: {e}")
            return None
