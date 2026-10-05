import uuid
from pathlib import Path
from django.db import models
from django.utils import timezone

# instead of hardcoding the file directory : 
def _path(folder, instance, filename):
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"captures/{folder}/{timezone.now():%Y/%m/%d}/{instance.uuid}{ext}"  # blob storage directorry structure

def original_path(instance, filename):
    return _path("original", instance, filename)

def processed_path(instance, filename):
    return _path("processed", instance, filename)


# Camera table contains the details of camera and its location

class Camera(models.Model):
    code = models.CharField(max_length=50, primary_key=True)  # planned for readable ids so "CAM-GATE-01"
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


# Capture contains the detaills of the whole process; the image, outcome, status, location, processing time, etc
# idempotency key to ensure same frame not processed again. 

class Capture(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"          # the job crashed; details in `error`


    class Outcome(models.TextChoices):
        SUCCESS = "success"
        INVALID_FORMAT = "invalid_format"    # a plate was read, but it is not a valid indian plate
        LOW_CONFIDENCE = "low_confidence"    # valid plate, but the model is not sure
        UNREADABLE = "unreadable"
        NO_PLATE_DETECTED = "no_plate_detected"
        INVALID_IMAGE = "invalid_image"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    camera = models.ForeignKey(Camera, on_delete=models.PROTECT, related_name="captures")
    image = models.ImageField(upload_to=original_path)
    processed_image = models.ImageField(upload_to=processed_path, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    processing_ms = models.PositiveIntegerField(null=True, blank=True)
    model_version = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)    # times a worker claimed it
    locked_at = models.DateTimeField(null=True, blank=True)   # when the current attempt started
    queued_at = models.DateTimeField(null=True, blank=True)   # when the id was last queued
    class Meta:
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["camera", "-captured_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.uuid} ({self.camera_id}, {self.status})"


# Plate has the details of the successfully recongized numbers and its confidence 

class Plate(models.Model):
    class Status(models.TextChoices):
        OK = "ok"
        INVALID_FORMAT = "invalid_format"
        LOW_CONFIDENCE = "low_confidence"
        UNREADABLE = "unreadable"
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    capture = models.ForeignKey(Capture, on_delete=models.CASCADE, related_name="plates")
    license_plate = models.CharField(max_length=30, db_index=True) # after cleaning and correction
    raw_text = models.CharField(max_length=30, blank=True)          # exactly what the ocr read
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)# decided by the
    detector_conf = models.FloatField()
    ocr_conf = models.FloatField()
    bbox = models.JSONField() 

    def __str__(self):
        return self.license_plate