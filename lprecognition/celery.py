import os

from celery import Celery
from celery.signals import worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lprecognition.settings")

app = Celery("lprecognition")
app.config_from_object("django.conf:settings", namespace="CELERY")  # reads CELERY_* settings
app.autodiscover_tasks()  # finds recognition/tasks.py


@worker_process_init.connect
def warm_up(**kwargs):
    """Load the models when a worker process starts, so the first image is not slow."""
    if os.environ.get("PLATE_WARM_UP", "1") == "1":
        from recognition.services.pipeline import get_recognizer
        get_recognizer()
