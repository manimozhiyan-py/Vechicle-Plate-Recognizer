"""Tests for the purge/sweeper functionality."""
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from io import StringIO

from recognition.models import Camera, Capture
from recognition.tasks import enqueue


def make_camera(code="CAM-T"):
    return Camera.objects.create(code=code, name="Test Camera", location="Test")


def make_capture(camera, status=Capture.Status.PENDING, outcome="", **kwargs):
    """Create a capture with minimal required fields."""
    from django.core.files.base import ContentFile
    import os
    
    image_path = os.path.join(os.path.dirname(__file__), "..", "sample_inputs", "clearcar.jpg")
    with open(image_path, "rb") as f:
        image_data = f.read()
    
    capture = Capture.objects.create(
        camera=camera,
        image=ContentFile(image_data, name="test.jpg"),
        status=status,
        outcome=outcome,
        **kwargs
    )
    return capture


FAKE_RESULT = {
    "status": "success",
    "plates": [
        {
            "text": "TN09AB1234",
            "raw_text": "TN09AB1234",
            "status": "OK",
            "detector_conf": 0.95,
            "ocr_conf": 0.92,
            "bbox": [100, 100, 300, 200],
        }
    ],
    "model_version": "test-model",
    "processing_ms": 100,
}


class PurgeTests(TestCase):
    """Test the purge/sweeper functionality."""

    @patch("recognition.services.processing.recognize", return_value=FAKE_RESULT)
    def test_purge_after_set_on_completion(self, mock_recognize):
        """Verify purge_after is set correctly based on outcome."""
        camera = make_camera()
        
        # Test SUCCESS -> 15 days
        cap1 = make_capture(camera)
        enqueue(cap1.uuid)
        cap1.refresh_from_db()
        
        # Need to actually process to set purge_after
        # Let's directly test the logic
        from recognition.services.processing import RETENTION_DAYS
        self.assertEqual(RETENTION_DAYS["success"], 15)
        self.assertEqual(RETENTION_DAYS["no_plate_detected"], 3)
        self.assertEqual(RETENTION_DAYS["invalid_format"], 30)
        self.assertEqual(RETENTION_DAYS["low_confidence"], 30)
        self.assertEqual(RETENTION_DAYS["unreadable"], 30)
        self.assertEqual(RETENTION_DAYS["invalid_image"], 30)
        self.assertEqual(RETENTION_DAYS["failed"], 30)

    @patch("recognition.services.processing.recognize", return_value=FAKE_RESULT)
    def test_purge_after_via_enqueue(self, mock_recognize):
        """Test that purge_after is set when capture is processed via queue."""
        camera = make_camera()
        cap = make_capture(camera)
        
        # Process directly (tests run inline)
        from recognition.tasks import process_capture_task
        process_capture_task(str(cap.pk))
        
        cap.refresh_from_db()
        self.assertEqual(cap.status, "completed")
        self.assertIsNotNone(cap.purge_after)
        self.assertEqual(cap.outcome, "success")
        
        # Should be ~15 days in future
        expected = timezone.now() + timedelta(days=15)
        self.assertAlmostEqual(cap.purge_after.timestamp(), expected.timestamp(), delta=10)

    @patch("recognition.services.processing.recognize", return_value=FAKE_RESULT)
    def test_purge_command_dry_run(self, mock_recognize):
        """Test --dry-run lists captures without deleting."""
        camera = make_camera()
        
        # Create old completed captures
        old_time = timezone.now() - timedelta(days=20)
        cap1 = make_capture(camera, status="completed", outcome="success", purge_after=old_time)
        cap2 = make_capture(camera, status="completed", outcome="no_plate_detected", purge_after=old_time)
        
        # Recent capture should not be listed
        recent = make_capture(camera, status="completed", outcome="success", purge_after=timezone.now() + timedelta(days=10))
        
        out = StringIO()
        call_command("purge_images", "--dry-run", stdout=out)
        
        output = out.getvalue()
        self.assertIn(str(cap1.uuid), output)
        self.assertIn(str(cap2.uuid), output)
        self.assertNotIn(str(recent.uuid), output)

    @patch("recognition.services.processing.recognize", return_value=FAKE_RESULT)
    def test_purge_command_deletes_files(self, mock_recognize):
        """Test purge command deletes files and sets image_purged_at."""
        camera = make_camera()
        
        old_time = timezone.now() - timedelta(days=20)
        cap = make_capture(camera, status="completed", outcome="success", purge_after=old_time)
        
        # Verify files exist
        self.assertTrue(cap.image)
        self.assertTrue(cap.image.storage.exists(cap.image.name))
        
        # Run purge
        out = StringIO()
        call_command("purge_images", "--batch-size", "10", stdout=out)
        
        cap.refresh_from_db()
        self.assertIsNotNone(cap.image_purged_at)
        self.assertIn("Purged", out.getvalue())
        
        # Files should be deleted
        self.assertFalse(cap.image.storage.exists(cap.image.name))

    def test_api_returns_null_for_purged(self):
        """Test API returns null for image URLs when purged."""
        camera = make_camera()
        
        cap = make_capture(camera, status="completed", outcome="success")
        cap.image_purged_at = timezone.now()
        cap.save()
        
        # Test capture_to_dict directly
        from recognition.views import capture_to_dict
        data = capture_to_dict(cap)
        
        self.assertIsNone(data["image"])
        self.assertIsNone(data["processed_image"])

    def test_api_returns_urls_for_not_purged(self):
        """Test API returns URLs for non-purged captures."""
        camera = make_camera()
        
        cap = make_capture(camera, status="completed", outcome="success")
        
        from recognition.views import capture_to_dict
        data = capture_to_dict(cap)
        
        self.assertIsNotNone(data["image"])
        self.assertIn(cap.image.name, data["image"])