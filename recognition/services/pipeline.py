"""Plate recognition: YOLO detector -> crop -> fast-plate-ocr."""
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from fast_plate_ocr import LicensePlateRecognizer
from ultralytics import YOLO

MODEL_PATH = os.environ.get("PLATE_MODEL_PATH", "models/best.pt")
OCR_MODEL = os.environ.get("PLATE_OCR_MODEL", "cct-s-v2-global-model")
DET_CONF = float(os.environ.get("PLATE_DET_CONF", "0.25"))
MODEL_VERSION = f"{Path(MODEL_PATH).name}+{OCR_MODEL}"


class PlateRecognizer:
    def __init__(self, model_path=MODEL_PATH, ocr_model=OCR_MODEL):
        self.detector = YOLO(str(model_path))
        self.ocr = LicensePlateRecognizer(ocr_model)

    def _read(self, crop):
        """OCR one plate crop. Two-line (near-square) plates are read line by line."""
        h, w = crop.shape[:2]
        parts = [crop[: h // 2], crop[h // 2:]] if w / h < 2.5 else [crop]

        text, confs = "", []
        for part in parts:
            pred = self.ocr.run(part, return_confidence=True)[0]
            text += pred.plate
            confs.append(float(np.mean(pred.char_probs)))
        return text.replace("_", ""), sum(confs) / len(confs)

    def recognize(self, image):
        """image: file path or BGR numpy array. Returns a dict that is easy to store."""
        start = time.perf_counter()
        img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image

        if img is None or img.size == 0:
            return self._result("INVALID_IMAGE", [], start)

        res = self.detector.predict(img, conf=DET_CONF, iou=0.4, verbose=False)[0]

        plates = []
        for box in sorted(res.boxes, key=lambda b: float(b.xyxy[0][0])):  # left to right
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            crop = img[max(0, y1):y2, max(0, x1):x2]
            if crop.size == 0:
                continue
            text, ocr_conf = self._read(crop)
            plates.append({
                "text": text,
                "ocr_conf": round(ocr_conf, 3),
                "detector_conf": round(float(box.conf[0]), 3),
                "bbox": [x1, y1, x2, y2],
            })

        if not plates:
            status = "NO_PLATE_DETECTED"
        elif any(p["text"] for p in plates):
            status = "SUCCESS"
        else:
            status = "UNREADABLE"
        return self._result(status, plates, start)

    @staticmethod
    def _result(status, plates, start):
        return {
            "status": status,
            "plates": plates,
            "model_version": MODEL_VERSION,
            "processing_ms": int((time.perf_counter() - start) * 1000),
        }


@lru_cache(maxsize=1)
def get_recognizer():
    """Models load once per process, on first use."""
    return PlateRecognizer()


def recognize(image):
    return get_recognizer().recognize(image)


if __name__ == "__main__":
    import json
    print(json.dumps(recognize(sys.argv[1]), indent=2))