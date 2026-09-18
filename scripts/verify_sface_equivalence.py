import cv2
import numpy as np
import onnxruntime as ort
import os

def run_equivalence_test():
    model_path = "face_recognition_sface_2021dec.onnx"
    if not os.path.exists(model_path):
        print("FAILED: Model not found")
        return
        
    # Generate random face image
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    
    # Generate random 5-point landmarks
    landmarks = np.array([
        [100, 100], [200, 100], [150, 150], [120, 200], [180, 200]
    ], dtype=np.float32)
    
    # REFERENCE: OpenCV FaceRecognizerSF
    # cv2.FaceRecognizerSF takes bounding box and landmarks for alignment, wait alignCrop uses face_box?
    # Actually, alignCrop needs face_box which is [x, y, w, h, right_eye_x, right_eye_y, ...]
    # For YuNet, face detection result has 15 elements:
    # x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score
    face_box = np.array([
        50, 50, 200, 200,
        100, 100, 200, 100, 150, 150, 120, 200, 180, 200, 0.99
    ], dtype=np.float32)
    
    try:
        recognizer = cv2.FaceRecognizerSF.create(model_path, "")
        aligned_ref = recognizer.alignCrop(image, face_box)
        feature_ref = recognizer.feature(aligned_ref)
    except Exception as e:
        print(f"FAILED (Reference): {e}")
        return
        
    # DIRECT: ONNX Runtime
    session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    
    # We will use the aligned_ref for direct inference to isolate preprocessing/inference equivalence
    # from alignment equivalence for a moment.
    
    # SFace OpenCV pre-processing: blobFromImage with scale=1.0, size=(112, 112), mean=(0,0,0), swapRB=False, crop=False
    # This means input is just the BGR image in float32, HWC -> NCHW.
    input_blob = cv2.dnn.blobFromImage(aligned_ref, 1.0, (112, 112), (0, 0, 0), swapRB=False, crop=False)
    
    feature_dir = session.run(["fc1"], {"data": input_blob})[0]
    
    # The reference is already L2 normalized by OpenCV!
    # Let's check:
    ref_norm = np.linalg.norm(feature_ref)
    dir_norm = np.linalg.norm(feature_dir)
    
    feature_dir_normalized = feature_dir / dir_norm
    
    cos_sim = np.dot(feature_ref.flatten(), feature_dir_normalized.flatten())
    
    diff = np.max(np.abs(feature_ref.flatten() - feature_dir_normalized.flatten()))
    
    print(f"Ref Norm: {ref_norm:.6f}")
    print(f"Dir Norm (raw): {dir_norm:.6f}")
    print(f"Max Diff (normalized): {diff:.6e}")
    print(f"Cosine Similarity: {cos_sim:.6f}")
    
    if diff < 1e-4:
        print("RESULT: EQUIVALENT")
    else:
        print("RESULT: MATERIAL DIFFERENCE")

if __name__ == "__main__":
    run_equivalence_test()
