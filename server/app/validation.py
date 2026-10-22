import json
import re
from datetime import date
from pathlib import Path

from .schema import ExtractedForm, FieldStatus, FieldValue, ModelField, ModelNumber, ModelOutput

_SENDERS_FILE = json.loads((Path(__file__).parent / "senders.json").read_text(encoding="utf-8"))
HMOS: dict[str, list[str]] = _SENDERS_FILE["hmos"]
HOSPITALS: dict[str, list[str]] = _SENDERS_FILE["hospitals"]
OTHERS: dict[str, list[str]] = _SENDERS_FILE.get("others", {})  # גורמים משלמים שנראו בטפסים
SENDERS = list(HMOS) + list(HOSPITALS) + list(OTHERS)
LEUMIT = "לאומית"

_GENERIC_WORDS = {"המרכז", "מרכז", "הרפואי", "רפואי", "בית", "החולים", "חולים",
                  "ביהח", "האוניברסיטאי", "עש", "קמפוס"}


def short_sender_name(name: str) -> str:
    """שם קצר לתצוגה בטבלה: הכינוי הראשון של בית חולים (ברשימה הוא הכינוי המוכר), אחרת השם עצמו."""
    aliases = HOSPITALS.get(name)
    return aliases[0] if aliases else name


def normalize_sender(text: str) -> str:
    """מנקה שם גורם להשוואה: בלי מירכאות, סימני פיסוק ומילים כלליות."""
    text = re.sub(r"[\"'״׳]", "", text)
    text = re.sub(r"[\-–—(),.]", " ", text)
    return " ".join(w for w in text.split() if w not in _GENERIC_WORDS)


def _sender_index() -> dict[str, list[str]]:
    """בונה מילון: שם רשמי -> כל הצורות המנוקות שלו (שם רשמי + כינויים)."""
    index = {}
    for canonical, aliases in {**HMOS, **HOSPITALS, **OTHERS}.items():
        forms = {normalize_sender(canonical)} | {normalize_sender(a) for a in aliases}
        index[canonical] = [f for f in forms if f]
    return index


_SENDER_INDEX = _sender_index()


def _contains(outer: str, inner: str) -> bool:
    """בודקת אם inner מופיע ב-outer כמילים שלמות."""
    return len(inner) >= 3 and f" {inner} " in f" {outer} "


def match_sender(f: ModelField) -> FieldValue:
    """מתאימה גורם שולח לרשימה: מדויק או קופה+בית חולים = ok, חלקי יחיד = review, אחרת ריק ומסומן."""
    raw = f.text
    text = normalize_sender(raw or "")
    if not text:
        return FieldValue(confidence=f.confidence, status=FieldStatus.not_found)

    exact = [c for c, forms in _SENDER_INDEX.items() if text in forms]
    if len(exact) == 1:
        return FieldValue(value=exact[0], raw_value=raw, confidence=f.confidence,
                          status=FieldStatus.review if f.unclear_reason else FieldStatus.ok,
                          review_reason=f.unclear_reason)

    partial = [c for c, forms in _SENDER_INDEX.items()
               if any(_contains(text, form) or _contains(form, text) for form in forms)]
    hospitals = [c for c in partial if c in HOSPITALS]
    if len(hospitals) == 1 and len(partial) > 1 and all(c in HMOS for c in partial if c not in hospitals):
        return FieldValue(value=hospitals[0], raw_value=raw, confidence=f.confidence,
                          status=FieldStatus.review if f.unclear_reason else FieldStatus.ok,
                          review_reason=f.unclear_reason)
    if len(partial) == 1:
        return FieldValue(value=partial[0], raw_value=raw, confidence=f.confidence,
                          status=FieldStatus.review, review_reason="התאמה חלקית לרשימה")

    reason = "כמה גורמים אפשריים" if partial else "גורם לא ברשימה"
    return FieldValue(value=None, raw_value=raw, confidence=f.confidence,
                      status=FieldStatus.review, review_reason=reason)

NAME_REASON = "שם, אין בדיקה אוטומטית"


