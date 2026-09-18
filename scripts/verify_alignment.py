import cv2
import numpy as np
import os

from edge.detection.face_align import FaceAligner

def test_alignment():
    # Generate random face image
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    
    # 5-point landmarks
    landmarks = np.array([
        [100, 100], [200, 100], [150, 150], [120, 200], [180, 200]
    ], dtype=np.float32)
    
    # cv2.FaceRecognizerSF needs a face_box format
    # x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score
    face_box = np.array([
        50, 50, 200, 200,
        100, 100, 200, 100, 150, 150, 120, 200, 180, 200, 0.99
    ], dtype=np.float32)
    
    model_path = "face_recognition_sface_2021dec.onnx"
    recognizer = cv2.FaceRecognizerSF.create(model_path, "")
    
    # Reference crop
    aligned_ref = recognizer.alignCrop(image, face_box)
    
    # Direct crop
    aligner = FaceAligner(output_size=(112, 112))
    res = aligner.align(image, None, landmarks)
    aligned_dir = res["aligned_face"]
    
    diff = np.max(np.abs(aligned_ref.astype(np.float32) - aligned_dir.astype(np.float32)))
    print(f"Alignment Diff: {diff}")
    
    if diff == 0:
        print("ALIGNMENT: EXACT")
    elif diff < 5:
        print("ALIGNMENT: ACCEPTABLE NUMERIC DIFFERENCE")
    else:
        print("ALIGNMENT: MATERIAL DIFFERENCE")

if __name__ == "__main__":
    test_alignment()
