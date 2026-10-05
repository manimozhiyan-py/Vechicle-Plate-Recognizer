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
from .validation import capture_status, plate_status

MODEL_PATH = os.environ.get("PLATE_MODEL_PATH", "models/best.pt")
OCR_MODEL = os.environ.get("PLATE_OCR_MODEL", "cct-s-v2-global-model")
DET_CONF = float(os.environ.get("PLATE_DET_CONF", "0.25"))
MODEL_VERSION = f"{Path(MODEL_PATH).name}+{OCR_MODEL}"


class PlateRecognizer:
    def __init__(self, model_path=MODEL_PATH, ocr_model=OCR_MODEL):
        self.detector = YOLO(str(model_path))
        self.ocr = LicensePlateRecognizer(ocr_model)

    def _read(self, crop):
        # our model is trained with rectangle shape plates where registration number in single line,
        # but there are kinda square number plates which has rregistration number in two lines.
        # in this case, we need to train our model for this case.
        # For now, lets crop them into two and join the text.
        h, w = crop.shape[:2]
        parts = [crop[: h // 2], crop[h // 2:]] if w / h < 2.5 else [crop]

        text, confs = "", []
        for part in parts:
            pred = self.ocr.run(part, return_confidence=True)[0]
            text += pred.plate.replace("_", "")
            confs.append(float(np.mean(pred.char_probs)))
        return text, sum(confs) / len(confs), pred.plate

    def recognize(self, image):
        """image: file path or BGR numpy array. Returns a dict that is easy to store."""
        start = time.perf_counter()
        img = cv2.imread(str(image)) if isinstance(image, (str, Path)) else image

        if img is None or img.size == 0:
            return self._result("INVALID_IMAGE", [], start)

        res = self.detector.predict(img, conf=DET_CONF, iou=0.4, verbose=False)[0]  # detects plates
        plates = []
        for box in sorted(res.boxes, key=lambda b: float(b.xyxy[0][0])):  # ordered left to right, and orchestrates reading
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            crop = img[max(0, y1):y2, max(0, x1):x2]
            if crop.size == 0:
                continue
            text, ocr_conf, raw_text = self._read(crop)
            ocr_conf = round(ocr_conf, 3)
            detector_conf = round(float(box.conf[0]), 3)

            # status of this one plate: OK, INVALID_FORMAT, LOW_CONFIDENCE or UNREADABLE
            text, status = plate_status(text, detector_conf, ocr_conf)
            plates.append({
                "text": text,
                "raw_text": raw_text,
                "status": status,
                "ocr_conf": ocr_conf,
                "detector_conf": detector_conf,
                "bbox": [x1, y1, x2, y2],
            })

        # status of the whole image, decided by its plates
        image_status = capture_status([p["status"] for p in plates])
        return self._result(image_status, plates, start)

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