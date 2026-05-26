import argparse, csv, os, re, sys
from threading import Lock
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

_BACKEND_DIR = Path(__file__).resolve().parent
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_BACKEND_DIR / ".paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

# ── ultralytics ───────────────────────────────────────────────────────────────
try:
    from ultralytics import YOLO
except ImportError:
    sys.exit("[ERROR] Install:  pip install ultralytics")

PADDLE_AVAILABLE = False
try:
    from paddleocr import PaddleOCR, TextRecognition
    PADDLE_AVAILABLE = True
except Exception as exc:
    PADDLEOCR_IMPORT_ERROR = exc
    TextRecognition = None
else:
    PADDLEOCR_IMPORT_ERROR = None

# ── RapidOCR (primary, PaddleOCR models via ONNX) ─────────────────────────────
RAPID_AVAILABLE = False
try:
    from rapidocr_onnxruntime import RapidOCR
    RAPID_AVAILABLE = True
except ImportError:
    pass

# ── EasyOCR (fallback) ───────────────────────────────────────────────────────
EASY_AVAILABLE = False
try:
    import easyocr
    EASY_AVAILABLE = True
except ImportError:
    pass

OCR_AVAILABLE = PADDLE_AVAILABLE or RAPID_AVAILABLE or EASY_AVAILABLE
if not OCR_AVAILABLE:
    print("[WARN] No OCR engine - install paddleocr+paddlepaddle, rapidocr_onnxruntime, or easyocr")

OCR_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_paddle_ocr = None
_paddle_rec = None
_rapid_ocr = None
_easy_reader = None
_ocr_lock = Lock()
_paddle_rec_lock = Lock()


def _get_ocr():
    global OCR_AVAILABLE, PADDLE_AVAILABLE, _paddle_ocr, _rapid_ocr, _easy_reader

    if PADDLE_AVAILABLE:
        if _paddle_ocr is None:
            with _ocr_lock:
                if _paddle_ocr is None:
                    print("[INFO] Initialising PaddleOCR...")
                    try:
                        _paddle_ocr = PaddleOCR(
                            text_detection_model_name="PP-OCRv5_mobile_det",
                            text_recognition_model_name="en_PP-OCRv5_mobile_rec",
                            use_doc_orientation_classify=False,
                            use_doc_unwarping=False,
                            use_textline_orientation=False,
                            text_det_limit_side_len=960,
                            text_det_limit_type="max",
                            text_rec_score_thresh=0.0,
                        )
                    except Exception as exc:
                        PADDLE_AVAILABLE = False
                        OCR_AVAILABLE = RAPID_AVAILABLE or EASY_AVAILABLE
                        print(f"[WARN] PaddleOCR unavailable; falling back if possible: {exc}")
                    else:
                        print("[INFO] PaddleOCR ready.")
                        return _paddle_ocr
                else:
                    return _paddle_ocr
        else:
            return _paddle_ocr

    if RAPID_AVAILABLE:
        if _rapid_ocr is None:
            with _ocr_lock:
                if _rapid_ocr is None:
                    print("[INFO] Initialising RapidOCR...")
                    _rapid_ocr = RapidOCR()
                    print("[INFO] RapidOCR ready.")
        return _rapid_ocr

    if EASY_AVAILABLE:
        if _easy_reader is None:
            with _ocr_lock:
                if _easy_reader is None:
                    print("[INFO] Initialising EasyOCR (fallback)...")
                    _easy_reader = easyocr.Reader(["en"], gpu=False, detector=True, verbose=False)
                    print("[INFO] EasyOCR ready.")
        return _easy_reader

    return None


def _get_paddle_recognizer():
    global _paddle_rec

    if not PADDLE_AVAILABLE or TextRecognition is None:
        return None

    if _paddle_rec is None:
        with _paddle_rec_lock:
            if _paddle_rec is None:
                print("[INFO] Initialising Paddle text recognizer...")
                _paddle_rec = TextRecognition(model_name="en_PP-OCRv5_mobile_rec")
                print("[INFO] Paddle text recognizer ready.")
    return _paddle_rec


def warm_up_ocr():
    """Initialise OCR models once so first detection request does not pay setup cost."""
    engine = _get_ocr()
    if engine is _paddle_ocr:
        _get_paddle_recognizer()
    return engine is not None