def check_name(f: ModelField) -> FieldValue:
    """שם: אין בדיקה בקוד, ולכן כל שם שנמצא מסומן review (ריק = not_found)."""
    text = (f.text or "").strip()
    if not text:
        return FieldValue(confidence=f.confidence, status=FieldStatus.not_found)
    reason = "; ".join(filter(None, [NAME_REASON, f.unclear_reason]))
    return FieldValue(value=text, raw_value=f.text, confidence=f.confidence,
                      status=FieldStatus.review, review_reason=reason)


def id_checksum_ok(digits: str) -> bool:
    """בודקת ספרת ביקורת של ת"ז (משלימה אפסים משמאל ל-9 ספרות רק לחישוב)."""
    total = 0
    for i, ch in enumerate(digits.zfill(9)):
        n = int(ch) * (1 if i % 2 == 0 else 2)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def check_id(f: ModelField) -> FieldValue:
    """בודקת ת"ז: ספרות בלבד, אורך 8–9, ספרת ביקורת, וסימן אי-ודאות מהמודל."""
    raw = f.text
    text = (raw or "").strip()
    if not text:
        return FieldValue(confidence=f.confidence, status=FieldStatus.not_found)

    digits = text.replace(" ", "").replace("-", "")
    problem = None
    if not digits.isdigit():
        problem = "תו לא ספרתי בת\"ז"
    elif len(digits) > 9:
        problem = "ת\"ז ארוכה מדי"
    elif len(digits) < 8:
        problem = "ת\"ז קצרה מדי"
    elif set(digits) == {"0"}:
        problem = "ת\"ז אפסים בלבד"
    elif not id_checksum_ok(digits):
        problem = "ספרת ביקורת לא תקינה"
    elif f.unclear_reason:
        problem = f.unclear_reason

    value = digits if digits.isdigit() else text
    return FieldValue(value=value, raw_value=raw, confidence=f.confidence,
                      status=FieldStatus.review if problem else FieldStatus.ok,
                      review_reason=problem)


MAX_DATE_AGE_DAYS = 365
NO_YEAR = "השנה לא כתובה בטופס"


def parse_date(text: str, today: date | None = None) -> tuple[str | None, str | None]:
    """מנרמלת תאריך ל-DD/MM/YYYY ומחזירה (תאריך, בעיה). לא מתקנת ספרות ולא משלימה שנה חסרה."""
    today = today or date.today()
    parts = [p for p in re.split(r"[.\-/\s]+", text.strip()) if p]
    if not all(p.isdigit() for p in parts):
        return None, "פורמט תאריך לא מזוהה"
    if len(parts) == 2 and all(len(p) <= 2 for p in parts):
        day, month = (int(p) for p in parts)
        try:
            date(2000, month, day)  # שנה מעוברת: רק בדיקה שהיום והחודש קיימים
        except ValueError:
            return None, "תאריך לא קיים"
        return f"{day:02d}/{month:02d}", NO_YEAR
    if len(parts) != 3:
        return None, "פורמט תאריך לא מזוהה"
    day, month, year = parts
    if len(day) > 2 or len(month) > 2 or len(year) not in (2, 4):
        return None, "פורמט תאריך לא מזוהה"
    y = int(year) + (2000 if len(year) == 2 else 0)
    try:
        d = date(y, int(month), int(day))
    except ValueError:
        return None, "תאריך לא קיים"
    normalized = d.strftime("%d/%m/%Y")
    if d > today:
        return normalized, "תאריך עתידי"
    if (today - d).days > MAX_DATE_AGE_DAYS:
        return normalized, "תאריך ישן מדי, ייתכן שנקרא לא נכון"
    return normalized, None


def check_date(f: ModelField, today: date | None = None) -> FieldValue:
    """בודקת שדה תאריך: נרמול, תקינות, סבירות, וסימן אי-ודאות מהמודל."""
    text = (f.text or "").strip()
    if not text:
        return FieldValue(confidence=f.confidence, status=FieldStatus.not_found)
    normalized, problem = parse_date(text, today)
    problem = problem or f.unclear_reason
    return FieldValue(value=normalized or text, raw_value=f.text, confidence=f.confidence,
                      status=FieldStatus.review if problem else FieldStatus.ok,
                      review_reason=problem)


