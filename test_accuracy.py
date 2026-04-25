import os
import json
import time
import glob
from improved_mrz_extractor import MRZExtractor

# Install Levenshtein if not present
try:
    from Levenshtein import ratio
except ImportError:
    print("Levenshtein library not found. Please install it using: pip install python-Levenshtein")
    exit()


# Configuration
TEST_IMAGES_DIR = "./test_images"  # Directory containing passport images
GROUND_TRUTH_FILE = "./ground_truth.json" # JSON file with { "filename": { "document_number": "...", ... } }
MODEL_PATH = os.path.join(os.path.dirname(__file__), "fastmrz", "fastmrz", "model", "mrz_seg.onnx")

# Configuration
#TEST_IMAGES_DIR = "./test_images_midv"  
#GROUND_TRUTH_FILE = "./ground_truth_midv.json" 
#MODEL_PATH = os.path.join(os.path.dirname(__file__), "fastmrz", "fastmrz", "model", "mrz_seg.onnx")

def correct_ocr_errors(data):
    """
    Corrects common OCR errors in MRZ data based on field context.
    """
    if not data or not isinstance(data, dict):
        return data

    corrections = {
        'document_number': {'O': '0', 'I': '1', 'B': '8', 'S': '5', 'Q': '0'},
        'birth_date': {'O': '0', 'I': '1', 'S': '5'},
        'expiry_date': {'O': '0', 'I': '1', 'S': '5'},
        'surname': {'0': 'O', '1': 'I', '5': 'S', '8': 'B'},
        'given_names': {'0': 'O', '1': 'I', '5': 'S', '8': 'B'},
    }
    
    corrected_data = data.copy()
    for field, mapping in corrections.items():
        if field in corrected_data and isinstance(corrected_data[field], str):
            original_value = corrected_data[field]
            corrected_value = original_value
            for wrong, right in mapping.items():
                corrected_value = corrected_value.replace(wrong, right)
            corrected_data[field] = corrected_value
            
    return corrected_data

def calculate_accuracy(pred, truth, similarity_threshold=0.85):
    """
    Compare prediction algorithm against truth using Levenshtein distance.
    Returns score (0-1) and list of mismatches.
    """
    matches = 0
    total_fields = 0
    mismatches = []

    # Correct both prediction and ground truth before comparison
    corrected_pred = correct_ocr_errors(pred)
    corrected_truth = correct_ocr_errors(truth)
    
    fields_to_check = ['document_number', 'surname', 'given_names', 'birth_date', 'expiry_date', 'sex', 'nationality']
    
    for field in fields_to_check:
        if field in corrected_truth:
            total_fields += 1
            p_val = corrected_pred.get(field, "").replace("<", "").strip().upper()
            t_val = corrected_truth.get(field, "").replace("<", "").strip().upper()
            
            # Use Levenshtein ratio for similarity check
            if ratio(p_val, t_val) >= similarity_threshold:
                matches += 1
            else:
                mismatches.append(f"{field}: expected '{t_val}', got '{p_val}'")
                
    return (matches / total_fields if total_fields > 0 else 0), mismatches

def main():
    print("Initializing Extractor...")
    try:
        extractor = MRZExtractor(MODEL_PATH)
    except FileNotFoundError:
        print(f"Error: Model not found at {MODEL_PATH}")
        return

    # Check validity
    if not os.path.isdir(TEST_IMAGES_DIR):
        print(f"Test images directory '{TEST_IMAGES_DIR}' not found. Please create it and add images.")
        return
        
    ground_truth = {}
    if os.path.exists(GROUND_TRUTH_FILE):
        with open(GROUND_TRUTH_FILE, 'r') as f:
            raw_data = json.load(f)
            # If it's a list (like accuracy_log_correct.json), convert it to a dictionary
            if isinstance(raw_data, list):
                for item in raw_data:
                    if 'filename' in item and 'data' in item:
                        ground_truth[item['filename']] = item['data']
            else:
                ground_truth = raw_data
    else:
        print("Warning: No ground truth file found. Running in processing-only mode.")

    image_files = glob.glob(os.path.join(TEST_IMAGES_DIR, "*.*"))
    print(f"Found {len(image_files)} images.")
    
    total_time = 0
    total_accuracy = 0
    processed_count = 0
    
    for img_path in image_files:
        if img_path.lower().endswith(('.png', '.jpg', '.jpeg', '.tif')):
            fname = os.path.basename(img_path)
            print(f"\nProcessing {fname}...")
            
            start_time = time.time()
            result = extractor.process(img_path)
            duration = time.time() - start_time
            total_time += duration
            
            if result.get('success'):
                conf = result.get('overall_confidence', 0)
                print(f"  Success! Time: {duration:.2f}s, Confidence: {conf}")
                
                if fname in ground_truth:
                    acc, mismatches = calculate_accuracy(result, ground_truth[fname])
                    total_accuracy += acc
                    processed_count += 1
                    print(f"  Accuracy: {acc*100:.1f}%")
                    if mismatches:
                        print(f"  Mismatches: {', '.join(mismatches)}")
                else:
                    print(f"  Result: {result.get('document_number', 'N/A')} ({result.get('surname', '')})")
            else:
                print(f"  Failed: {result.get('error')}")
                
    if processed_count > 0:
        avg_acc = total_accuracy / processed_count
        avg_time = total_time / len(image_files)
        print(f"\nOverall Results:")
        print(f"  Average Accuracy: {avg_acc*100:.2f}%")
        print(f"  Average Time: {avg_time:.2f}s")
    else:
        print("\nDone. (No ground truth comparisons made)")

if __name__ == "__main__":
    main()