def _clean_ocr_text(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _box_left(box):
    try:
        pts = np.asarray(box, dtype=float).reshape(-1, 2)
        if pts.size:
            return float(np.min(pts[:, 0]))
    except Exception:
        pass
    return 0.0


def _normalise_confidence(conf):
    try:
        if isinstance(conf, (list, tuple, np.ndarray)):
            if len(conf) == 0:
                return 0.0
            conf = conf[0]
        return float(conf)
    except Exception:
        return 0.0


def _prepare_paddle_image(img):
    if img is None:
        return img
    if getattr(img, "ndim", None) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if getattr(img, "ndim", None) == 3 and img.shape[2] == 1:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if getattr(img, "ndim", None) == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def _read_paddle_recognition(img):
    recognizer = _get_paddle_recognizer()
    if recognizer is None:
        return []

    result = recognizer.predict(_prepare_paddle_image(img))
    tokens = []
    for item in result or []:
        if not isinstance(item, dict):
            continue
        clean = _clean_ocr_text(item.get("rec_text"))
        if clean:
            tokens.append((clean, _normalise_confidence(item.get("rec_score"))))
    return tokens


def _read_paddleocr(img):
    tokens = []
    try:
        tokens.extend(_read_paddle_recognition(img))
    except Exception as exc:
        print(f"[WARN] Paddle text recognizer failed: {exc}")

    result = _paddle_ocr.predict(_prepare_paddle_image(img))
    if not result:
        return tokens

    for page in result:
        if isinstance(page, dict) and "rec_texts" in page:
            texts = page.get("rec_texts")
            scores = page.get("rec_scores")
            if texts is None:
                texts = []
            if scores is None:
                scores = []
            boxes = page.get("rec_polys")
            if boxes is None or len(boxes) == 0:
                boxes = page.get("dt_polys")
            if boxes is None:
                boxes = []
            order = sorted(
                range(len(texts)),
                key=lambda i: _box_left(boxes[i]) if i < len(boxes) else float(i),
            )
            for i in order:
                clean = _clean_ocr_text(texts[i])
                if clean:
                    conf = scores[i] if i < len(scores) else 0.0
                    tokens.append((clean, _normalise_confidence(conf)))
            continue

        lines = page if isinstance(page, list) else [page]
        for line in lines:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                continue
            rec = line[1]
            if not isinstance(rec, (list, tuple)) or len(rec) < 2:
                continue
            clean = _clean_ocr_text(rec[0])
            if clean:
                tokens.append((clean, _normalise_confidence(rec[1])))

    return tokens


def _ocr_read(img):
    """Run OCR on an image. Returns [(cleaned_text, confidence), ...]."""
    global OCR_AVAILABLE, PADDLE_AVAILABLE

    engine = _get_ocr()
    if engine is None:
        return []

    if engine is _paddle_ocr:
        try:
            return _read_paddleocr(img)
        except Exception as exc:
            print(f"[WARN] PaddleOCR read failed; falling back if possible: {exc}")
            PADDLE_AVAILABLE = False
            OCR_AVAILABLE = RAPID_AVAILABLE or EASY_AVAILABLE
            engine = _get_ocr()
            if engine is None or engine is _paddle_ocr:
                return []

    if engine is _rapid_ocr:
        result, _ = engine(img)
        if not result:
            return []
        sorted_result = sorted(result, key=lambda item: item[0][0][0])
        tokens = []
        for box, text, conf in sorted_result:
            clean = _clean_ocr_text(text)
            if clean:
                tokens.append((clean, float(conf)))
        return tokens

    res = engine.readtext(
        img, detail=1, paragraph=False,
        allowlist=OCR_ALLOWLIST,
        text_threshold=0.2, low_text=0.2,
    )
    return [(_clean_ocr_text(t), float(c)) for _, t, c in res if t.strip()]


# ─────────────────────────────────────────────────────────────────────────────
#  Romanian county table
# ─────────────────────────────────────────────────────────────────────────────
RO_COUNTIES = {
    "AB":"Alba",        "AR":"Arad",         "AG":"Argeș",
    "BC":"Bacău",       "BH":"Bihor",        "BN":"Bistrița-Năsăud",
    "BT":"Botoșani",    "BV":"Brașov",       "BR":"Brăila",
    "B": "București",   "BZ":"Buzău",        "CS":"Caraș-Severin",
    "CL":"Călărași",    "CJ":"Cluj",         "CT":"Constanța",
    "CV":"Covasna",     "DB":"Dâmbovița",    "DJ":"Dolj",
    "GL":"Galați",      "GR":"Giurgiu",      "GJ":"Gorj",
    "HR":"Harghita",    "HD":"Hunedoara",    "IL":"Ialomița",
    "IS":"Iași",        "IF":"Ilfov",        "MM":"Maramureș",
    "MH":"Mehedinți",   "MS":"Mureș",        "NT":"Neamț",
    "OT":"Olt",         "PH":"Prahova",      "SM":"Satu Mare",
    "SJ":"Sălaj",       "SB":"Sibiu",        "SV":"Suceava",
    "TR":"Teleorman",   "TM":"Timiș",        "TL":"Tulcea",
    "VS":"Vaslui",      "VL":"Vâlcea",       "VN":"Vrancea",
    "CD":"Corp Diplomatic", "TC":"Tribunal/Curte",
}

_RO_RE = re.compile(
    r"^(B)(\d{2,3})([A-Z]{3})$"
    r"|^([A-Z]{2})(\d{2})([A-Z]{3})$",
    re.IGNORECASE,
)
_RO_TEMP_RE = re.compile(r"^(B|[A-Z]{2})(\d{6})$", re.IGNORECASE)
_RO_STANDARD_INCOMPLETE_RE = re.compile(r"^(B\d{2,3}|[A-Z]{2}\d{2})[A-Z]{1,2}$", re.IGNORECASE)
_RO_BUCHAREST_MISSING_PREFIX_RE = re.compile(r"^\d{3}[A-Z]{3}$", re.IGNORECASE)
_RO_BUCHAREST_HINT_MISSING_PREFIX_RE = re.compile(r"^\d{2,3}[A-Z]{3}$", re.IGNORECASE)
_FR_SIV_RE = re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$", re.IGNORECASE)
_UK_CURRENT_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{3}$", re.IGNORECASE)
_UK_CURRENT_PARTIAL_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{2}$", re.IGNORECASE)
_UK_PREFIX_RE = re.compile(
    r"^[A-Z]\d{1,3}[A-Z]{3}$"
    r"|^[A-Z]{3}\d{1,3}[A-Z]$"
    r"|^[A-Z]{2}\d{1,4}$",
    re.IGNORECASE,
)
_GENERIC_PLATE_RE = re.compile(r"^[A-Z0-9]{5,10}$", re.IGNORECASE)

_D = {"O":"0","I":"1","Z":"2","S":"5","B":"8","G":"6","T":"7","Q":"0","D":"0"}
_L = {"0":"O","1":"I","8":"B","5":"S","6":"G","2":"Z"}
_UK_SUFFIX_LAST_FIX = {"I": "B", "Q": "O"}
COUNTRY_PREFIXES = {
    "FR": ("FR", "France"),
    "RO": ("RO", "Romania"),
    "GB": ("UK", "United Kingdom"),
    "UK": ("UK", "United Kingdom"),
}

def _fc(c, t):
    return (_D if t=="D" else _L).get(c.upper(), c.upper())

def _fix(raw):
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if s[:2]=="RO" and len(s)>=8: s=s[2:]
    if s and s[0]=="B" and len(s)==7:
        return "B"+"".join(_fc(s[i],"D") for i in range(1,4))+"".join(_fc(s[i],"L") for i in range(4,7))
    if s and s[0]=="B" and len(s)==6:
        interp = "B"+"".join(_fc(s[i],"D") for i in range(1,3))+"".join(_fc(s[i],"L") for i in range(3,6))
        if _RO_RE.match(interp):
            return interp
        return "B"+"".join(_fc(s[i],"D") for i in range(1,4))+"".join(_fc(s[i],"L") for i in range(4,6))
    if s and s[0]=="B" and len(s)==5:
        return "B"+"".join(_fc(s[i],"D") for i in range(1,3))+"".join(_fc(s[i],"L") for i in range(3,5))
    if len(s)==7:
        county2=s[:2].upper()
        county2_letters=all(c.isalpha() for c in county2)
        if county2_letters and county2 in RO_COUNTIES and county2!="B":
            return "".join(_fc(s[i],"L") for i in range(2))+"".join(_fc(s[i],"D") for i in range(2,4))+"".join(_fc(s[i],"L") for i in range(4,7))
        return "".join(_fc(s[i],"L") for i in range(2))+"".join(_fc(s[i],"D") for i in range(2,4))+"".join(_fc(s[i],"L") for i in range(4,7))
    if len(s)==6:
        c2=s[:2].upper()
        if all(c.isalpha() for c in c2) and c2 in RO_COUNTIES and c2!="B":
            return c2+"".join(_fc(s[i],"D") for i in range(2,4))+"".join(_fc(s[i],"L") for i in range(4,6))
    return s


class RomanianPlate:
    country_code = "RO"
    country_name = "Romania"
    plate_type = "standard"

    def __init__(self, code, digits, letters):
        self.county_code = code.upper()
        self.digits      = digits
        self.letters     = letters.upper()
        self.county_name = RO_COUNTIES.get(self.county_code, "Unknown")
    @property
    def full(self):    return f"{self.county_code} {self.digits} {self.letters}"
    @property
    def compact(self): return f"{self.county_code}{self.digits}{self.letters}"


class RomanianTemporaryPlate:
    country_code = "RO"
    country_name = "Romania"
    plate_type = "temporary"

    def __init__(self, code, digits):
        self.county_code = code.upper()
        self.digits = digits
        self.letters = ""
        self.county_name = RO_COUNTIES.get(self.county_code, "Unknown")

    @property
    def full(self): return f"{self.county_code} {self.digits}"
    @property
    def compact(self): return f"{self.county_code}{self.digits}"


class ForeignPlate:
    def __init__(self, compact, country_code="INT", country_name="Foreign plate", full=None):
        self._compact = compact.upper()
        self._full = full or self._compact
        self.country_code = country_code
        self.country_name = country_name
        self.county_code = country_code
        self.county_name = country_name
        self.digits = "".join(ch for ch in self._compact if ch.isdigit())
        self.letters = "".join(ch for ch in self._compact if ch.isalpha())

    @property
    def full(self): return self._full
    @property
    def compact(self): return self._compact


def _clean_plate_text(raw):
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def _split_country_prefix(raw):
    clean = _clean_plate_text(raw)
    if len(clean) < 7:
        return None, clean

    if len(clean) == 8 and _fc(clean[0], "L") == "F" and _FR_SIV_RE.match(_fix_fr_siv(clean[1:])):
        return "FR", clean[1:]

    prefix = "".join(_fc(c, "L") for c in clean[:2])
    country = COUNTRY_PREFIXES.get(prefix)
    if country and len(clean[2:]) >= 5:
        return country[0], clean[2:]
    return None, clean


def _fix_ro_body(raw):
    body = _clean_plate_text(raw)
    if not body:
        return ""

    first = _fc(body[0], "L")
    county_candidate = ""
    if len(body) >= 2:
        county_candidate = first + _fc(body[1], "L")

    if first == "B" and len(body) == 7 and body[1].isdigit():
        return (
            "B"
            + "".join(_fc(c, "D") for c in body[1:4])
            + "".join(_fc(c, "L") for c in body[4:7])
        )

    if len(body) == 7 and county_candidate in RO_COUNTIES and county_candidate != "B":
        return (
            county_candidate
            + "".join(_fc(c, "D") for c in body[2:4])
            + "".join(_fc(c, "L") for c in body[4:7])
        )

    if first == "B" and len(body) == 7:
        return (
            "B"
            + "".join(_fc(c, "D") for c in body[1:4])
            + "".join(_fc(c, "L") for c in body[4:7])
        )

    if first == "B" and len(body) == 6:
        interp_2d = (
            "B"
            + "".join(_fc(c, "D") for c in body[1:3])
            + "".join(_fc(c, "L") for c in body[3:6])
        )
        if _RO_RE.match(interp_2d):
            return interp_2d
        return (
            "B"
            + "".join(_fc(c, "D") for c in body[1:4])
            + "".join(_fc(c, "L") for c in body[4:6])
        )

    if len(body) == 7:
        return (
            "".join(_fc(c, "L") for c in body[:2])
            + "".join(_fc(c, "D") for c in body[2:4])
            + "".join(_fc(c, "L") for c in body[4:7])
        )
    return body


def _parse_ro_plate(raw, allow_temporary=False):
    fixed = _fix_ro_body(raw)

    m = _RO_RE.match(fixed)
    if m:
        code, digits, letters = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
        if code.upper() in RO_COUNTIES:
            return RomanianPlate(code, digits, letters)

    if allow_temporary:
        temp_plate = _parse_ro_temporary_plate(raw)
        if temp_plate:
            return temp_plate

    return None


def _parse_ro_missing_bucharest_prefix(raw, allow_two_digits=False):
    body = _clean_plate_text(raw)
    if allow_two_digits:
        match = _RO_BUCHAREST_HINT_MISSING_PREFIX_RE.match(body)
    else:
        match = _RO_BUCHAREST_MISSING_PREFIX_RE.match(body)
    if not match:
        return None

    digits_len = len(body) - 3
    digits = "".join(_fc(c, "D") for c in body[:digits_len])
    letters = "".join(_fc(c, "L") for c in body[digits_len:])
    if not digits.isdigit() or not letters.isalpha():
        return None
    return RomanianPlate("B", digits, letters)


def _parse_ro_temporary_plate(raw):
    body = _clean_plate_text(raw)
    if not body:
        return None

    if _fc(body[0], "L") == "B" and len(body) == 7:
        code = "B"
        digits = "".join(_fc(c, "D") for c in body[1:7])
    elif len(body) == 8:
        code = "".join(_fc(c, "L") for c in body[:2])
        digits = "".join(_fc(c, "D") for c in body[2:8])
    else:
        return None

    compact = f"{code}{digits}"
    if code in RO_COUNTIES and _RO_TEMP_RE.match(compact):
        return RomanianTemporaryPlate(code, digits)
    return None


def _fix_fr_siv(raw):
    body = _clean_plate_text(raw)
    if len(body) != 7:
        return body
    return (
        "".join(_fc(c, "L") for c in body[:2])
        + "".join(_fc(c, "D") for c in body[2:5])
        + "".join(_fc(c, "L") for c in body[5:7])
    )


def _clean_fr_siv_text(raw):
    clean = _clean_plate_text(raw)
    if clean.startswith("FR") and len(clean) == 9:
        return clean[2:]
    if len(clean) == 8 and _fc(clean[0], "L") == "F":
        return clean[1:]
    return clean


def _parse_fr_plate(raw, allow_corrections=False):
    clean = _clean_fr_siv_text(raw)
    fixed = _fix_fr_siv(clean) if allow_corrections else clean
    if not _FR_SIV_RE.match(fixed):
        return None
    return ForeignPlate(
        fixed,
        country_code="FR",
        country_name="France",
        full=f"{fixed[:2]} {fixed[2:5]} {fixed[5:]}",
    )


def _is_exact_fr_siv(raw):
    return bool(_FR_SIV_RE.match(_clean_fr_siv_text(raw)))


def _looks_like_incomplete_ro_standard(raw):
    fixed = _fix_ro_body(raw)
    if not _RO_STANDARD_INCOMPLETE_RE.match(fixed):
        return False

    if fixed.startswith("B"):
        return True

    return fixed[:2] in RO_COUNTIES


def _fix_uk_current(raw):
    fixed = _fix(raw)
    if not _UK_CURRENT_RE.match(fixed):
        return fixed

    suffix = fixed[4:]
    suffix = suffix[:2] + _UK_SUFFIX_LAST_FIX.get(suffix[2], suffix[2])
    return fixed[:4] + suffix


def _is_exact_uk_current(raw):
    return bool(_UK_CURRENT_RE.match(_clean_plate_text(raw)))


def _parse_uk_plate(raw, allow_corrections=True, prefer_exact_fr=True):
    clean = _clean_plate_text(raw)

    if _UK_CURRENT_RE.match(clean):
        uk_text = _fix_uk_current(clean)
        return ForeignPlate(
            uk_text,
            country_code="UK",
            country_name="United Kingdom",
            full=f"{uk_text[:4]} {uk_text[4:]}",
        )

    fixed = _fix_uk_current(raw) if allow_corrections else clean
    if prefer_exact_fr and _is_exact_fr_siv(clean):
        fixed = clean
    uk_text = fixed if _UK_CURRENT_RE.match(fixed) else clean
    if _UK_CURRENT_RE.match(uk_text):
        return ForeignPlate(
            uk_text,
            country_code="UK",
            country_name="United Kingdom",
            full=f"{uk_text[:4]} {uk_text[4:]}",
        )
    if _UK_CURRENT_PARTIAL_RE.match(clean):
        return ForeignPlate(
            clean,
            country_code="UK",
            country_name="United Kingdom",
            full=f"{clean[:4]} {clean[4:]}",
        )
    if _UK_PREFIX_RE.match(clean):
        return ForeignPlate(clean, country_code="UK", country_name="United Kingdom")
    return None


def _is_plausible_generic_plate(text):
    if not _GENERIC_PLATE_RE.match(text):
        return False
    return any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)


