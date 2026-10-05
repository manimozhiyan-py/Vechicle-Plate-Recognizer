"""
URL configuration for lprecognition project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from recognition import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.upload_page, name="upload"),
    path("api/health/", views.health, name="health"),
    path("api/cameras/", views.list_cameras, name="cameras"),
    path("api/captures/", views.captures, name="captures"),
    path("api/captures/<uuid:capture_id>/", views.get_capture, name="capture-detail"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)  # serves uploaded images, only when DEBUG is on, just for getting the file for debuggin if needed