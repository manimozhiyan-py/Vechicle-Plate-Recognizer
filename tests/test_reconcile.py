"""Tests for the reconcile management command."""
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from io import StringIO

from recognition.models import Camera, Capture
from recognition.tasks import enqueue as real_enqueue


def make_camera(code="CAM-T"):
    return Camera.objects.create(code=code, name="Test Camera", location="Test")


def make_capture(camera, status=Capture.Status.PENDING, **kwargs):
    """Create a capture with minimal required fields."""
    from django.core.files.base import ContentFile
    import os
    
    # Use an existing image file
    image_path = os.path.join(os.path.dirname(__file__), "..", "sample_inputs", "clearcar.jpg")
    with open(image_path, "rb") as f:
        image_data = f.read()
    
    capture = Capture.objects.create(
        camera=camera,
        image=ContentFile(image_data, name="test.jpg"),
        status=status,
        **kwargs
    )
    return capture


class ReconcileCommandTests(TestCase):
    """Test the reconcile management command."""

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_pending_never_queued(self, mock_enqueue):
        """PENDING captures with queued_at=NULL should be re-queued."""
        # Use side_effect to call real enqueue (which updates queued_at)
        mock_enqueue.side_effect = real_enqueue
        
        camera = make_camera()
        cap = make_capture(camera, status=Capture.Status.PENDING, queued_at=None)
        
        out = StringIO()
        call_command("reconcile", stdout=out)
        
        mock_enqueue.assert_called_once_with(cap.uuid)
        self.assertIn(str(cap.uuid), out.getvalue())
        
        cap.refresh_from_db()
        self.assertIsNotNone(cap.queued_at)

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_processing_stuck(self, mock_enqueue):
        """PROCESSING captures stuck >5min should be reset and re-queued."""
        mock_enqueue.side_effect = real_enqueue
        
        camera = make_camera()
        old_time = timezone.now() - timedelta(minutes=10)
        cap = make_capture(
            camera, 
            status=Capture.Status.PROCESSING, 
            locked_at=old_time
        )
        
        out = StringIO()
        call_command("reconcile", stdout=out)
        
        mock_enqueue.assert_called_once_with(cap.uuid)
        self.assertIn("resetting to PENDING", out.getvalue())
        
        cap.refresh_from_db()
        self.assertEqual(cap.status, Capture.Status.PENDING)
        self.assertIsNone(cap.locked_at)
        self.assertIsNotNone(cap.queued_at)

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_skips_normal_pending(self, mock_enqueue):
        """PENDING captures with queued_at set should be skipped."""
        camera = make_camera()
        cap = make_capture(camera, status=Capture.Status.PENDING, queued_at=timezone.now())
        
        out = StringIO()
        call_command("reconcile", stdout=out)
        
        mock_enqueue.assert_not_called()
        self.assertIn("No stuck captures found", out.getvalue())

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_skips_completed(self, mock_enqueue):
        """COMPLETED/FAILED captures should be skipped."""
        camera = make_camera()
        cap = make_capture(camera, status=Capture.Status.COMPLETED, queued_at=None)
        
        out = StringIO()
        call_command("reconcile", stdout=out)
        
        mock_enqueue.assert_not_called()
        self.assertIn("No stuck captures found", out.getvalue())

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_respects_limit(self, mock_enqueue):
        """Should respect the --limit parameter."""
        camera = make_camera()
        for i in range(5):
            make_capture(camera, status=Capture.Status.PENDING, queued_at=None)
        
        out = StringIO()
        call_command("reconcile", "--limit", "3", stdout=out)
        
        self.assertEqual(mock_enqueue.call_count, 3)

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_dry_run(self, mock_enqueue):
        """--dry-run should not actually enqueue."""
        camera = make_camera()
        cap = make_capture(camera, status=Capture.Status.PENDING, queued_at=None)
        
        out = StringIO()
        call_command("reconcile", "--dry-run", stdout=out)
        
        mock_enqueue.assert_not_called()
        self.assertIn("Would re-queue", out.getvalue())
        
        cap.refresh_from_db()
        self.assertIsNone(cap.queued_at)

    @patch("recognition.management.commands.reconcile.enqueue")
    def test_reconcile_custom_stuck_minutes(self, mock_enqueue):
        """--stuck-minutes should change the threshold."""
        camera = make_camera()
        
        # 3 minutes old - should NOT be stuck with default 5 min
        cap1 = make_capture(
            camera, 
            status=Capture.Status.PROCESSING, 
            locked_at=timezone.now() - timedelta(minutes=3)
        )
        
        out = StringIO()
        call_command("reconcile", "--stuck-minutes", "5", stdout=out)
        mock_enqueue.assert_not_called()
        
        # Reset mock for second call
        mock_enqueue.reset_mock()
        
        # But SHOULD be stuck with 2 min threshold
        call_command("reconcile", "--stuck-minutes", "2", stdout=out)
        mock_enqueue.assert_called_once_with(cap1.uuid)