def _is_unambiguous_uk_current_plate(text):
    if _is_exact_fr_siv(text):
        return False
    fixed = _fix_uk_current(text)
    return bool(_UK_CURRENT_RE.match(fixed) and fixed[:2] not in RO_COUNTIES)


def parse_plate(text, allow_ro_temporary=False, country_hint=None):
    clean = _clean_plate_text(text)
    country_code, body = _split_country_prefix(text)

    if country_code == "RO":
        return _parse_ro_plate(body, allow_temporary=allow_ro_temporary)
    if country_code == "FR":
        plate = _parse_fr_plate(body, allow_corrections=True)
        if plate:
            return plate
        return _parse_fr_plate(clean, allow_corrections=True)
    if country_code == "UK":
        plate = _parse_uk_plate(body, allow_corrections=True, prefer_exact_fr=False)
        if plate:
            return plate
        return _parse_uk_plate(clean, allow_corrections=True, prefer_exact_fr=False)

    if country_hint == "FR":
        plate = _parse_fr_plate(body, allow_corrections=True)
        if plate:
            return plate
        fixed = _fix(body)
        if _is_plausible_generic_plate(fixed):
            return ForeignPlate(fixed)
        return None

    if country_hint == "UK":
        plate = _parse_uk_plate(body, allow_corrections=True, prefer_exact_fr=False)
        if plate:
            return plate
        fixed = _fix(body)
        if _is_plausible_generic_plate(fixed):
            return ForeignPlate(fixed)
        return None

    if country_hint == "RO":
        plate = _parse_ro_plate(body, allow_temporary=allow_ro_temporary)
        if plate:
            return plate
        plate = _parse_ro_missing_bucharest_prefix(body, allow_two_digits=True)
        if plate:
            return plate
        if _looks_like_incomplete_ro_standard(body):
            return None
        fixed = _fix(body)
        if _is_plausible_generic_plate(fixed):
            return ForeignPlate(fixed)
        return None

    plate = _parse_ro_plate(body, allow_temporary=allow_ro_temporary)
    if plate:
        return plate

    plate = _parse_ro_missing_bucharest_prefix(body)
    if plate:
        return plate

    if _looks_like_incomplete_ro_standard(body):
        return None

    plate = _parse_uk_plate(body, allow_corrections=True, prefer_exact_fr=True)
    if plate:
        return plate

    plate = _parse_fr_plate(body)
    if plate:
        return plate

    plate = _parse_ro_temporary_plate(body)
    if plate:
        return plate

    fixed = _fix(body)
    generic_text = fixed if _is_plausible_generic_plate(fixed) else body
    if _is_plausible_generic_plate(generic_text):
        return ForeignPlate(generic_text)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Multi-pass OCR
