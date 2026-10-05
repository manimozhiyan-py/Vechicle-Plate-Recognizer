import logging

from celery import shared_task
from django.db.models import F
from django.utils import timezone

from .models import Capture
from .services.processing import process_capture

logger = logging.getLogger(__name__)


@shared_task
def process_capture_task(capture_id):
    # claim the row: only one worker can flip pending -> processing.
    # a duplicate message finds 0 rows to change and stops here.
    claimed = Capture.objects.filter(pk=capture_id, status=Capture.Status.PENDING).update(
        status=Capture.Status.PROCESSING,
        attempts=F("attempts") + 1,
        locked_at=timezone.now(),
    )
    if not claimed:
        return
    process_capture(Capture.objects.get(pk=capture_id))


def enqueue(capture_id):
    print(capture_id)
    """Put one capture on the queue. Returns False if the broker is down.
    The row is already saved, so the reconciler will pick it up later."""
    try:
        process_capture_task.apply_async(args=[str(capture_id)], retry=False)
    except Exception:
        logger.warning("could not queue %s, the reconciler will retry", capture_id)
        return False
    Capture.objects.filter(pk=capture_id).update(queued_at=timezone.now())
    return True
