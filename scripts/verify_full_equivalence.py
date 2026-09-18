import cv2
import numpy as np
import onnxruntime as ort

from edge.detection.face_align import FaceAligner

def test_full_equivalence():
    model_path = "face_recognition_sface_2021dec.onnx"
    
    # Generate random face image
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    
    # 5-point landmarks
    landmarks = np.array([
        [100, 100], [200, 100], [150, 150], [120, 200], [180, 200]
    ], dtype=np.float32)
    
    face_box = np.array([
        50, 50, 200, 200,
        100, 100, 200, 100, 150, 150, 120, 200, 180, 200, 0.99
    ], dtype=np.float32)
    
    # REFERENCE: OpenCV FaceRecognizerSF
    recognizer = cv2.FaceRecognizerSF.create(model_path, "")
    aligned_ref = recognizer.alignCrop(image, face_box)
    feature_ref = recognizer.feature(aligned_ref)
    
    feature_ref_normalized = feature_ref / np.linalg.norm(feature_ref)
    
    # DIRECT: FaceAligner + ONNXRuntime
    aligner = FaceAligner(output_size=(112, 112))
    aligned_dir = aligner.align(image, None, landmarks)["aligned_face"]
    
    session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    input_blob = cv2.dnn.blobFromImage(aligned_dir, 1.0, (112, 112), (0, 0, 0), swapRB=True, crop=False)
    feature_dir = session.run(["fc1"], {"data": input_blob})[0]
    
    feature_dir_normalized = feature_dir / np.linalg.norm(feature_dir)
    
    cos_sim = np.dot(feature_ref_normalized.flatten(), feature_dir_normalized.flatten())
    diff = np.max(np.abs(feature_ref_normalized.flatten() - feature_dir_normalized.flatten()))
    
    print(f"Cosine Similarity between Reference vs Direct pipeline: {cos_sim:.6f}")
    print(f"Max Diff (normalized): {diff:.6e}")
    
    if cos_sim > 0.99:
        print("RESULT: ACCEPTABLE NUMERIC DIFFERENCE")
    else:
        print("RESULT: MATERIAL DIFFERENCE")

if __name__ == "__main__":
    test_full_equivalence()