# ─────────────────────────────────────────────────────────────────────────────
def _fast_variants(gray):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    eq    = clahe.apply(gray)
    _, ot = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    kern  = np.ones((2,2), np.uint8)
    er    = cv2.erode(gray, kern, iterations=1)

    h, w = gray.shape
    right = gray[:, w // 3:]
    right_scaled = cv2.resize(right, (w, h), interpolation=cv2.INTER_CUBIC)
    _, ot_r = cv2.threshold(right_scaled, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)

    return [
        ("otsu",      ot),
        ("inv_clahe", cv2.bitwise_not(eq)),
        ("erode",     er),
        ("right_otsu", ot_r),
    ]


def _balanced_variants(gray):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    eq    = clahe.apply(gray)
    _, ot = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    ad    = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,10)
    kern  = np.ones((2,2), np.uint8)
    er    = cv2.erode(gray, kern, iterations=1)

    return [
        ("otsu",       ot),
        ("inv_otsu",   cv2.bitwise_not(ot)),
        ("clahe",      eq),
        ("inv_clahe",  cv2.bitwise_not(eq)),
        ("adapt",      ad),
        ("inv_adapt",  cv2.bitwise_not(ad)),
        ("erode",      er),
    ]


def _accurate_variants(gray):
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    eq    = clahe.apply(gray)
    _, ot = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)

    return [
        ("gray",  gray),
        ("clahe", eq),
        ("otsu",  ot),
        ("inv",   cv2.bitwise_not(ot)),
    ]


