import numpy as np
import cv2
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .services.pipeline import recognize

#bsic call to recognizer
@csrf_exempt
@require_POST
def recognize_image(request):
    upload = request.FILES.get("image")
    if upload is None:
        return JsonResponse({"error": "Send an image in the 'image' field."}, status=400)

    data = np.frombuffer(upload.read(), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) #for 3 channel image

    return JsonResponse(recognize(image))