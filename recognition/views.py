import numpy as np
import cv2
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_datetime
from .models import Camera, Capture, Plate
from .services.pipeline import recognize
from .services.processing import process_capture
from .tasks import enqueue

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def error(message, status):
    return JsonResponse({"error": message}, status=status)


# turns a capture and its plates into a dict, used by every endpoint that returns a capture
def capture_to_dict(capture):
    plates = [
        {
            "uuid": str(p.uuid),
            "license_plate": p.license_plate,
            "raw_text": p.raw_text,
            "status": p.status,
            "confidence": round(min(p.detector_conf, p.ocr_conf), 3),  # the weaker of the two scores
            "bbox": p.bbox,
        }
        for p in capture.plates.all()
    ]
    purged = capture.image_purged_at is not None
    return {
        "uuid": str(capture.uuid),
        "camera": capture.camera_id,
        "status": capture.status,
        "outcome": capture.outcome,
        "captured_at": capture.captured_at.isoformat(),
        "processing_ms": capture.processing_ms,
        "model_version": capture.model_version,
        "error": capture.error,
        "image": None if purged else capture.image.url,
        "processed_image": None if purged else (capture.processed_image.url if capture.processed_image else None),
        "plates": plates,
    }


def create_capture(request):
    # 1. which camera sent it
    #we have to add auth to each camera in production
    camera = Camera.objects.filter(code=request.POST.get("camera")).first()
    if camera is None:
        return error("Unknown camera.", 400)

    # 2. the same key means the same frame, so return the saved result instead of processing again
    key = request.headers.get("Idempotency-Key", "").strip() or None
    if key:
        existing = Capture.objects.filter(idempotency_key=key).first()
        if existing:
            return JsonResponse(capture_to_dict(existing))

    # 3. checks on the file
    upload = request.FILES.get("image")
    if upload is None:
        return error("Send an image in the 'image' field.", 400)
    if upload.size > MAX_UPLOAD_BYTES:
        return error("Image is larger than 10 MB.", 413)

    data = np.frombuffer(upload.read(), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)  # for 3 channel image
    if image is None:
        return error("The file is not a valid image.", 400)
    upload.seek(0)  # we read the file above, rewind it so it can be saved

    # 4. optional time from the camera, defaults to now, in future we could make it pass it from cam like current image.
    captured_at = request.POST.get("captured_at")
    if captured_at:
        captured_at = parse_datetime(captured_at)
        if captured_at is None:
            return error("captured_at must look like 2026-10-04T12:30:00+05:30.", 400)

    # 5. save first, so the image is never lost even if processing crashes
    capture = Capture(camera=camera, image=upload, idempotency_key=key)
    if captured_at:
        capture.captured_at = captured_at
    capture.save()  # let any IntegrityError bubble up for debugging

    # 6, run the recognizer, this never raises, a crash is stored as status "failed"
    enqueue(capture.uuid)
    return JsonResponse(capture_to_dict(capture), status=201)


def list_captures(request):
    captures = Capture.objects.select_related("camera").prefetch_related("plates")
    for field in ("camera", "status", "ouat the same motcome"):  # ?camera=CAM-01&outcome=invalid_format
        value = request.GET.get(field)
        if value:
            captures = captures.filter(**{field: value})
    return JsonResponse({"results": [capture_to_dict(c) for c in captures[:50]]})


# one url, two jobs: POST uploads an image, GET lists captures
@csrf_exempt
@require_http_methods(["GET", "POST"])
def captures(request):
    if request.method == "POST":
        return create_capture(request)
    return list_captures(request)


@require_GET
def get_capture(request, capture_id):
    capture = Capture.objects.filter(pk=capture_id).first()
    if capture is None:
        return error("Capture not found.", 404)
    return JsonResponse(capture_to_dict(capture))


@require_GET
def list_cameras(request):
    cameras = [
        {"code": c.code, "name": c.name, "location": c.location}
        for c in Camera.objects.order_by("code")
    ]
    return JsonResponse({"results": cameras})


def upload_page(request):
    return render(request, "lprecognition/upload.html")

@require_GET
def health(request):
    checks = {}

    # Database
    try:
        Camera.objects.exists()
        Capture.objects.exists()
        checks["database"] = "ok"
    except DatabaseError as e:
        checks["database"] = f"error: {e}"

    # Celery broker (Redis/RabbitMQ)
    try:
        from lprecognition.celery import app
        with app.connection() as conn:
            conn.ensure_connection(max_retries=1)
        checks["broker"] = "ok"
    except Exception as e:
        checks["broker"] = f"error: {e}"

    # Celery workers (active)
    try:
        from lprecognition.celery import app
        inspect = app.control.inspect()
        active = inspect.active()
        checks["workers"] = "ok" if active else "no_active_workers"
    except Exception as e:
        checks["workers"] = f"error: {e}"

    # Overall status
    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return JsonResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status=status_code
    )