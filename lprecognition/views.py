import numpy as np
import cv2
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .services.pipeline import recognize


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def error(message, status):
    return JsonResponse({"error": message}, status=status)


#bsic call to recognizer
@csrf_exempt
@require_POST
def recognize_image(request):
    upload = request.FILES.get("image")
    if upload is None:
        return error({"error": "Send an image in the 'image' field."}, status=400)
    if upload.size > MAX_UPLOAD_BYTES:
        return error("Image is larger than 10 MB.", 413)

    data = np.frombuffer(upload.read(), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) #for 3 channel image

    if image is None:
        return error("The file is not a valid image.", 400)

    return JsonResponse(recognize(image))