from django.test import SimpleTestCase
from recognition.services.validation import capture_status, clean_plate, plate_status


class CleanPlateTests(SimpleTestCase):
    def test_valid_plate_is_kept(self):
        self.assertEqual(clean_plate("AP21BC2008"), ("AP21BC2008", True))

    def test_spaces_and_lowercase_are_removed(self):
        self.assertEqual(clean_plate("ap 21 bc 2008"), ("AP21BC2008", True))

    def test_digit_in_a_letter_position_is_fixed(self):
        # the 8 sits where a series letter must be, so it becomes B
        self.assertEqual(clean_plate("AP218C2008"), ("AP21BC2008", True))

    def test_wrong_state_code_is_flagged_but_still_fixed(self):
        # the real ocr reading from our test image: I instead of A, 8 instead of B
        self.assertEqual(clean_plate("IP218C2008"), ("IP21BC2008", False))

    def test_garbage_is_not_valid(self):
        self.assertEqual(clean_plate("XYZ"), ("XYZ", False))

    def test_bharat_series_is_valid(self):
        self.assertEqual(clean_plate("22BH1234AA"), ("22BH1234AA", True))

    def test_delhi_style_plate_is_not_damaged_by_the_fixes(self):
        # the S in DL1S... is a real letter in a digit position, it must stay
        self.assertEqual(clean_plate("DL1SAB1234"), ("DL1SAB1234", True))


class PlateStatusTests(SimpleTestCase):
    def test_good_plate_is_ok(self):
        self.assertEqual(plate_status("AP21BC2008", 0.9, 0.9), ("AP21BC2008", "OK"))

    def test_invalid_format(self):
        self.assertEqual(plate_status("IP218C2008", 0.9, 0.9), ("IP21BC2008", "INVALID_FORMAT"))

    def test_low_confidence_uses_the_weaker_score(self):
        self.assertEqual(plate_status("AP21BC2008", 0.95, 0.5), ("AP21BC2008", "LOW_CONFIDENCE"))
        self.assertEqual(plate_status("AP21BC2008", 0.5, 0.95), ("AP21BC2008", "LOW_CONFIDENCE"))

    def test_invalid_format_is_reported_before_low_confidence(self):
        self.assertEqual(plate_status("IP218C2008", 0.9, 0.5)[1], "INVALID_FORMAT")

    def test_empty_text_is_unreadable(self):
        self.assertEqual(plate_status("", 0.9, 0.9), ("", "UNREADABLE"))


class CaptureStatusTests(SimpleTestCase):
    def test_no_plates(self):
        self.assertEqual(capture_status([]), "NO_PLATE_DETECTED")

    def test_all_ok_is_success(self):
        self.assertEqual(capture_status(["OK", "OK"]), "SUCCESS")

    def test_one_bad_plate_decides_the_whole_image(self):
        self.assertEqual(capture_status(["OK", "LOW_CONFIDENCE"]), "LOW_CONFIDENCE")
        self.assertEqual(capture_status(["OK", "INVALID_FORMAT"]), "INVALID_FORMAT")

    def test_unreadable_is_the_worst(self):
        self.assertEqual(capture_status(["INVALID_FORMAT", "UNREADABLE", "LOW_CONFIDENCE"]), "UNREADABLE")
