import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from recognition.models import Camera, Capture, Plate

MEDIA_ROOT = tempfile.mkdtemp()

PLATE = {"text": "AP21BC2008", "raw_text": "AP21BC2008", "status": "OK",
         "detector_conf": 0.9, "ocr_conf": 0.9, "bbox": [5, 5, 40, 30]}


def result(status="SUCCESS", plates=None):
    return {"status": status, "plates": [PLATE] if plates is None else plates,
            "model_version": "test", "processing_ms": 12}


def image_file(name="car.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class CaptureApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        Camera.objects.create(code="CAM-01", name="Main gate")
        # the real recognizer loads the models, so every test uses a fake one
        patcher = patch("recognition.services.processing.recognize")
        self.recognize = patcher.start()
        self.recognize.return_value = result()
        self.addCleanup(patcher.stop)

    def upload(self, **extra):
        return self.client.post("/api/captures/", {"camera": "CAM-01", "image": image_file()}, **extra)

    def test_upload_saves_capture_and_plate(self):
        response = self.upload()
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["plates"][0]["license_plate"], "AP21BC2008")
        self.assertTrue(data["processed_image"])
        self.assertEqual(Capture.objects.count(), 1)
        self.assertEqual(Plate.objects.count(), 1)

    def test_two_plates_in_one_image_make_two_rows(self):
        second = {**PLATE, "text": "KA01AB1234", "raw_text": "KA01AB1234", "bbox": [50, 5, 60, 30]}
        self.recognize.return_value = result(plates=[PLATE, second])

        self.assertEqual(len(self.upload().json()["plates"]), 2)

    def test_status_decided_by_the_pipeline_is_stored(self):
        bad = {**PLATE, "text": "IP21BC2008", "raw_text": "IP218C2008", "status": "INVALID_FORMAT"}
        self.recognize.return_value = result(status="INVALID_FORMAT", plates=[bad])
        data = self.upload().json()

        self.assertEqual(data["outcome"], "invalid_format")
        self.assertEqual(data["plates"][0]["status"], "invalid_format")
        self.assertEqual(data["plates"][0]["license_plate"], "IP21BC2008")  # cleaned
        self.assertEqual(data["plates"][0]["raw_text"], "IP218C2008")       # what the ocr read

    def test_low_confidence_status_is_stored(self):
        unsure = {**PLATE, "status": "LOW_CONFIDENCE", "ocr_conf": 0.5}
        self.recognize.return_value = result(status="LOW_CONFIDENCE", plates=[unsure])
        data = self.upload().json()

        self.assertEqual(data["outcome"], "low_confidence")
        self.assertEqual(data["plates"][0]["confidence"], 0.5)

    def test_no_plate_detected(self):
        self.recognize.return_value = result(status="NO_PLATE_DETECTED", plates=[])
        data = self.upload().json()

        self.assertEqual(data["outcome"], "no_plate_detected")
        self.assertEqual(data["plates"], [])
        self.assertIsNone(data["processed_image"])

    def test_crash_is_stored_as_failed_and_the_image_is_kept(self):
        self.recognize.side_effect = RuntimeError("model exploded")
        data = self.upload().json()

        self.assertEqual(data["status"], "failed")
        self.assertIn("model exploded", data["error"])
        self.assertEqual(Capture.objects.count(), 1)

    def test_unknown_camera_is_rejected(self):
        response = self.client.post("/api/captures/", {"camera": "NOPE", "image": image_file()})

        self.assertEqual(response.status_code, 400)

    def test_missing_file_is_rejected(self):
        response = self.client.post("/api/captures/", {"camera": "CAM-01"})

        self.assertEqual(response.status_code, 400)

    def test_file_that_is_not_an_image_is_rejected(self):
        fake = SimpleUploadedFile("car.jpg", b"not an image", content_type="image/jpeg")
        response = self.client.post("/api/captures/", {"camera": "CAM-01", "image": fake})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Capture.objects.count(), 0)

    @patch("recognition.views.MAX_UPLOAD_BYTES", 1)
    def test_large_file_is_rejected(self):
        self.assertEqual(self.upload().status_code, 413)

    def test_same_key_returns_the_first_capture(self):
        first = self.upload(HTTP_IDEMPOTENCY_KEY="abc")
        second = self.upload(HTTP_IDEMPOTENCY_KEY="abc")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["uuid"], second.json()["uuid"])
        self.assertEqual(Capture.objects.count(), 1)
        self.recognize.assert_called_once()

    def test_uploads_without_a_key_are_never_duplicates(self):
        self.upload()
        self.upload()

        self.assertEqual(Capture.objects.count(), 2)

    def test_get_one_capture(self):
        uuid = self.upload().json()["uuid"]

        self.assertEqual(self.client.get(f"/api/captures/{uuid}/").status_code, 200)
        self.assertEqual(self.client.get("/api/captures/00000000-0000-0000-0000-000000000000/").status_code, 404)

    def test_list_can_be_filtered(self):
        Camera.objects.create(code="CAM-02", name="Back gate")
        Capture.objects.create(camera_id="CAM-01", image="a.jpg", outcome="success")
        Capture.objects.create(camera_id="CAM-02", image="b.jpg", outcome="invalid_format")

        by_camera = self.client.get("/api/captures/", {"camera": "CAM-02"}).json()["results"]
        by_outcome = self.client.get("/api/captures/", {"outcome": "success"}).json()["results"]

        self.assertEqual([c["camera"] for c in by_camera], ["CAM-02"])
        self.assertEqual([c["camera"] for c in by_outcome], ["CAM-01"])


class OtherEndpointTests(TestCase):
    def test_cameras_are_listed(self):
        Camera.objects.create(code="CAM-02", name="Back gate")
        Camera.objects.create(code="CAM-01", name="Main gate")

        codes = [c["code"] for c in self.client.get("/api/cameras/").json()["results"]]

        self.assertEqual(codes, ["CAM-01", "CAM-02"])

    def test_health(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})

    def test_upload_page(self):
        self.assertContains(self.client.get("/"), "Read a number plate")
