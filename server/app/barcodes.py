import io
import logging
import math
import re
from dataclasses import dataclass

from PIL import Image

from .schema import ExtractedForm, FieldStatus, FieldValue

log = logging.getLogger("medextract")

# חתימת המדבקה המרכזית של המעבדה (נמדד על 19 עמודים, 21/10/2026): Code 128, 6 ספרות,
# ורוחב של כ-8% מהצלע הקצרה של הדף (196–218 פיקסלים ב-300 DPI). ברקודים אחרים רחבים יותר.
CENTRAL_FORMAT = "Code128"
CENTRAL_DIGITS = 6
CENTRAL_WIDTH_SHARE = (0.07, 0.095)
MAX_DIGIT_FIX = 2  # החלפה לפי ברקוד רק כשההבדל קטן: אותו מספר שנקרא עם טעות בספרות


@dataclass(frozen=True)
class Barcode:
    """ברקוד שנקרא בעמוד: הטקסט, הסוג, הרוחב ביחס לצלע הקצרה, והמיקום [x0, y0, x1, y1] ביחס לדף."""
    text: str
    kind: str
    width_share: float
    box: tuple[float, float, float, float] | None = None

    @property
    def is_central(self) -> bool:
        """האם זו המדבקה המרכזית של המעבדה (לפי סוג, מספר ספרות ורוחב)."""
        low, high = CENTRAL_WIDTH_SHARE
        return (self.kind == CENTRAL_FORMAT and self.text.isdigit() and len(self.text) == CENTRAL_DIGITS
                and low <= self.width_share <= high)


UPSCALE = 1.5  # ניסיון שני על תמונה מוגדלת, כשמדבקה מרכזית לא נקראה ברזולוציה הרגילה


def _scan(img: Image.Image, found: dict[str, Barcode]) -> None:
    """מוסיפה את הברקודים שנקראו בתמונה (רוחב ביחס לצלע הקצרה, כך שלא תלוי ברזולוציה)."""
    import zxingcpp
    side = min(img.size)
    for b in zxingcpp.read_barcodes(img):
        p = b.position
        width = math.dist((p.top_left.x, p.top_left.y), (p.top_right.x, p.top_right.y))
        kind = str(b.format).split(".")[-1].replace(" ", "")
        xs = [c.x for c in (p.top_left, p.top_right, p.bottom_left, p.bottom_right)]
        ys = [c.y for c in (p.top_left, p.top_right, p.bottom_left, p.bottom_right)]
        box = (round(min(xs) / img.width, 4), round(min(ys) / img.height, 4),
               round(max(xs) / img.width, 4), round(max(ys) / img.height, 4))
        found.setdefault(b.text.strip(), Barcode(b.text.strip(), kind, width / side, box))


def read_barcodes(image: bytes) -> list[Barcode]:
    """קוראת את כל הברקודים בתמונת העמוד, בזיכרון בלבד. כשל בקריאה מחזיר רשימה ריקה."""
    try:
        img = Image.open(io.BytesIO(image))
        found: dict[str, Barcode] = {}
        _scan(img, found)
        if not any(b.is_central for b in found.values()):
            _scan(img.resize((round(img.width * UPSCALE), round(img.height * UPSCALE))), found)
        return list(found.values())
    except Exception as e:
        log.warning("barcode read failed (%s)", type(e).__name__)
        return []


FAR = 99


def _digits_apart(a: str, b: str) -> int:
    """כמה ספרות שונות בין שני מספרים באותו אורך (FAR אם האורך שונה)."""
    return sum(x != y for x, y in zip(a, b)) if len(a) == len(b) else FAR


def _verified(fv: FieldValue) -> None:
    """הספרות אומתו מול ברקוד: השדה תקין."""
    fv.status, fv.review_reason = FieldStatus.ok, None


def _taken_from_barcode(fv: FieldValue, code: str) -> None:
    """הספרות שנקראו שונות מהברקוד באותה מדבקה: הערך נלקח מהברקוד, ומסומן לבדיקה."""
    read = fv.value
    fv.value, fv.status = code, FieldStatus.review
    fv.review_reason = f"נלקח מהברקוד; המודל קרא {read}"


def _flag(fv: FieldValue, reason: str) -> None:
    """מוסיפה סיבת בדיקה לשדה."""
    fv.status = FieldStatus.review
    fv.review_reason = "; ".join(filter(None, [fv.review_reason, reason]))