def _line_ocr_crop(crop):
    """Trim the EU strip before recognition while preserving character height."""
    if crop is None or crop.size == 0:
        return crop

    h, w = crop.shape[:2]
    y2 = h
    x1 = 0
    x2 = w

    left_w = max(1, int(w * 0.25))
    probe = crop[:max(1, y2), :left_w]
    b, g, r = cv2.split(probe)
    blue_score = b.astype(np.int16) - np.maximum(g, r).astype(np.int16)
    blue_cols = np.where((blue_score.mean(axis=0) > 25) & (b.mean(axis=0) > 80))[0]
    if blue_cols.size:
        x1 = min(int(w * 0.14), max(int(w * 0.04), int(blue_cols.max()) + 2))

    if x2 <= x1:
        return crop
    result = crop[:max(1, y2), x1:x2]
    if result.size > 0:
        rp = max(30, int(result.shape[1] * 0.18))
        result = cv2.copyMakeBorder(result, 0, 0, 0, rp, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return result


def _looks_like_red_plate(crop):
    if crop is None or crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red_low = cv2.inRange(hsv, np.array([0, 45, 40]), np.array([12, 255, 255]))
    red_high = cv2.inRange(hsv, np.array([165, 45, 40]), np.array([179, 255, 255]))
    red_mask = cv2.bitwise_or(red_low, red_high)

    red_pixels = int(cv2.countNonZero(red_mask))
    red_ratio = red_pixels / max(1, crop.shape[0] * crop.shape[1])
    return red_pixels >= 40 and red_ratio >= 0.012


def _detect_left_strip(crop):
    if crop is None or crop.size == 0:
        return None, False

    h, w = crop.shape[:2]
    strip_w = max(1, int(w * 0.18))
    left_strip = crop[:, :strip_w]

    hsv = cv2.cvtColor(left_strip, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, np.array([95, 80, 60]), np.array([130, 255, 255]))
    blue_pixels = int(cv2.countNonZero(blue_mask))
    total_pixels = max(1, left_strip.shape[0] * left_strip.shape[1])
    blue_ratio = blue_pixels / total_pixels

    if blue_pixels < 50 or blue_ratio < 0.15:
        return None, False

    if OCR_AVAILABLE:
        try:
            strip_h = left_strip.shape[0]
            text_region = left_strip[int(strip_h * 0.5):, :]
            gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
            sc = max(4.0, 80.0 / max(gray.shape[0], 1))
            resized = cv2.resize(
                gray, (int(gray.shape[1] * sc), int(gray.shape[0] * sc)),
                interpolation=cv2.INTER_CUBIC,
            )
            _, binary = cv2.threshold(
                resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            for img in [binary, cv2.bitwise_not(binary)]:
                for text, conf in _ocr_read(img):
                    clean = re.sub(r"[^A-Z]", "", text.upper())
                    if "RO" in clean and conf > 0.05:
                        return "RO", True
                    if ("FR" in clean or clean == "F") and conf > 0.05:
                        return "FR", True
                    if ("GB" in clean or "UK" in clean) and conf > 0.05:
                        return "UK", True
        except Exception:
            pass

    return "EU", True


def _looks_like_green_plate(crop):
    if crop is None or crop.size == 0:
        return False

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35, 45, 40]), np.array([85, 255, 255]))

    green_pixels = int(cv2.countNonZero(green_mask))
    green_ratio = green_pixels / max(1, crop.shape[0] * crop.shape[1])
    return green_pixels >= 40 and green_ratio >= 0.012


def _make_variants(crop, variant_fn):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    sc = max(4.0, 120.0 / max(h, 1))
    gray = cv2.resize(gray, (int(w*sc), int(h*sc)), interpolation=cv2.INTER_CUBIC)
    return variant_fn(gray)


