import cv2
import numpy as np
import pytesseract
import os
import sys
import json
import re
from datetime import datetime
from pdf2image import convert_from_path
from PIL import Image
import config
from ai_engine import AIExtractor

class ImagePreprocessor:
    """
    Handles advanced image preprocessing for MRZ extraction.
    Implements multi-scale, shadow removal, and adaptive thresholding.
    """
    
    @staticmethod
    def load_image(image_source):
        """Load image from path or return if already numpy array."""
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"Image not found: {image_source}")
            
            # Handle PDF
            if image_source.lower().endswith('.pdf'):
                try:
                    # Convert first page of PDF to image
                    pages = convert_from_path(image_source)
                    if not pages:
                        raise ValueError("PDF is empty")
                    
                    # Convert PIL Image to OpenCV Buffer (RGB -> BGR)
                    pil_image = pages[0]
                    opencv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                    return opencv_image
                except Exception as e:
                    raise ValueError(f"Failed to convert PDF: {e}")

            # Standard Image
            return cv2.imread(image_source)
        elif isinstance(image_source, np.ndarray):
            return image_source.copy()
        else:
            raise ValueError("Unsupported image source type")

    @staticmethod
    def preprocess_for_roi(image):
        """Basic preprocessing for ROI detection (resize, normalize)."""
        # Resize to standard size for neural net
        blob = cv2.resize(image, config.ROI_INPUT_SIZE, interpolation=cv2.INTER_NEAREST)
        blob = np.asarray(np.float32(blob / 255.0))
        if len(blob.shape) >= 3:
            blob = blob[:, :, :3] # Ensure 3 channels
        blob = np.reshape(blob, (1, config.ROI_INPUT_SIZE[0], config.ROI_INPUT_SIZE[1], 3))
        return blob

    @staticmethod
    def upscale_image_if_needed(image):
        """Upscale image if width is below threshold."""
        h, w = image.shape[:2]
        if w < config.MIN_IMAGE_WIDTH:
            scale = config.MIN_IMAGE_WIDTH / w
            return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return image

    @staticmethod
    def remove_shadows(gray_image):
        """Remove shadows using morphological operations."""
        dilated = cv2.dilate(gray_image, np.ones((7, 7), np.uint8))
        bg_img = cv2.medianBlur(dilated, 21)
        diff_img = 255 - cv2.absdiff(gray_image, bg_img)
        
        # FIX: Explicitly create the destination array to satisfy type checkers.
        norm_img = np.zeros_like(diff_img)
        cv2.normalize(diff_img, norm_img, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1)
        return norm_img

    @staticmethod
    def get_preprocessing_variants(image):
        """
        Generate multiple preprocessed variants for voting mechanism.
        Returns a dictionary of {variant_name: processed_image}
        """
        variants = {}
        
        # Ensure grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Variant 1: Standard OTSU
        variants['otsu'] = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # Variant 2: Gaussian Blur + OTSU (Denoise)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        variants['blur_otsu'] = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # Variant 3: Adaptive Thresholding (Gaussian) - DISABLED (Too slow/risky)
        # variants['adaptive_gauss'] = cv2.adaptiveThreshold(
        #     gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        #     cv2.THRESH_BINARY, config.BW_THRESHOLD_BLOCK_SIZE, config.BW_THRESHOLD_C
        # )
        
        # Variant 4: Shadow Removal + OTSU
        no_shadow = ImagePreprocessor.remove_shadows(gray)
        variants['shadow_otsu'] = cv2.threshold(no_shadow, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # Invert checking (if background is dark)
        # MRZ is usually black text on white background (or light).
        # Checking middle of image for dominance
        # Simple heuristic: if majority of pixels are black, invert.
        for key in list(variants.keys()):
            img = variants[key]
            white_pixels = np.sum(img == 255)
            total_pixels = img.size
            if white_pixels < total_pixels * 0.4: # Assuming text is minority
                variants[f'{key}_inverted'] = cv2.bitwise_not(img)
                
        return variants

class ROIExtractor:
    """
    Robust Region of Interest extraction.
    Uses ONNX Model -> Morphological Fallback -> Positional Fallback.
    """
    def __init__(self, model_path):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found at {model_path}")
        self.net = cv2.dnn.readNetFromONNX(model_path)

    def extract_roi(self, image):
        """
        Attempts to extract MRZ region. 
        Returns (roi_image, method_used)
        """
        # 1. Try Neural Network
        try:
            roi_cnn = self._extract_via_cnn(image)
            if self._validate_roi(roi_cnn):
                return roi_cnn, "CNN"
        except Exception as e:
            print(f"CNN Extraction Failed: {e}")

        # 2. Try Morphological
        try:
            roi_morph = self._extract_via_morphology(image)
            if self._validate_roi(roi_morph):
                return roi_morph, "MORPH"
        except Exception as e:
            print(f"Morphological Extraction Failed: {e}")

        # 3. Fallback: Bottom Crop
        roi_fallback = self._extract_fallback(image)
        return roi_fallback, "FALLBACK"

    def _extract_via_cnn(self, image):
        input_blob = ImagePreprocessor.preprocess_for_roi(image)
        self.net.setInput(input_blob)
        output = self.net.forward()
        
        # Process mask
        mask = output[0, :, :, 0]
        mask = cv2.resize(mask, (image.shape[1], image.shape[0]))
        mask = (mask > config.ROI_MIN_CONFIDENCE).astype(np.uint8) * 255
        
        # Find contours on mask
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
            
        # Get largest contour
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        
        # Padding
        x = max(0, x - config.ROI_PADDING)
        y = max(0, y - config.ROI_PADDING)
        w = min(image.shape[1] - x, w + 2 * config.ROI_PADDING)
        h = min(image.shape[0] - y, h + 2 * config.ROI_PADDING)
        
        return image[y:y+h, x:x+w]

    def _extract_via_morphology(self, image):
        # Grayscale -> Gradient -> Threshold -> Morph Close
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=-1)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=-1)
        gradient = cv2.subtract(grad_x, grad_y)
        gradient = cv2.convertScaleAbs(gradient)
        
        blurred = cv2.blur(gradient, (9, 9))
        _, thresh = cv2.threshold(blurred, 225, 255, cv2.THRESH_BINARY)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 7))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
            
        # Filter by aspect ratio
        valid_rois = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            ar = w / float(h)
            if config.ROI_MIN_ASPECT_RATIO < ar < config.ROI_MAX_ASPECT_RATIO:
                valid_rois.append((x,y,w,h))
        
        if not valid_rois:
            return None
            
        # take the bottom-most valid ROI (MRZ is usually at bottom)
        valid_rois.sort(key=lambda b: b[1], reverse=True)
        x, y, w, h = valid_rois[0]
        
        # Padding
        padding = 10
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(image.shape[1] - x, w + 2 * padding)
        h = min(image.shape[0] - y, h + 2 * padding)
        
        return image[y:y+h, x:x+w]

    def _extract_fallback(self, image):
        h, w = image.shape[:2]
        return image[int(h*0.60):h, 0:w] # Bottom 40%

    def _validate_roi(self, roi_image):
        if roi_image is None or roi_image.size == 0:
            return False
        h, w = roi_image.shape[:2]
        if w == 0 or h == 0: return False
        ar = w / h
        # Relaxed constraints for validation
        return 3.0 < ar < 30.0

