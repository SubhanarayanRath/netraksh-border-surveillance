import cv2
import numpy as np

def test_alignment_exact():
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    
    landmarks = np.array([
        [100, 100], [200, 100], [150, 150], [120, 200], [180, 200]
    ], dtype=np.float32)
    
    face_box = np.array([
        50, 50, 200, 200,
        100, 100, 200, 100, 150, 150, 120, 200, 180, 200, 0.99
    ], dtype=np.float32)
    
    model_path = "face_recognition_sface_2021dec.onnx"
    recognizer = cv2.FaceRecognizerSF.create(model_path, "")
    aligned_ref = recognizer.alignCrop(image, face_box)
    
    # Try with cv2.estimateAffinePartial2D
    dst_pts = np.array([
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041]
    ], dtype=np.float32)
    
    M, _ = cv2.estimateAffinePartial2D(landmarks, dst_pts)
    aligned_dir1 = cv2.warpAffine(image, M, (112, 112), borderValue=0.0)
    
    M2, _ = cv2.estimateAffinePartial2D(landmarks, dst_pts, method=cv2.LMEDS)
    aligned_dir2 = cv2.warpAffine(image, M2, (112, 112), borderValue=0.0)
    
    # Also in OpenCV Zoo's original python script they use:
    # skimage.transform.SimilarityTransform, but since it differs, maybe we should use cv2.estimateAffinePartial2D
    
    diff1 = np.max(np.abs(aligned_ref.astype(np.float32) - aligned_dir1.astype(np.float32)))
    diff2 = np.max(np.abs(aligned_ref.astype(np.float32) - aligned_dir2.astype(np.float32)))
    
    print(f"Diff standard: {diff1}")
    print(f"Diff LMEDS: {diff2}")

if __name__ == "__main__":
    test_alignment_exact()
