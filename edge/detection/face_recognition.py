"""
NETRAKSH Edge — Real watchlist face recognition (SIH PS 26187: "support
facial recognition", not detection alone).

Every prior mention of face recognition in this codebase disclosed it as
NOT implemented (`edge/rules/modules.py`'s FaceDetectionModule docstring:
"Architecture §15: MVP is detection only. Recognition (ArcFace) is
advanced/stretch."). This is the real, first implementation.

HONEST SCOPE — read before treating a match as anything more than a lead:
- Uses `cv2.face.LBPHFaceRecognizer` (Local Binary Patterns Histograms) —
  OpenCV's classical, CPU-friendly recognizer, trained directly on real,
  admin-enrolled reference photos (`backend/api/watchlist.py`). Requires
  `opencv-contrib-python-headless` (see requirements.txt) — the plain
  `opencv-python-headless` package never ships `cv2.face`, at any version.
- NOT a production-grade deep-learning FRS (no ArcFace/FaceNet embeddings).
  LBPH is a real, genuinely-working, decades-old classical CV technique —
  not fabricated, not a stub — but its real published accuracy is
  meaningfully behind modern embedding-based recognizers, especially
  across real lighting/pose/expression variation.
- No liveness detection anywhere in this pipeline — a printed photo held
  up to a camera matches exactly like the real person. Never use a match
  from this module as the sole basis for a consequential decision; treat
  it as a lead for human review, the same posture ANPR/plate reads and
  every other soft-evidence signal in this project already carry.
- Not appropriate for large-scale (hundreds+) 1:N identification — LBPH's
  real accuracy degrades as the enrolled watchlist population grows.
"""
from __future__ import annotations

import base64
import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Disclosed, hand-picked threshold: LBPH's predict() returns a real
# distance (LOWER = better match — unlike a probability where higher is
# better — and not bounded to [0,1]). There is no universal "correct"
# value; OpenCV's own documentation suggests roughly 50-80 as a reasonable
# cutoff for "same person" on reasonably-controlled face crops. Chosen
# conservative (stricter/lower) to bias toward missed matches over false
# matches — consistent with this project's established preference for
# ABSTAIN/UNCERTAIN over a fabricated confident answer (edge/reliability/
# decision.py) — a false watchlist match is a materially worse outcome
# for border security than a missed one.
LBPH_MATCH_THRESHOLD = 60.0

# LBPH requires every training/query image to be the same size.
FACE_IMAGE_SIZE = (200, 200)


class WatchlistFaceRecognizer:
    """Wraps cv2.face.LBPHFaceRecognizer — see module docstring for the
    full honest scope of what a "match" from this class does and doesn't
    mean."""

    def __init__(self):
        import cv2
        self._recognizer = cv2.face.LBPHFaceRecognizer_create()
        self._label_to_person: Dict[int, dict] = {}
        self._trained = False

    def train(self, persons: List[dict]) -> int:
        """
        persons: [{"person_id": str, "name": str, "images": List[np.ndarray]}]
        (grayscale, FACE_IMAGE_SIZE — see decode_base64_face_image).
        Returns the real number of training images used.

        Trains from scratch every call (cv2.face's .train(), not
        .update()) — correct for a periodic full re-sync from
        GET /watchlist/sync: a person removed from the watchlist genuinely
        stops being matchable on the next sync, not just "no longer added
        to" an ever-growing model.
        """
        images: List[np.ndarray] = []
        labels: List[int] = []
        self._label_to_person = {}
        for idx, person in enumerate(persons):
            self._label_to_person[idx] = {"person_id": person["person_id"], "name": person["name"]}
            for img in person["images"]:
                images.append(img)
                labels.append(idx)

        if not images:
            self._trained = False
            logger.warning("[FaceRecognition] No real training images available — recognizer left untrained")
            return 0

        self._recognizer.train(images, np.array(labels))
        self._trained = True
        logger.info(
            f"[FaceRecognition] Trained on {len(images)} real reference image(s) "
            f"across {len(persons)} watchlist person(s)"
        )
        return len(images)

    def recognize(self, face_crop: np.ndarray) -> Optional[dict]:
        """
        face_crop: a real crop of a detected face (BGR or grayscale).
        Returns {"person_id", "name", "confidence"} for a real match within
        LBPH_MATCH_THRESHOLD, else None. `confidence` is LBPH's own raw
        distance (lower = better), surfaced as-is — never inverted into a
        fake 0-1 "probability" LBPH doesn't actually produce.
        """
        if not self._trained:
            return None
        import cv2
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY) if face_crop.ndim == 3 else face_crop
        if gray.size == 0:
            return None
        resized = cv2.resize(gray, FACE_IMAGE_SIZE)
        try:
            label, distance = self._recognizer.predict(resized)
        except Exception as exc:
            logger.debug(f"[FaceRecognition] predict() failed: {exc}")
            return None
        if distance > LBPH_MATCH_THRESHOLD:
            return None
        person = self._label_to_person.get(label)
        if person is None:
            return None
        return {"person_id": person["person_id"], "name": person["name"], "confidence": float(distance)}

    def is_trained(self) -> bool:
        return self._trained


def decode_base64_face_image(image_base64: str) -> Optional[np.ndarray]:
    """Real base64 JPEG -> grayscale numpy array, resized to
    FACE_IMAGE_SIZE. Returns None (never a fabricated placeholder image)
    if decoding genuinely fails."""
    import cv2
    try:
        raw = base64.b64decode(image_base64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return cv2.resize(img, FACE_IMAGE_SIZE)
    except Exception:
        return None


def sync_from_backend(backend_url: str, timeout: float = 10.0) -> WatchlistFaceRecognizer:
    """
    Real HTTP GET /watchlist/sync, decodes every real reference image, and
    trains a fresh WatchlistFaceRecognizer. Returns an untrained-but-real
    recognizer on any failure — recognize() then honestly returns None for
    everything rather than raising, matching this project's established
    non-fatal-failure posture for edge/main.py's real-time frame loop
    (e.g. _report_metrics' backend push, night_motion_fallback).
    """
    import httpx
    recognizer = WatchlistFaceRecognizer()
    try:
        resp = httpx.get(f"{backend_url}/watchlist/sync", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[FaceRecognition] Watchlist sync failed (non-fatal, recognizer stays untrained): {exc}")
        return recognizer

    persons = []
    for entry in data.get("persons", []):
        images = []
        for b64 in entry.get("image_base64_list", []):
            img = decode_base64_face_image(b64)
            if img is not None:
                images.append(img)
        if images:
            persons.append({"person_id": entry["person_id"], "name": entry["name"], "images": images})

    recognizer.train(persons)
    return recognizer
