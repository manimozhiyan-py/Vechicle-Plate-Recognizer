from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from recognition.models import Capture
from recognition.tasks import process_capture_task

from .helpers import FAKE_RESULT, CaptureTestCase, jpeg_bytes, make_camera, make_capture

RECOGNIZE = "recognition.services.processing.recognize"


class TaskTests(CaptureTestCase):
    @patch(RECOGNIZE, return_value=FAKE_RESULT)
    def test_pending_capture_is_processed(self, recognize):
        capture = make_capture()
        process_capture_task(str(capture.pk))

        capture.refresh_from_db()
        self.assertEqual(capture.status, "completed")
        self.assertEqual(capture.outcome, "success")
        self.assertEqual(capture.attempts, 1)
        self.assertIsNotNone(capture.locked_at)
        self.assertEqual(capture.plates.count(), 1)
        self.assertTrue(capture.processed_image)
        # success images are kept 30 days
        days = (capture.purge_after - timezone.now()).days
        self.assertIn(days, (29, 30))

    @patch(RECOGNIZE, return_value=FAKE_RESULT)
    def test_duplicate_message_does_nothing(self, recognize):
        capture = make_capture(status="processing")  # another worker already has it
        process_capture_task(str(capture.pk))

        recognize.assert_not_called()
        capture.refresh_from_db()
        self.assertEqual(capture.attempts, 0)

    @patch(RECOGNIZE, side_effect=RuntimeError("boom"))
    def test_crash_marks_failed(self, recognize):
        capture = make_capture()
        process_capture_task(str(capture.pk))

        capture.refresh_from_db()
        self.assertEqual(capture.status, "failed")
        self.assertEqual(capture.error, "boom")
        self.assertEqual(capture.attempts, 1)  # no automatic retry

    @patch(RECOGNIZE, return_value=FAKE_RESULT)
    def test_upload_replies_202_then_finishes(self, recognize):
        make_camera()
        upload = SimpleUploadedFile("t.jpg", jpeg_bytes(), content_type="image/jpeg")
        response = self.client.post("/api/captures/", {"camera": "CAM-T", "image": upload})

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "pending")

        # tests run Celery inline, so the job is already done
        data = self.client.get(f"/api/captures/{response.json()['uuid']}/").json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["plates"][0]["license_plate"], "TN09AB1234")

    @patch("recognition.views.enqueue", return_value=False)  # pretend Redis is down
    def test_upload_still_202_when_queue_is_down(self, enqueue):
        make_camera()
        upload = SimpleUploadedFile("t.jpg", jpeg_bytes(), content_type="image/jpeg")
        response = self.client.post("/api/captures/", {"camera": "CAM-T", "image": upload})

        self.assertEqual(response.status_code, 202)
        capture = Capture.objects.get(pk=response.json()["uuid"])
        self.assertEqual(capture.status, "pending")  # the reconciler will pick it up
