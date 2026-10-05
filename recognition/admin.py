from django.contrib import admin
from .models import Camera, Capture, Plate


admin.site.register(Camera)
admin.site.register(Capture)
admin.site.register(Plate)