def _color_variants(crop):
    if crop is None or crop.size == 0:
        return []

    prepared = _prepare_paddle_image(crop)
    h, w = prepared.shape[:2]
    sc = max(1.0, 120.0 / max(h, 1))
    scaled = cv2.resize(prepared, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_CUBIC)
    x_pad = max(20, int(w * 0.25))
    x_safe_pad = max(35, int(w * 0.45))
    y_pad = max(8, int(h * 0.18))
    padded = cv2.copyMakeBorder(
        prepared, 0, y_pad, 0, x_pad, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    safe_padded = cv2.copyMakeBorder(
        prepared, 0, y_pad, 0, x_safe_pad, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    bottom_padded = cv2.copyMakeBorder(
        prepared, 0, y_pad, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )

    variants = [("color", prepared)]
    variants.append(("color_bpad", bottom_padded))
    variants.append(("color_rpad", padded))
    variants.append(("color_xrpad", safe_padded))
    if scaled.shape[:2] != prepared.shape[:2]:
        variants.append(("color_up", scaled))
        scaled_x_pad = max(40, int(scaled.shape[1] * 0.25))
        scaled_x_safe_pad = max(70, int(scaled.shape[1] * 0.45))
        scaled_y_pad = max(20, int(scaled.shape[0] * 0.18))
        variants.append(
            (
                "color_up_bpad",
                cv2.copyMakeBorder(
                    scaled,
                    0,
                    scaled_y_pad,
                    0,
                    0,
                    cv2.BORDER_CONSTANT,
                    value=(255, 255, 255),
                ),
            )
        )
        variants.append(
            (
                "color_up_rpad",
                cv2.copyMakeBorder(
                    scaled,
                    0,
                    scaled_y_pad,
                    0,
                    scaled_x_pad,
                    cv2.BORDER_CONSTANT,
                    value=(255, 255, 255),
                ),
            )
        )
        variants.append(
            (
                "color_up_xrpad",
                cv2.copyMakeBorder(
                    scaled,
                    0,
                    scaled_y_pad,
                    0,
                    scaled_x_safe_pad,
                    cv2.BORDER_CONSTANT,
                    value=(255, 255, 255),
                ),
            )
        )
    return variants


def _collect_ocr_candidates(variants):
    candidates = []
    for name, img in variants:
        print(f"           OCR pass: {name}...", end="", flush=True)
        tokens = _ocr_read(img)
        if not tokens:
            print(" no text")
            continue
        print(f" {len(tokens)} token(s)")

        merged = "".join(t for t, _ in tokens)
        avg_c = sum(c for _, c in tokens) / len(tokens)
        candidates.append((merged, avg_c, name))

        for t, c in tokens:
            candidates.append((t, c, name + "-tok"))

    return candidates


def read_plate(crop, debug_dir=None, debug_idx=""):
    """OCR the crop using CRAFT detector + recognition.
    Returns (raw_best_string, plate object|None)."""
    if not OCR_AVAILABLE or crop is None or crop.size == 0:
        return "", None

    if _get_ocr() is None:
        return "", None

    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, f"{debug_idx}_orig.jpg"), crop)

    country_hint, _has_blue_band = _detect_left_strip(crop)
    _is_electric = _looks_like_green_plate(crop)

    print(f"         [visual] country_hint={country_hint!r}  blue_band={_has_blue_band}  electric={_is_electric}")

    line_crop = _line_ocr_crop(crop)
    allow_ro_temporary = _looks_like_red_plate(line_crop)

    variants = _color_variants(crop) + _color_variants(line_crop) + _make_variants(line_crop, _accurate_variants)
    candidates = _collect_ocr_candidates(variants)
    best_unparsed = ""
    if not candidates:
        print("         [accurate] no text found")
        return best_unparsed, None

    best_text, voted = _choose_best_text(
        candidates,
        allow_ro_temporary=allow_ro_temporary,
        country_hint=country_hint,
    )
    best_unparsed = voted or best_text or best_unparsed
    plate = parse_plate(best_text, allow_ro_temporary=allow_ro_temporary, country_hint=country_hint)
    voted_plate = parse_plate(voted, allow_ro_temporary=allow_ro_temporary, country_hint=country_hint) if voted else None

    if voted_plate and not plate:
        best_text = voted
        plate = voted_plate

    if not plate:
        for item in sorted(
            candidates,
            key=lambda item: _score_candidate(
                item,
                allow_ro_temporary=allow_ro_temporary,
                country_hint=country_hint,
            ),
            reverse=True,
        ):
            candidate_text = item[0]
            candidate_plate = parse_plate(candidate_text, allow_ro_temporary=allow_ro_temporary, country_hint=country_hint)
            if candidate_plate:
                best_text = candidate_text
                plate = candidate_plate
                print(f"         [accurate] rescued plate from candidate: {candidate_text} (src={item[2]}, conf={item[1]:.2f})")
                break

    _print_candidates(
        candidates,
        best_text,
        voted,
        allow_ro_temporary=allow_ro_temporary,
        country_hint=country_hint,
    )

    if plate:
        if _is_electric and isinstance(plate, RomanianPlate):
            plate.plate_type = "electric"
        return best_text, plate

    return best_unparsed, None


def _score_candidate(item, allow_ro_temporary=False, country_hint=None):
    text, conf, _ = item
    plate = parse_plate(
        text,
        allow_ro_temporary=allow_ro_temporary,
        country_hint=country_hint,
    )
    if not plate:
        return conf
    country_code = getattr(plate, "country_code", "")
    if country_code == "RO":
        return conf + 0.9
    if country_code == "FR":
        if country_hint == "FR":
            return conf + (1.1 if _is_exact_fr_siv(text) else 0.95)
        return conf + (0.92 if _is_exact_fr_siv(text) else 0.86)
    if country_code == "UK":
        fixed = _fix_uk_current(text)
        if _UK_CURRENT_RE.match(fixed):
            return conf + 0.85
        if _UK_CURRENT_PARTIAL_RE.match(fixed):
            return conf + 0.35
        if len(fixed) <= 4:
            return conf - 0.2
        return conf + 0.2
    return conf + 0.3