class ChecksumValidator:
    """
    Validates and computes MRZ checksums.
    Weights: 7, 3, 1 repeating.
    """
    WEIGHTS = [7, 3, 1]

    @staticmethod
    def get_char_value(char):
        if char.isdigit():
            return int(char)
        if char.isalpha():
            return ord(char.upper()) - 55 # A=10, Z=35
        if char == '<':
            return 0
        return 0

    @classmethod
    def compute(cls, text):
        total = 0
        for i, char in enumerate(text):
            val = cls.get_char_value(char)
            weight = cls.WEIGHTS[i % 3]
            total += val * weight
        return str(total % 10)

    @classmethod
    def validate(cls, text, expected_digit):
        if not expected_digit.isdigit(): return False
        return cls.compute(text) == expected_digit

    @classmethod
    def brute_force_correct(cls, text, expected_digit, is_date=False):
        """
        Try substituting one character at a time to match checksum.
        """
        if cls.validate(text, expected_digit):
            return text, True, False # text, valid, corrected
            
        candidates = config.WHITELIST_NUMERIC if is_date else config.WHITELIST_ALPHANUM
        
        # Priority: Check highly confused characters first
        text_list = list(text)
        
        # 1. Try common confusions correction
        for i, char in enumerate(text_list):
            if char in config.OCR_CONFUSIONS:
                for replacement in config.OCR_CONFUSIONS[char]:
                    original = text_list[i]
                    text_list[i] = replacement
                    candidate_text = "".join(text_list)
                    if cls.validate(candidate_text, expected_digit):
                        return candidate_text, True, True
                    text_list[i] = original # Backtrack

        # 2. Full brute force (single char) if confusions fail
        # This is expensive, so only do it for short strings
        if len(text) <= 15:
            for i in range(len(text_list)):
                original = text_list[i]
                for c in candidates:
                    if c == original: continue
                    text_list[i] = c
                    candidate_text = "".join(text_list)
                    if cls.validate(candidate_text, expected_digit):
                         return candidate_text, True, True
                text_list[i] = original
                
        return text, False, False