def pick_received_date(stamp: ModelField, handwritten: ModelField,
                       today: date | None = None) -> FieldValue:
    """בוחרת תאריך קבלה לפי החלטה 13: חותמת קודמת; תאריכים שונים אחרי נרמול = review עם שניהם."""
    s = check_date(stamp, today)
    h = check_date(handwritten, today)
    if s.status == FieldStatus.not_found:
        return h
    if h.status == FieldStatus.not_found or s.value == h.value:
        return s
    # אותו יום וחודש, ורק באחד מהם כתובה שנה: השנה לקוחה מהטופס עצמו, לא מנוחשת
    if s.value and h.value and s.value[:5] == h.value[:5]:
        full = s if len(s.value) > 5 else h
        if len(full.value) > 5:
            return full
    return FieldValue(value=s.value, raw_value=f"חותמת: {stamp.text} | כתב יד: {handwritten.text}",
                      confidence=min(stamp.confidence, handwritten.confidence),
                      status=FieldStatus.review,
                      review_reason="חותמת ותאריך בכתב יד שונים")


COMMITMENT_LABELS = ("התחייבות", "דרישה", "דגימה")
MIN_COMMITMENT_DIGITS = 4
# עד 2 אותיות באנגלית בתחילת המספר (נראה בטפסים), ואחריהן ספרות בלבד
COMMITMENT_FORMAT = re.compile(r"[A-Za-z]{0,2}(\d+)")


def label_kind(label: str | None) -> str | None:
    """מסווגת תווית מהטופס: 'central', 'commitment' או None."""
    text = label or ""
    if "מרכז" in text:
        return "central"
    if any(k in text for k in COMMITMENT_LABELS):
        return "commitment"
    return None


def _clean_number(text: str | None) -> str:
    """מסירה רווחים ומקפים בלבד; לא משנה אף ספרה או אות."""
    return re.sub(r"[\s\-]", "", text or "")


def _number_field(n: ModelNumber, value: str, problems: list[str]) -> FieldValue:
    """בונה שדה מספר סופי מרשימת בעיות (ריקה = ok)."""
    if n.unclear_reason:
        problems.append(n.unclear_reason)
    return FieldValue(value=value, raw_value=n.text, confidence=n.confidence,
                      status=FieldStatus.review if problems else FieldStatus.ok,
                      review_reason="; ".join(problems) or None)


CENTRAL_TYPICAL_LENGTH = 6


def check_central(n: ModelNumber) -> FieldValue:
    """בודקת מספר מרכזי: ספרות בלבד, אורך שאינו 6 מסומן (לא נמחק), ותווית שלא סותרת."""
    value = _clean_number(n.text)
    problems = []
    if not value.isdigit():
        problems.append("תו לא ספרתי במספר מרכזי")
    elif len(value) != CENTRAL_TYPICAL_LENGTH:
        problems.append("מספר מרכזי אינו באורך 6 ספרות, כמקובל")
    if label_kind(n.label) == "commitment":
        problems.append(f"התווית בטופס היא '{n.label}'")
    return _number_field(n, value, problems)


def check_commitment(n: ModelNumber, is_leumit: bool) -> FieldValue:
    """בודקת מספר התחייבות: עד 2 אותיות באנגלית בהתחלה ואחריהן ספרות, תווית מתאימה, ו'דגימה' רק בלאומית."""
    value = _clean_number(n.text)
    problems = []
    match = COMMITMENT_FORMAT.fullmatch(value)
    if not match:
        problems.append("אות או תו במקום לא צפוי במספר התחייבות")
    elif len(match.group(1)) < MIN_COMMITMENT_DIGITS:
        problems.append("מספר התחייבות קצר מהצפוי")
    label = (n.label or "").strip()
    if not label:
        problems.append("אין תווית ליד המספר, לא ודאי שזה מספר התחייבות")
    elif label_kind(label) != "commitment":
        problems.append(f"התווית בטופס היא '{label}'")
    elif "דגימה" in label and not is_leumit:
        problems.append("תווית 'דגימה' בגורם שאינו לאומית")
    return _number_field(n, value, problems)