def _choose_best_text(candidates, allow_ro_temporary=False, country_hint=None):
    def parse_candidate(text):
        return parse_plate(
            text,
            allow_ro_temporary=allow_ro_temporary,
            country_hint=country_hint,
        )

    def score_candidate(item):
        return _score_candidate(
            item,
            allow_ro_temporary=allow_ro_temporary,
            country_hint=country_hint,
        )

    non_uk_country_candidates = [
        item for item in candidates
        if getattr(parse_candidate(item[0]), "country_code", None) in {"RO", "FR"}
    ]
    full_uk_candidates = [
        item for item in candidates if _is_unambiguous_uk_current_plate(item[0])
    ]
    if full_uk_candidates and not non_uk_country_candidates:
        best_full_uk = max(full_uk_candidates, key=score_candidate)
        return _fix_uk_current(best_full_uk[0]), None

    best_text, best_conf, best_src = max(candidates, key=score_candidate)

    voted = _char_vote(
        candidates,
        allow_ro_temporary=allow_ro_temporary,
        country_hint=country_hint,
    )
    if voted:
        vote_parsed = parse_candidate(voted)
        best_parsed = parse_candidate(best_text)
        if vote_parsed and not best_parsed:
            best_text = voted
        elif vote_parsed and best_parsed:
            vote_country = getattr(vote_parsed, "country_code", None)
            best_country = getattr(best_parsed, "country_code", None)
            if vote_country in {"RO", "FR"} and best_country not in {"RO", "FR"}:
                best_text = voted
            elif not (best_country in {"RO", "FR"} and vote_country not in {"RO", "FR"}):
                vote_score = sum(
                    score_candidate(item)
                    for item in candidates
                    if _vote_text(item[0], country_hint=country_hint) == voted
                )
                best_score = sum(
                    score_candidate(item)
                    for item in candidates
                    if _vote_text(item[0], country_hint=country_hint)
                    == _vote_text(best_text, country_hint=country_hint)
                )
                if vote_score > best_score:
                    best_text = voted

    return best_text, voted


def _print_candidates(candidates, best_text, voted, allow_ro_temporary=False, country_hint=None):
    print(f"         OCR candidates (showing top 5):")
    for item in sorted(
        candidates,
        key=lambda item: _score_candidate(
            item,
            allow_ro_temporary=allow_ro_temporary,
            country_hint=country_hint,
        ),
        reverse=True,
    )[:5]:
        t, c, src = item
        marker = "*" if t==best_text else " "
        print(
            f"         {marker} [{src:<12}] {t!r:<12} "
            f"conf={c:.2f}  fixed={_vote_text(t, country_hint=country_hint)!r}"
        )
    if voted:
        print(f"         Vote result: {voted}")


def _parsed_candidate_scores(candidates):
    scores = {}
    for item in candidates:
        plate = parse_plate(item[0])
        if plate:
            scores[plate.compact] = max(scores.get(plate.compact, 0.0), _score_candidate(item))
    return scores


def _vote_text(text, country_hint=None):
    if country_hint == "FR" or _parse_fr_plate(text):
        return _fix_fr_siv(text)
    return _fix(text)


def _char_vote(candidates, allow_ro_temporary=False, country_hint=None):
    from collections import Counter
    by_len = {}
    for text, conf, src in candidates:
        fixed = _vote_text(text, country_hint=country_hint)
        by_len.setdefault(len(fixed), []).append((fixed, conf))
    for length in sorted(by_len, key=lambda l: -len(by_len[l])):
        group = by_len[length]
        if len(group) < 3:
            continue
        result = []
        for i in range(length):
            counter = Counter()
            for t, c in group:
                counter[t[i]] += c
            result.append(counter.most_common(1)[0][0])
        voted = "".join(result)
        if parse_plate(
            voted,
            allow_ro_temporary=allow_ro_temporary,
            country_hint=country_hint,
        ):
            return voted
    return None



# ─────────────────────────────────────────────────────────────────────────────
#  Drawing
# ─────────────────────────────────────────────────────────────────────────────
def draw(frame, box, conf, plate, raw):
    x1,y1,x2,y2 = map(int, box)
    color = (0,220,0) if plate else (0,165,255)
    cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)

    top = f"{plate.full}  {conf:.0%}" if plate else f"? {raw}  {conf:.0%}" if raw else f"Plate {conf:.0%}"
    (lw,lh),bl = cv2.getTextSize(top,cv2.FONT_HERSHEY_SIMPLEX,0.65,2)
    cv2.rectangle(frame,(x1,y1-lh-bl-8),(x1+lw+6,y1),color,-1)
    cv2.putText(frame,top,(x1+3,y1-bl-2),cv2.FONT_HERSHEY_SIMPLEX,0.65,(0,0,0),2)

    if plate:
        bot = plate.county_name
        (bw,bh),bbl = cv2.getTextSize(bot,cv2.FONT_HERSHEY_SIMPLEX,0.5,1)
        cv2.rectangle(frame,(x1,y2),(x1+bw+6,y2+bh+bbl+6),color,-1)
        cv2.putText(frame,bot,(x1+3,y2+bh+2),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,0),1)
    return frame


# ─────────────────────────────────────────────────────────────────────────────
#  Safe imshow
# ─────────────────────────────────────────────────────────────────────────────
_gui = None

def safe_show(title, frame):
    global _gui
    if _gui is False: return -1
    try:
        cv2.imshow(title, frame)
        _gui = True
        return cv2.waitKey(1) & 0xFF
    except Exception:
        if _gui is None:
            print("[WARN] cv2.imshow unavailable — run: pip install opencv-python")
        _gui = False
        return -1


# ─────────────────────────────────────────────────────────────────────────────
#  CSV — always create with header on first call
# ─────────────────────────────────────────────────────────────────────────────
CSV_FIELDS = ["timestamp","plate_full","plate_compact","county_code",
              "county_name","digits","letters","confidence","frame","source","raw_ocr"]

