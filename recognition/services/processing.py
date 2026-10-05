import logging

import cv2
import numpy as np
from django.core.files.base import ContentFile
from django.db import transaction

from ..models import Capture, Plate
from .pipeline import recognize

logger = logging.getLogger(__name__)

# for saving the images, drawing rect as we detected
def draw_plates(image, plates):
    out = image.copy()  # keep the original untouched
    for p in plates:
        x1, y1, x2, y2 = p["bbox"]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(out, p["text"] or "?", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
    return out


def save_result(capture, image, result):
    
    # the pipeline already cleaned the text and decided every status, here we only store them
    for p in result["plates"]:
        Plate.objects.create(
            capture=capture,
            license_plate=p["text"],
            raw_text=p["raw_text"],
            status=p["status"].lower(),
            detector_conf=p["detector_conf"],
            ocr_conf=p["ocr_conf"],
            bbox=p["bbox"],
        )

    if result["plates"]:
        ok, buffer = cv2.imencode(".jpg", draw_plates(image, result["plates"]))
        capture.processed_image.save("processed.jpg", ContentFile(buffer.tobytes()), save=False)

    capture.outcome = result["status"].lower()
    capture.processing_ms = result["processing_ms"]
    capture.model_version = result["model_version"]
    capture.status = Capture.Status.COMPLETED
    capture.save()


def process_capture(capture):
    """runs the recognizer on a saved capture and stores the result. never raises.
    it reads the image from the saved file, so a worker can call it later with just the capture"""
    capture.status = Capture.Status.PROCESSING
    capture.save(update_fields=["status"])

    try:
        with capture.image.open("rb") as file:
            image = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
        result = recognize(image)
        with transaction.atomic():  # all plates are saved, or none
            save_result(capture, image, result)
    except Exception as exc:  # a crashed job must not lose the image
        logger.exception("processing failed for capture %s", capture.pk)
        capture.status = Capture.Status.FAILED
        capture.error = str(exc)[:1000]
        capture.save(update_fields=["status", "error"])
    return capture