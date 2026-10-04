import re

MIN_CONFIDENCE = 0.8  # a plate below this goes to review

# validating here with the indian registration plate structure
# state and union territory codes.
STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ", "HP", "HR",
    "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "OR",
    "PB", "PY", "RJ", "SK", "TG", "TN", "TR", "TS", "UA", "UK", "UP", "WB",
}

STANDARD = re.compile(r"^([A-Z]{2})[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")  # AP21BC2008 AP21B2008  AP21BCD2008
BH_SERIES = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")           # 22BH1234AA

# characters ocr often mixes up
DIGIT_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
LETTER_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "Z": "2", "A": "4", "S": "5", "G": "6", "T": "7", "B": "8"}


def has_shape(text):
    return bool(STANDARD.match(text) or BH_SERIES.match(text))

def is_valid(text):
    if BH_SERIES.match(text):
        return True
    match = STANDARD.match(text)
    return bool(match) and match.group(1) in STATE_CODES


def fix_by_position(text):
    # assumes 2 state letters, 2 district digits, 1-3 series letters, 4 digits
    n = len(text)
    if not 8 <= n <= 11:
        return text
    kinds = "LL" + "DD" + "L" * (n - 8) + "DDDD"  # L = letter expected, D = digit expected
    fixed = ""
    for char, kind in zip(text, kinds):
        if kind == "L" and char.isdigit():
            char = DIGIT_TO_LETTER.get(char, char)
        elif kind == "D" and char.isalpha():
            char = LETTER_TO_DIGIT.get(char, char)
        fixed += char
    return fixed


def clean_plate(raw):
    """returns (text, valid). 
    only tries to fix the text when it does not look like a plate
    some plates are not recgnized well we need to train the model, for now, fix the position"""  # this decision is explained in 'working' docs in line

    text = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if not has_shape(text):
        fixed = fix_by_position(text)
        if has_shape(fixed):
            text = fixed
    return text, is_valid(text)
    
# validates plates
def plate_status(raw, detector_conf, ocr_conf):
    text, valid = clean_plate(raw)
    if not text:
        return text, "UNREADABLE"
    if not valid:
        return text, "INVALID_FORMAT"
    if min(detector_conf, ocr_conf) < MIN_CONFIDENCE:
        return text, "LOW_CONFIDENCE"
    return text, "OK"
    

# pass the plate status
def capture_status(plate_statuses):
    if not plate_statuses:
        return "NO_PLATE_DETECTED"
    for bad in ("UNREADABLE", "INVALID_FORMAT", "LOW_CONFIDENCE"):
        if bad in plate_statuses:
            return bad
    return "SUCCESS"