def init_csv(path):
    """Create the CSV file with headers immediately (even if no plates found yet)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()

def append_csv(path, row):
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(row)


# ─────────────────────────────────────────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────────────────────────────────────────
def detect(model_path, source, conf_thr=0.4,
           save_crops=False, save_video=False, save_log=True,
           show=True, output_dir="output"):

    print(f"[INFO] Loading model: {model_path}")
    model = YOLO(model_path)
    print(f"[INFO] Classes: {model.names}")

    if OCR_AVAILABLE:
        _get_ocr()

    is_webcam = str(source).isdigit()
    cap = cv2.VideoCapture(int(source) if is_webcam else source)
    if not cap.isOpened():
        sys.exit(f"[ERROR] Cannot open: {source}")

    W  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps= cap.get(cv2.CAP_PROP_FPS) or 30.0
    is_img = (not is_webcam and
              Path(str(source)).suffix.lower() in {".jpg",".jpeg",".png",".bmp",".webp"})

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    writer = None
    if save_video and not is_img:
        vp = os.path.join(output_dir, f"detected_{ts}.mp4")
        writer = cv2.VideoWriter(vp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W,H))
        print(f"[INFO] Video → {vp}")

    csv_path = None
    if save_log:
        csv_path = os.path.join(output_dir, f"plates_{ts}.csv")
        init_csv(csv_path)
        print(f"[INFO] Log  → {csv_path}  (created with headers)")

    seen      = {}   # compact → RomanianPlate
    frame_num = total_dets = total_parsed = 0

    print("[INFO] Press  Q  to quit.")
    print("=" * 60)

    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_num += 1

        results = model(frame, conf=conf_thr, verbose=False)[0]
        fp = 0

        for i, box in enumerate(results.boxes):
            conf = float(box.conf[0])
            xyxy = box.xyxy[0].tolist()
            x1,y1,x2,y2 = map(int, xyxy)

            # ── Padded crop (avoids cutting edge chars) ───────────────────────
            px = max(18, int((x2-x1)*0.20))
            py = max(10, int((y2-y1)*0.22))
            cx1,cy1 = max(0,x1-px), max(0,y1-py)
            cx2,cy2 = min(W,x2+px), min(H,y2+py)
            crop = frame[cy1:cy2, cx1:cx2]

            ddir = os.path.join(output_dir,"debug") if save_crops else None
            raw, plate = read_plate(crop, debug_dir=ddir, debug_idx=f"f{frame_num:05d}_{i}")
            frame = draw(frame, xyxy, conf, plate, raw)

            if plate:
                print(f"  Frame {frame_num:>5} | #{i+1} | conf={conf:.2f} | "
                      f"✓ {plate.full:<12}  ({plate.county_name})")
                total_parsed += 1
            else:
                print(f"  Frame {frame_num:>5} | #{i+1} | conf={conf:.2f} | "
                      f"✗ unmatched OCR: {raw!r}  (fixed: {_fix(raw)!r})")

            if save_crops and crop.size > 0:
                label = plate.compact if plate else (raw or "unknown")
                cp = os.path.join(output_dir,"crops",f"{label}_f{frame_num:05d}_{i}.jpg")
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                cv2.imwrite(cp, crop)

            if csv_path:
                row = {
                    "timestamp":     datetime.now().isoformat(timespec="seconds"),
                    "plate_full":    plate.full    if plate else "",
                    "plate_compact": plate.compact if plate else "",
                    "county_code":   plate.county_code if plate else "",
                    "county_name":   plate.county_name if plate else "",
                    "digits":        plate.digits  if plate else "",
                    "letters":       plate.letters if plate else "",
                    "confidence":    f"{conf:.3f}",
                    "frame":         frame_num,
                    "source":        source,
                    "raw_ocr":       raw,
                }
                # Write every detection (parsed or not); deduplicate parsed ones
                if plate:
                    if plate.compact not in seen:
                        seen[plate.compact] = plate
                        append_csv(csv_path, row)
                else:
                    append_csv(csv_path, row)   # always log failed reads too

            fp += 1; total_dets += 1

        cv2.putText(frame, f"Frame {frame_num}  |  Plates: {fp}",
                    (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255,255,0), 2)

        if writer: writer.write(frame)

        if is_img:
            out = os.path.join(output_dir, f"{Path(str(source)).stem}_detected.jpg")
            cv2.imwrite(out, frame)
            print(f"[INFO] Saved → {out}")

        if show:
            key = safe_show("Romanian Plate Detector", frame)
            if _gui and is_img: cv2.waitKey(0)
            elif key == ord("q"): break

        if is_img: break

    cap.release()
    if writer: writer.release()
    cv2.destroyAllWindows()

    print("=" * 60)
    print(f"[DONE] Frames   : {frame_num}")
    print(f"       Detected : {total_dets}")
    print(f"       Parsed   : {total_parsed}")
    if seen:
        print(f"       Unique plates ({len(seen)}):")
        for pl in sorted(seen.values(), key=lambda p: p.compact):
            print(f"         {pl.full}  —  {pl.county_name}")
    if csv_path:
        print(f"       CSV → {csv_path}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _img_exts   = {".jpg",".jpeg",".png",".bmp",".webp"}

    _default_model  = os.path.join(_script_dir, "best.pt")
    _default_source = None
    for f in sorted(os.listdir(_script_dir)):
        if Path(f).suffix.lower() in _img_exts:
            _default_source = os.path.join(_script_dir, f)
            break
    if _default_source is None:
        _default_source = "0"

    p = argparse.ArgumentParser(description="Romanian plate detector — YOLOv8 + EasyOCR")
    p.add_argument("--model",      default=_default_model)
    p.add_argument("--source",     default=_default_source)
    p.add_argument("--conf",       type=float, default=0.4)
    p.add_argument("--save-crops", action="store_true")
    p.add_argument("--save-video", action="store_true")
    p.add_argument("--no-log",     action="store_true")
    p.add_argument("--no-show",    action="store_true")
    p.add_argument("--output-dir", default=os.path.join(_script_dir, "output"))
    a = p.parse_args()
    detect(a.model, a.source, a.conf, a.save_crops, a.save_video,
           not a.no_log, not a.no_show, a.output_dir)