def _check_centrals(centrals: list[FieldValue], codes: list[str]) -> list[FieldValue]:
    """משווה את המספרים המרכזיים שנקראו למדבקות המרכזיות שזוהו בברקוד, ומוסיפה מדבקה שהמודל החמיץ."""
    left = list(codes)
    unmatched = []
    for fv in centrals:
        if fv.value in left:
            left.remove(fv.value)
            _verified(fv)
        else:
            unmatched.append(fv)
    for fv in unmatched:
        near = [c for c in left if _digits_apart(fv.value or "", c) <= MAX_DIGIT_FIX]
        if len(near) == 1:
            left.remove(near[0])
            _taken_from_barcode(fv, near[0])
        else:
            _flag(fv, "לא נמצאה מדבקה מרכזית עם המספר הזה")
    for code in left:
        centrals.append(FieldValue(value=code, raw_value=None, confidence=1.0, status=FieldStatus.review,
                                   review_reason="נמצא בברקוד של מדבקה מרכזית; המודל לא קרא אותו"))
    return centrals


def _same_as_other_barcode(value: str, other_codes: list[str]) -> bool:
    """המספר זהה לברקוד שאינו מדבקה מרכזית, או שהברקוד מסתיים בו (20107646 מול 107646)."""
    return value in other_codes or (len(value) >= CENTRAL_DIGITS and any(c.endswith(value) for c in other_codes))


def _move_non_centrals(form: ExtractedForm, central_codes: list[str], other_codes: list[str]) -> None:
    """מספר ברשימת המרכזיים שהוא בעצם ברקוד אחר בעמוד עובר להתחייבויות, מסומן ובלי מחיקה (החלטה 16)."""
    keep, taken = [], {fv.value for fv in form.commitment_numbers}
    for fv in form.central_numbers:
        v = fv.value or ""
        if v in central_codes or not _same_as_other_barcode(v, other_codes):
            keep.append(fv)
            continue
        if v not in taken:
            _flag(fv, "הועבר מרשימת המרכזיים: זהה לברקוד שאינו מדבקה מרכזית")
            form.commitment_numbers.append(fv)
            taken.add(v)
    form.central_numbers = keep


def _check_commitments(commitments: list[FieldValue], codes: list[str]) -> None:
    """מתקנת ספרות של מספר התחייבות רק כשברקוד בעמוד הוא בבירור אותו מספר (אותו אורך, הבדל קטן)."""
    for fv in commitments:
        letters, digits = re.fullmatch(r"([A-Za-z]*)(.*)", fv.value or "").groups()
        if not digits.isdigit() or digits in codes:
            continue
        near = [c for c in codes if c.isdigit() and 0 < _digits_apart(digits, c) <= MAX_DIGIT_FIX]
        if len(near) == 1:
            _taken_from_barcode(fv, letters + near[0])


def reconcile(form: ExtractedForm, barcodes: list[Barcode]) -> ExtractedForm:
    """מצליבה את המספרים שהמודל קרא עם הברקודים בעמוד. בלי ברקודים: הרשומה נשארת כמו שהיא."""
    if not barcodes:
        if len(form.central_numbers) > 1:
            for fv in form.central_numbers:
                _flag(fv, "יותר ממספר מרכזי אחד בטופס")
        return form
    central_codes = [b.text for b in barcodes if b.is_central]
    other_codes = [b.text for b in barcodes if not b.is_central]
    if central_codes:
        _move_non_centrals(form, central_codes, other_codes)
        form.central_numbers = _check_centrals(form.central_numbers, central_codes)
    elif len(form.central_numbers) > 1:
        for fv in form.central_numbers:
            _flag(fv, "יותר ממספר מרכזי אחד בטופס")
    _check_commitments(form.commitment_numbers, other_codes)
    _attach_barcode_boxes(form, barcodes)
    return form


def _attach_barcode_boxes(form: ExtractedForm, barcodes: list[Barcode]) -> None:
    """מספר שיש לו ברקוד בעמוד מקבל את מיקום הברקוד, שמדויק יותר ממיקום שהמודל החזיר."""
    for fv in form.central_numbers + form.commitment_numbers:
        digits = re.sub(r"^[A-Za-z]+", "", fv.value or "")
        for b in barcodes:
            if b.box and digits and (b.text == digits or (len(digits) >= CENTRAL_DIGITS and b.text.endswith(digits))):
                fv.box = list(b.box)
                break