def check_numbers(central: list[ModelNumber], commitment: list[ModelNumber],
                  sender: str | None) -> tuple[list[FieldValue], list[FieldValue]]:
    """בודקת כל מספר ברשימה שבה המודל שם אותו, ומסמנת מספר שמופיע בשתי הרשימות."""
    is_leumit = sender == LEUMIT
    centrals = [check_central(n) for n in central if (n.text or "").strip()]
    commitments = [check_commitment(n, is_leumit) for n in commitment if (n.text or "").strip()]

    for dup in {c.value for c in centrals} & {c.value for c in commitments}:
        for fv in centrals + commitments:
            if fv.value == dup:
                fv.status = FieldStatus.review
                fv.review_reason = "; ".join(filter(None, [fv.review_reason, "מופיע גם כמרכזי וגם כהתחייבות"]))
    return centrals, commitments


def check_correction(field: str, text: str | None) -> FieldValue:
    """בודקת ערך שתיקנה לבורנטית באותם כללי קוד; שם שתוקן הוא ok (אין לו בדיקה בקוד)."""
    f = ModelField(text=(text or "").strip() or None, confidence=1.0)
    if f.text is None:
        return FieldValue(confidence=1.0, status=FieldStatus.not_found)
    if field in ("first_name", "last_name"):
        return FieldValue(value=f.text, raw_value=f.text, confidence=1.0, status=FieldStatus.ok)
    if field == "id_number":
        return check_id(f)
    if field == "received_date":
        return check_date(f)
    if field == "sender":
        fv = match_sender(f)
        fv.value = fv.value or f.text
        return fv
    raise ValueError(field)


def check_number_correction(kind: str, text: str, sender: str | None) -> FieldValue:
    """בודקת מספר שתוקן או נוסף ידנית (בלי בדיקת תווית: האדם קבע את הסוג)."""
    if kind == "central":
        return check_central(ModelNumber(text=text, confidence=1.0, label="מרכזי"))
    return check_commitment(ModelNumber(text=text, confidence=1.0, label="התחייבות"), sender == LEUMIT)


def flag_id_lookalikes(numbers: list[FieldValue], id_number: FieldValue) -> None:
    """מסמנת מספר מרכזי או התחייבות שזהה לת"ז שבאותו טופס (המודל קרא את הת"ז כמספר)."""
    if not id_number.value:
        return
    for fv in numbers:
        if fv.value == id_number.value:
            fv.status = FieldStatus.review
            fv.review_reason = "; ".join(filter(None, [fv.review_reason, "זהה לת\"ז שבטופס"]))


def to_box(f: ModelField) -> list[float] | None:
    """ממירה מיקום מהמודל ([ymin, xmin, ymax, xmax], 0-1000) ל-[x0, y0, x1, y1] ביחס לדף. לא תקין: None."""
    b = f.box_2d
    if not f.text or not b or len(b) != 4:
        return None
    y0, x0, y1, x1 = (v / 1000 for v in b)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    return [round(v, 4) for v in (x0, y0, x1, y1)]


def _attach_boxes(form: ExtractedForm, out: ModelOutput) -> None:
    """מצמידה לכל שדה את המיקום שהמודל החזיר. מספרים לפי הטקסט שנקרא (הם עשויים לעבור בין רשימות)."""
    for name in ("first_name", "last_name", "id_number", "sender"):
        getattr(form, name).box = to_box(getattr(out, name))
    date_source = out.received_date_stamp if out.received_date_stamp.text else out.received_date_handwritten
    form.received_date.box = to_box(date_source)
    boxes = {n.text: to_box(n) for n in out.central_numbers + out.commitment_numbers}
    for fv in form.central_numbers + form.commitment_numbers:
        fv.box = boxes.get(fv.raw_value)


def build_form(out: ModelOutput, source_page: int | None = None) -> ExtractedForm:
    """בונה רשומה סופית מתשובת המודל."""
    sender = match_sender(out.sender)
    centrals, commitments = check_numbers(out.central_numbers, out.commitment_numbers, sender.value)
    id_number = check_id(out.id_number)
    flag_id_lookalikes(centrals + commitments, id_number)
    form = ExtractedForm(
        source_page=source_page,
        first_name=check_name(out.first_name),
        last_name=check_name(out.last_name),
        id_number=id_number,
        central_numbers=centrals,
        received_date=pick_received_date(out.received_date_stamp, out.received_date_handwritten),
        sender=sender,
        commitment_numbers=commitments,
        page_rotation=out.page_rotation,
    )
    _attach_boxes(form, out)
    return form