class CharacterCorrector:
    """
    Post-OCR cleanup and specific field corrections.
    """
    
    @staticmethod
    def clean_text(text, whitelist):
        return "".join([c for c in text if c in whitelist])

    @staticmethod
    def correct_line_structure(line, expected_len=44):
        # Basic padding/trimming
        text = line.replace(" ", "").upper()
        if len(text) > expected_len:
            text = text[:expected_len]
        elif len(text) < expected_len:
            text = text.ljust(expected_len, '<')
        return text

    @staticmethod
    def correct_date(date_str):
        # Dates are numeric. Replace common alpha errors
        res = []
        for c in date_str:
            if c.isdigit():
                res.append(c)
            elif c == 'O' or c == 'D' or c == 'Q':
                res.append('0')
            elif c == 'I' or c == 'L':
                res.append('1')
            elif c == 'S':
                res.append('5')
            elif c == 'B':
                res.append('8')
            elif c == 'Z':
                res.append('2')
            else:
                res.append(c) # Keep as is, let validation fail
        return "".join(res)

class OCREngine:
    """
    Multi-pass OCR engine with voting.
    """
    def __init__(self, tesseract_cmd=None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        elif config.TESSERACT_CMD:
             pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
        if config.TESSDATA_PREFIX:
            os.environ['TESSDATA_PREFIX'] = config.TESSDATA_PREFIX

    def run_ocr(self, image, allow_alpha=True):
        """Run Tesseract with configured modes."""
        whitelist = config.WHITELIST_ALPHANUM if allow_alpha else config.WHITELIST_NUMERIC
        results = []
        
        # Try configured modes
        for psm in config.PSM_MODES:
            for oem in config.OEM_MODES:
                cfg = f'--oem {oem} --psm {psm} -c tessedit_char_whitelist={whitelist}'
                try:
                    text = pytesseract.image_to_string(image, lang='mrz', config=cfg) # Try mrz lang first
                    if not text.strip():
                         # Fallback to eng if mrz fails
                        text = pytesseract.image_to_string(image, lang='eng', config=cfg)
                    results.append(text.strip())
                except Exception as e:
                    print(f"    [OCR ERROR]: {e}", file=sys.stderr)
                    continue
        
        # Simple majority or longest valid-looking result
        # For MRZ, we expect lines ~44 chars (TD3) or 30/36
        if not results: return ""
        
        # Heuristic: pick result closest to 44/88 chars and has '<<'
        return max(results, key=lambda x: (x.count('<'), len(x)))

class ConfidenceScorer:
    """
    Calculates 0-100 confidence score for the extraction check.
    """
    @staticmethod
    def calculate(parsed_result):
        score = 0
        total_checks = 0
        
        # Checksuit checks
        checks = [
            parsed_result.get('number_check_valid'),
            parsed_result.get('birth_check_valid'),
            parsed_result.get('expiry_check_valid'),
            parsed_result.get('final_check_valid')
        ]
        
        valid_checks = sum(1 for c in checks if c is True)
        total_checks = sum(1 for c in checks if c is not None)
        
        if total_checks > 0:
            score += (valid_checks / total_checks) * config.SCORE_WEIGHT_CHECKSUM
            
        # Penalize if any field was brute-forced (reduces confidence to trigger AI)
        if parsed_result.get('any_corrected'):
            score -= 15 # Significant penalty to drop below 95
        
        # Completeness Check
        fields = ['surname', 'given_names', 'document_number', 'nationality', 'birth_date', 'expiry_date', 'sex']
        present_fields = sum(1 for f in fields if parsed_result.get(f))
        score += (present_fields / len(fields)) * config.SCORE_WEIGHT_COMPLETENESS
        
        # Basic Logic Check (Expiry > Birth)
        logic_score = 0
        try:
            bd = parsed_result.get('birth_date')
            ed = parsed_result.get('expiry_date')
            if bd and ed:
                 # Very rough check as centuries might be ambiguous
                 # Just checking format validity adds points
                 logic_score = config.SCORE_WEIGHT_LOGIC 
        except:
            pass
        score += logic_score
            
        return min(100, int(score))

class MRZExtractor:
    """
    Main Orchestrator class.
    """
    def __init__(self, model_path=None):
        # If no model_path is provided, use the default one relative to this file.
        if model_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            # This assumes the model is in a predictable location relative to the extractor script
            model_path = os.path.join(base_dir, 'fastmrz', 'model', 'mrz_seg.onnx')

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found at the specified path: {model_path}")

        self.model_path = model_path
        self.preprocessor = ImagePreprocessor()
        self.roi_extractor = ROIExtractor(model_path)
        self.ocr_engine = OCREngine()
        self.corrector = CharacterCorrector()
        self.ai_extractor = AIExtractor()
        
    def process(self, image_path):
        """
        Full pipeline processing with rotation support.
        """
        # 1. Load and Upscale
        print(f"Loading {image_path}...", file=sys.stderr)
        original_image = self.preprocessor.load_image(image_path)
        original_image = self.preprocessor.upscale_image_if_needed(original_image)
        
        # Try 0 degrees
        print("Trying 0 degrees...", file=sys.stderr)
        result = self._process_single_image(original_image)
        if result.get('success') and result.get('overall_confidence', 0) > 60:
            return result
            
        # Try rotations if failed or low confidence
        rotations = [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE]
        rotation_names = ["90", "180", "270"]
        
        for rot_code, rot_name in zip(rotations, rotation_names):
            print(f"Trying rotation {rot_name}...", file=sys.stderr)
            rotated = cv2.rotate(original_image, rot_code)
            
            # Recursing/Calling internal process
            res = self._process_single_image(rotated)
            if res.get('success') and res.get('overall_confidence', 0) > 60:
                res['rotation'] = rot_name
                return res
                
        # If all failed, return the first result (0 degrees) or the best one
        # For simplicity return the failed 0 degree one
        return result

    def _process_single_image(self, image):
        """Internal processing of a single image array"""
        
        # 2. Extract ROI
        print("  Extracting ROI...", file=sys.stderr)
        roi, roi_method = self.roi_extractor.extract_roi(image)
        if roi is None:
            return {'success': False, 'status': 'ERROR', 'error': 'ROI Extraction Failed'}
        cv2.imwrite("debug_roi_crop.jpg", roi)
            
        # 3. Preprocessing Variants & Voting
        print("  Preprocessing variants...", file=sys.stderr)
        variants = self.preprocessor.get_preprocessing_variants(roi)
        
        best_candidate = None
        best_score = -1
        best_parsed = {}
        
        for v_name, v_img in variants.items():
            # 4. OCR
            print(f"    Running OCR on {v_name}...", file=sys.stderr)
            raw_text = self.ocr_engine.run_ocr(v_img)
            
            # 5. Parse & Validate
            parsed = self.parse_mrz(raw_text)
            
            # 6. Score
            confidence = ConfidenceScorer.calculate(parsed)
            
            if confidence > best_score:
                best_score = confidence
                best_parsed = parsed
                best_parsed['raw_text'] = raw_text # Store for AI correction if needed
                best_candidate = v_name
                
            # Early exit if perfect score
            if confidence >= 95:
                break
                
        # 7. AI Fallback (New Strategy for "Almost 0" Error)
        if config.AI_FALLBACK_ENABLED and best_score < config.AI_CONFIDENCE_THRESHOLD:
            print(f"  Confidence {best_score} < {config.AI_CONFIDENCE_THRESHOLD}. Triggering AI Fallback...", file=sys.stderr)
            
            # Save the ROI for AI to look at (if available)
            roi_path = "debug_roi_crop.jpg" # Already saved at line 493
            
            # Option A: Correct the best Tesseract result
            raw_text = best_parsed.get('raw_text', "")
            corrected_text = self.ai_extractor.correct_mrz(raw_text, image_path=roi_path)
            
            if corrected_text:
                print("  AI Correction successful.", file=sys.stderr)
                ai_parsed = self.parse_mrz(corrected_text)
                ai_score = ConfidenceScorer.calculate(ai_parsed)
                
                if ai_score > best_score:
                    best_score = ai_score
                    best_parsed = ai_parsed
                    best_candidate = "OpenAI-Correction"
            
            # Option B: If still low, try full AI extraction
            if best_score < config.AI_CONFIDENCE_THRESHOLD:
                 print("  Confidence still low. Trying full AI extraction...", file=sys.stderr)
                 full_ai = self.ai_extractor.extract_full_data(roi_path)
                 if full_ai and 'mrz_lines' in full_ai:
                     ai_text = "\n".join(full_ai['mrz_lines'])
                     ai_parsed = self.parse_mrz(ai_text)
                     # Merge visual fields if available for extra confidence
                     if 'visual_fields' in full_ai:
                         ai_parsed['visual_fields'] = full_ai['visual_fields']
                     
                     ai_score = ConfidenceScorer.calculate(ai_parsed)
                     if ai_score > best_score:
                         best_score = ai_score
                         best_parsed = ai_parsed
                         best_candidate = "OpenAI-Vision"

        if not best_parsed:
             return {'success': False, 'status': 'ERROR', 'error': 'Parsing Failed', 'raw_text': raw_text}
             
        best_parsed['overall_confidence'] = best_score
        best_parsed['roi_method'] = roi_method
        best_parsed['preprocessing_method'] = best_candidate
        
        # Check if the result is actually valid
        if best_parsed.get('valid') is False:
             best_parsed['success'] = False
             best_parsed['status'] = 'ERROR'
        else:
             best_parsed['success'] = True
             best_parsed['status'] = 'SUCCESS'
        
        return best_parsed

    def parse_mrz(self, text):
        """
        Parses raw text into fields, assumes TD3 for now (most common).
        Can be extended for TD1/TD2 based on line lengths.
        """
        clean_lines = [l.strip().replace(' ', '') for l in text.split('\n') if len(l.strip()) > 30]
        
        # Filter lines containing '<'
        clean_lines = [l for l in clean_lines if '<' in l]
        
        if len(clean_lines) < 2:
            return {'valid': False, 'status': 'ERROR', 'error': 'Not enough MRZ lines found'}
            
        # Find lines starting with P, I, A, V, C
        # Very simple heuristic: Take last 2 lines generally
        # Or find line starting with P<
        
        line1 = ""
        line2 = ""
        
        for i in range(len(clean_lines)-1):
            l1 = clean_lines[i]
            l2 = clean_lines[i+1]
            if len(l1) > 35 and len(l2) > 35: # Likely TD3
                 # Check for indicator
                 if l1[0] in 'PIACV' and '<' in l1[:5]:
                     line1 = l1
                     line2 = l2
                     break
        
        if not line1:
            # Fallback: take longest 2 lines
            clean_lines.sort(key=len, reverse=True)
            if len(clean_lines) >= 2:
                line1 = clean_lines[0] # Note: this logic is brittle, relying on sort might mix order
                # Ideally we need order preservation.
                # Let's revert to taking first 2 valid looking ones
                line1 = clean_lines[0] # Placeholder logic
                line2 = clean_lines[1] 

        # Normalize to 44 chars (TD3)
        line1 = self.corrector.correct_line_structure(line1, 44)
        line2 = self.corrector.correct_line_structure(line2, 44)
        
        # Parsing Logic (TD3)
        # Line 1:
        # 0-1: Type (P<)
        # 2-5: Issuer (GBR)
        # 5-44: Name (SURNAME<<GIVEN<NAMES)
        
        doc_type = line1[0:2].replace('<', '')
        issuer = line1[2:5].replace('<', '')
        raw_names = line1[5:].strip('<')
        if '<<' in raw_names:
            surname, given = raw_names.split('<<', 1)
        else:
            surname = raw_names
            given = ''
            
        surname = surname.replace('<', ' ').strip()
        given = given.replace('<', ' ').strip()
        
        # Line 2:
        # 0-9: Doc Number
        # 9: Check digit
        # 10-13: Nationality
        # 13-19: Birth Date
        # 19: Check
        # 20: Sex
        # 21-27: Expiry Date
        # 27: Check
        # 28-42: Personal Number
        # 42: Check
        # 43: Final Check
        
        doc_no_raw = line2[0:9]
        doc_no_check_curr = line2[9]
        nationality = line2[10:13].replace('<', '')
        birth_raw = line2[13:19]
        birth_check_curr = line2[19]
        sex = line2[20]
        expiry_raw = line2[21:27]
        expiry_check_curr = line2[27]
        final_check_curr = line2[43] if len(line2) > 43 else '0'

        # CORRECTIONS
        # 1. Dates (fix letters to numbers)
        birth_raw = self.corrector.correct_date(birth_raw)
        expiry_raw = self.corrector.correct_date(expiry_raw)
        
        # 2. Checksum Corrections
        doc_no_final, d_valid, d_corr = ChecksumValidator.brute_force_correct(doc_no_raw, doc_no_check_curr)
        birth_final, b_valid, b_corr = ChecksumValidator.brute_force_correct(birth_raw, birth_check_curr, is_date=True)
        expiry_final, e_valid, e_corr = ChecksumValidator.brute_force_correct(expiry_raw, expiry_check_curr, is_date=True)
        
        # Check overall checksum if others valid (simplified for now)
        # Construct composite for final check (TD3: line2 0-10 + 13-20 + 21-43)
        # We'll skip complex composite brute force for now, just validate
        
        return {
            'type': doc_type,
            'issuer': issuer,
            'surname': surname,
            'given_names': given,
            'document_number': doc_no_final,
            'nationality': nationality,
            'birth_date': birth_final,
            'sex': sex,
            'expiry_date': expiry_final,
            'number_check_valid': d_valid,
            'birth_check_valid': b_valid,
            'expiry_check_valid': e_valid,
            'any_corrected': d_corr or b_corr or e_corr
            # 'final_check_valid': ... # Not computed yet
        }

if __name__ == "__main__":
    # Test block
    model_path = os.path.join(os.path.dirname(__file__), "fastmrz/fastmrz/model/mrz_seg.onnx")
    extractor = MRZExtractor(model_path)
    # Check if a file is provided
    if len(sys.argv) > 1:
        res = extractor.process(sys.argv[1])
        print(json.dumps(res, indent=2))
