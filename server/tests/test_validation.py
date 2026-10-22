from datetime import date

import pytest

from app.schema import FieldStatus, ModelField, ModelNumber
from app.validation import (SENDERS, build_form, check_date, check_id, check_name, check_numbers,
                            id_checksum_ok, match_sender, pick_received_date)

TODAY = date(2026, 10, 20)


def mf(text, reason=None, conf=0.9):
    """יוצרת שדה מודל לבדיקה."""
    return ModelField(text=text, confidence=conf, unclear_reason=reason)


@pytest.mark.parametrize("digits,ok", [
    ("123456782", True),
    ("011223344", True),
    ("11223344", True),
    ("11223345", False),
    ("12602233", False),
])
def test_id_checksum(digits, ok):
    """ספרת ביקורת מחושבת נכון, כולל השלמת אפסים לחישוב בלבד."""
    assert id_checksum_ok(digits) is ok


def test_id_valid_is_ok():
    """ת"ז תקינה בלי סימן אי-ודאות: ok."""
    r = check_id(mf("123456782"))
    assert r.status == FieldStatus.ok and r.value == "123456782"


def test_id_eight_digits_kept_as_read():
    """ת"ז של 8 ספרות נשמרת כפי שנקראה, בלי אפס מוביל."""
    r = check_id(mf("11223344"))
    assert r.status == FieldStatus.ok and r.value == "11223344"


def test_id_bad_checksum():
    """ספרת ביקורת שגויה: review."""
    r = check_id(mf("11223345"))
    assert r.status == FieldStatus.review and "ביקורת" in r.review_reason


def test_id_short_even_if_checksum_passes():
    """7 ספרות: review גם כשהחישוב עובר."""
    assert id_checksum_ok("1234566")
    r = check_id(mf("1234566"))
    assert r.status == FieldStatus.review and "קצרה" in r.review_reason


def test_id_too_long():
    """יותר מ-9 ספרות: review."""
    assert check_id(mf("1234567890")).status == FieldStatus.review


def test_id_non_digit():
    """תו לא ספרתי: review, והטקסט נשמר כפי שנקרא."""
    r = check_id(mf("1122334?"))
    assert r.status == FieldStatus.review and r.value == "1122334?"


def test_id_separators_removed():
    """רווחים ומקפים מוסרים; הספרות לא משתנות."""
    r = check_id(mf("011-223 344"))
    assert r.status == FieldStatus.ok and r.value == "011223344" and r.raw_value == "011-223 344"


def test_id_all_zeros():
    """אפסים בלבד: review למרות שהחישוב עובר."""
    assert check_id(mf("000000000")).status == FieldStatus.review


def test_id_valid_but_unclear():
    """תקינה אבל המודל דיווח קריאה לא ברורה: review עם הסיבה של המודל."""
    r = check_id(mf("123456782", reason="כתב יד"))
    assert r.status == FieldStatus.review and r.review_reason == "כתב יד"


def test_id_empty():
    """אין ת"ז: not_found."""
    assert check_id(mf(None)).status == FieldStatus.not_found
    assert check_id(mf("  ")).status == FieldStatus.not_found


# ---------- תאריכים ----------

@pytest.mark.parametrize("text,expected", [
    ("27-08-2026", "27/08/2026"),
    ("27.8.26", "27/08/2026"),
    ("31 -08- 2026", "31/08/2026"),
    ("25/8/26", "25/08/2026"),
])
def test_date_normalized_ok(text, expected):
    """פורמטים שנראו בדוגמאות מנורמלים ל-DD/MM/YYYY ומקבלים ok."""
    r = check_date(mf(text), TODAY)
    assert r.status == FieldStatus.ok and r.value == expected and r.raw_value == text


@pytest.mark.parametrize("text,reason", [
    ("15/96/2026", "לא קיים"),
    ("31/02/2026", "לא קיים"),
    ("אוגוסט", "לא מזוהה"),
    ("2026-08-27", "לא מזוהה"),
])
def test_date_invalid(text, reason):
    """תאריך לא קיים או פורמט לא מזוהה: review, והטקסט נשמר כפי שנקרא."""
    r = check_date(mf(text), TODAY)
    assert r.status == FieldStatus.review and reason in r.review_reason and r.value == text


def test_date_old_not_corrected():
    """שנה 2020 לא מתוקנת ל-2026: נשמרת ומסומנת."""
    r = check_date(mf("27.8.20"), TODAY)
    assert r.status == FieldStatus.review and r.value == "27/08/2020" and "ישן" in r.review_reason


def test_date_future():
    """תאריך עתידי: review."""
    r = check_date(mf("27/08/2027"), TODAY)
    assert r.status == FieldStatus.review and "עתידי" in r.review_reason


def test_date_unclear():
    """תאריך תקין שהמודל דיווח עליו קריאה לא ברורה: review."""
    assert check_date(mf("27/08/2026", reason="חותמת מטושטשת"), TODAY).status == FieldStatus.review


def test_date_empty():
    """אין תאריך: not_found."""
    assert check_date(mf(None), TODAY).status == FieldStatus.not_found


def test_pick_same_date_different_format():
    """חותמת וכתב יד באותו תאריך בפורמט שונה: אין סתירה, ok."""
    r = pick_received_date(mf("25-08-2026"), mf("25/8/26"), TODAY)
    assert r.status == FieldStatus.ok and r.value == "25/08/2026"


@pytest.mark.parametrize("text,expected", [("25.8", "25/08"), ("31/08", "31/08"), ("1-9", "01/09")])
def test_date_without_year_kept_and_flagged(text, expected):
    """תאריך בלי שנה (אפשרות א'): יום וחודש בלבד, בלי השלמת שנה, ומסומן."""
    r = check_date(mf(text), TODAY)
    assert r.value == expected and r.status == FieldStatus.review and "השנה לא כתובה" in r.review_reason


def test_date_without_year_invalid_day():
    """יום שלא קיים גם בלי שנה: review עם 'לא קיים'."""
    r = check_date(mf("31.02"), TODAY)
    assert r.status == FieldStatus.review and "לא קיים" in r.review_reason


def test_pick_year_taken_from_other_date_on_form():
    """אותו יום וחודש, ורק באחד כתובה שנה: השנה מהטופס עצמו, ok."""
    r = pick_received_date(mf("31.08.2026"), mf("31.8"), TODAY)
    assert r.status == FieldStatus.ok and r.value == "31/08/2026"
    r = pick_received_date(mf("25.8"), mf("25/08/26"), TODAY)
    assert r.status == FieldStatus.ok and r.value == "25/08/2026"


def test_pick_conflict_prefers_stamp():
    """תאריכים שונים: ערך מהחותמת, review, ושניהם בערך כפי שנקרא."""
    r = pick_received_date(mf("31-08-2026"), mf("05.09.26"), TODAY)
    assert r.status == FieldStatus.review and r.value == "31/08/2026"
    assert "31-08-2026" in r.raw_value and "05.09.26" in r.raw_value


def test_pick_only_handwritten():
    """רק כתב יד: משתמשים בו."""
    r = pick_received_date(mf(None), mf("13.8.26"), TODAY)
    assert r.status == FieldStatus.ok and r.value == "13/08/2026"


def test_pick_none():
    """אין חותמת ואין כתב יד: not_found."""
    assert pick_received_date(mf(None), mf(None), TODAY).status == FieldStatus.not_found


# ---------- מספרים ----------

def num(text, label=None, reason=None):
    """יוצרת מספר מודל לבדיקה."""
    return ModelNumber(text=text, confidence=0.9, label=label, unclear_reason=reason)


def test_central_six_digits_ok():
    """מספר מרכזי של 6 ספרות: ok."""
    c, _ = check_numbers([num("947768", "מרכזי")], [], "שמיר")
    assert c[0].status == FieldStatus.ok and c[0].value == "947768"


@pytest.mark.parametrize("text", ["11786577", "94776", "264800879"])
def test_central_other_length_flagged_not_dropped(text):
    """אורך שאינו 6: נשמר כפי שנקרא ומסומן review."""
    c, _ = check_numbers([num(text, "מרכזי")], [], "שמיר")
    assert c[0].status == FieldStatus.review and c[0].value == text and "6" in c[0].review_reason


def test_central_non_digit():
    """תו לא ספרתי במספר מרכזי: review."""
    c, _ = check_numbers([num("9477a8", "מרכזי")], [], "שמיר")
    assert c[0].status == FieldStatus.review


def test_several_centrals_kept():
    """כמה מדבקות: כל המספרים המרכזיים נשמרים."""
    c, _ = check_numbers([num("947468", "מרכזי"), num("947469", "מרכזי")], [], "וולפסון")
    assert [x.value for x in c] == ["947468", "947469"]


@pytest.mark.parametrize("text,label,value", [
    ("2646", "התחייבות", "2646"),
    ("2646", "דרישה", "2646"),
    ("2648 00879", "התחייבות", "264800879"),
    ("141046589", "התחייבות", "141046589"),
])
def test_commitment_ok(text, label, value):
    """פורמטים שנראו בדוגמאות, עם תווית מתאימה: ok, רווחים מוסרים."""
    _, m = check_numbers([], [num(text, label)], "שמיר")
    assert m[0].status == FieldStatus.ok and m[0].value == value


@pytest.mark.parametrize("text", ["X132767", "AB12345678", "a1234567"])
def test_commitment_leading_letters_ok(text):
    """עד 2 אותיות באנגלית בתחילת מספר התחייבות: ok, נשמר בדיוק כפי שנקרא."""
    _, m = check_numbers([], [num(text, "דגימה")], "לאומית")
    assert m[0].status == FieldStatus.ok and m[0].value == text


@pytest.mark.parametrize("text", ["ABC1234567", "12A34567", "א1234567", "1234567X", "X12/345"])
def test_commitment_unexpected_letter_kept_and_flagged(text):
    """אות באמצע, בסוף, בעברית או שלוש אותיות: נשמר כפי שנקרא ומסומן."""
    _, m = check_numbers([], [num(text, "התחייבות")], "שמיר")
    assert m[0].status == FieldStatus.review and m[0].value == text
    assert "במקום לא צפוי" in m[0].review_reason


def test_commitment_letters_with_short_digits():
    """אותיות ואחריהן פחות מ-4 ספרות: קצר מהצפוי."""
    _, m = check_numbers([], [num("AB12", "התחייבות")], "שמיר")
    assert m[0].status == FieldStatus.review and "קצר" in m[0].review_reason


def test_commitment_short():
    """פחות מ-4 ספרות: review."""
    _, m = check_numbers([], [num("12", "התחייבות")], "שמיר")
    assert m[0].status == FieldStatus.review and "קצר" in m[0].review_reason


def test_commitment_without_label():
    """מספר התחייבות בלי תווית: נשמר ומסומן."""
    _, m = check_numbers([], [num("2646")], "שמיר")
    assert m[0].status == FieldStatus.review and "אין תווית" in m[0].review_reason


def test_commitment_reference_label_flagged():
    """'אסמכתא' אינה תווית התחייבות: נשמר ומסומן."""
    _, m = check_numbers([], [num("2646", "אסמכתא")], "שמיר")
    assert m[0].status == FieldStatus.review and "אסמכתא" in m[0].review_reason


def test_label_mismatch_flagged_not_moved():
    """מספר ברשימת המרכזיים עם תווית התחייבות: נשאר במקום ומסומן."""
    c, m = check_numbers([num("947476", "מרכזי"), num("141046589", "התחייבות")], [], "אסותא אשדוד")
    assert [x.value for x in c] == ["947476", "141046589"] and m == []
    assert c[0].status == FieldStatus.ok
    assert c[1].status == FieldStatus.review and "התחייבות" in c[1].review_reason


def test_sample_label_only_in_leumit():
    """'דגימה' בלאומית: ok. בגורם אחר: נשמר ומסומן."""
    _, m = check_numbers([], [num("132767", "דגימה")], "לאומית")
    assert m[0].status == FieldStatus.ok
    _, m = check_numbers([], [num("132767", "דגימה")], "וולפסון")
    assert m[0].status == FieldStatus.review and "לאומית" in m[0].review_reason


def test_same_number_in_both_lists():
    """אותו מספר בשתי הרשימות: שניהם מסומנים."""
    c, m = check_numbers([num("107646", "מרכזי")], [num("107646", "התחייבות")], "שניידר")
    assert c[0].status == FieldStatus.review and m[0].status == FieldStatus.review


def test_number_unclear():
    """מספר תקין שהמודל דיווח עליו קריאה לא ברורה: review."""
    c, _ = check_numbers([num("947768", "מרכזי", reason="מדבקה חתוכה")], [], "שמיר")
    assert c[0].status == FieldStatus.review and "חתוכה" in c[0].review_reason


def test_empty_numbers_dropped():
    """מספר ריק לא נכנס לרשימה."""
    c, m = check_numbers([num(None), num("  ")], [num("")], "שמיר")
    assert c == [] and m == []


# ---------- גורם שולח ----------

SHAMIR = "המרכז הרפואי שמיר – אסף הרופא"


@pytest.mark.parametrize("name", SENDERS)
def test_every_canonical_name_matches_itself(name):
    """כל שם רשמי ברשימה מותאם לעצמו בדיוק."""
    r = match_sender(mf(name))
    assert r.status == FieldStatus.ok and r.value == name


@pytest.mark.parametrize("canonical,alias", [
    (c, a) for group in ("hmos", "hospitals", "others")
    for c, aliases in __import__("app.validation", fromlist=["x"])._SENDERS_FILE[group].items() for a in aliases
])
def test_every_alias_matches_only_its_own_sender(canonical, alias):
    """כל כינוי ברשימה מותאם בדיוק לגורם שלו בלבד (שום כינוי לא מתנגש בגורם אחר)."""
    r = match_sender(mf(alias))
    assert r.status == FieldStatus.ok and r.value == canonical


def test_short_sender_names():
    """שם קצר לטבלה: הכינוי הראשון של בית חולים; קופה, גורם אחר או בית חולים בלי כינוי: השם עצמו."""
    from app.validation import short_sender_name
    assert short_sender_name(SHAMIR) == "שמיר - אסף הרופא"
    assert short_sender_name("מרכז רפואי רבין - קמפוס גולדה השרון") == "גולדה השרון"
    assert short_sender_name("כללית") == "כללית"
    assert short_sender_name("תיירות מרפא") == "תיירות מרפא"
    assert short_sender_name("מרכז רפואי רעות") == "מרכז רפואי רעות"


@pytest.mark.parametrize("text", ["באר שבע", "ראשון לציון", "צפון", "סנט", "הרופא", "לבריאות הנפש"])
def test_shared_words_are_not_guessed(text):
    """מילה שמשותפת לכמה גורמים (עיר, אזור, סוג) לא מנוחשת לגורם אחד: לבדיקה."""
    assert match_sender(mf(text)).status == FieldStatus.review


@pytest.mark.parametrize("text,expected", [
    ("אסף הרופא", SHAMIR),
    ("מרכז רפואי שמיר", SHAMIR),
    ("שניידר", "מרכז שניידר לרפואת ילדים בישראל"),
    ("מרכז רפואי מאיר", "מרכז רפואי מאיר"),
    ("כללית שרון", "מרכז רפואי רבין - קמפוס גולדה השרון"),
    ("לאומית שירותי בריאות", "לאומית"),
    ("רמב״ם", "רמב\"ם - הקריה הרפואית לבריאות האדם"),
])
def test_alias_exact_match(text, expected):
    """כינוי או שם עם מילים כלליות: התאמה מדויקת, ok, השם הרשמי נשמר."""
    r = match_sender(mf(text))
    assert r.status == FieldStatus.ok and r.value == expected and r.raw_value == text


def test_hmo_and_hospital_picks_hospital_ok():
    """קופה ובית חולים באותו טקסט: בית החולים (החלטה 14), ok."""
    r = match_sender(mf("שירותי בריאות כללית - שניידר"))
    assert r.value == "מרכז שניידר לרפואת ילדים בישראל" and r.status == FieldStatus.ok


def test_partial_single_is_review():
    """בית חולים אחד עם מילים לא מוכרות: התאמה חלקית, review."""
    r = match_sender(mf("שניידר מחלקת ילדים ב"))
    assert r.value == "מרכז שניידר לרפואת ילדים בישראל" and r.status == FieldStatus.review


# ---------- שמות ----------

def test_name_always_review():
    """שם שנמצא: תמיד review, גם בלי ספק מהמודל."""
    r = check_name(mf("ישראל", conf=1.0))
    assert r.status == FieldStatus.review and r.value == "ישראל" and "שם" in r.review_reason


def test_name_unclear_reason_kept():
    """סיבת הספק של המודל נוספת לסיבה."""
    r = check_name(mf("פסי.", reason="כתב יד קשה לקריאה"))
    assert "כתב יד" in r.review_reason


def test_name_empty():
    """אין שם: not_found."""
    assert check_name(mf(None)).status == FieldStatus.not_found


def test_ambiguous_is_empty():
    """'אסותא' לבד מתאים לכמה בתי חולים: ריק ומסומן."""
    r = match_sender(mf("אסותא"))
    assert r.value is None and r.status == FieldStatus.review and "כמה" in r.review_reason


def test_tel_hashomer_alone_not_sheba():
    """'תל השומר' לבד (הנמען) אינו מותאם לשיבא."""
    r = match_sender(mf("המעבדה המרכזית לנגיפים תל השומר"))
    assert r.value is None and r.status == FieldStatus.review


def test_unknown_sender():
    """גורם שלא ברשימה: ריק, מסומן, ומה שנקרא נשמר."""
    r = match_sender(mf("קליניקה פרטית"))
    assert r.value is None and r.status == FieldStatus.review and r.raw_value == "קליניקה פרטית"


def test_sender_unclear():
    """התאמה מדויקת אבל המודל דיווח ספק: review."""
    assert match_sender(mf("שמיר", reason="לוגו מטושטש")).status == FieldStatus.review


def test_sender_empty():
    """אין גורם: not_found."""
    assert match_sender(mf(None)).status == FieldStatus.not_found


@pytest.mark.parametrize("text,expected", [("תיירות מרפא", "תיירות מרפא"),
                                           ("הרשות הפלסטינית", "הרשות הפלסטינית")])
def test_other_payers_in_list(text, expected):
    """גורמים משלמים שנראו בטפסים (עמודים 20–22) נמצאים ברשימה ומותאמים."""
    assert expected in SENDERS
    r = match_sender(mf(text))
    assert r.value == expected and r.status == FieldStatus.ok


def test_number_equal_to_id_flagged():
    """מספר התחייבות או מרכזי שזהה לת"ז שבטופס: נשמר ומסומן."""
    from app.schema import ModelOutput
    out = ModelOutput(first_name=mf("ישראל"), last_name=mf("ישראלי"), id_number=mf("11223344"),
                      central_numbers=[ModelNumber(text="11223344", confidence=0.9, label="מרכזי")],
                      received_date_stamp=mf("31.08.2026"), received_date_handwritten=mf(None),
                      sender=mf("שמיר"),
                      commitment_numbers=[ModelNumber(text="11223344", confidence=0.9, label="התחייבות"),
                                          ModelNumber(text="2646", confidence=0.9, label="התחייבות")])
    form = build_form(out, 1)
    assert all("זהה לת\"ז" in n.review_reason for n in form.central_numbers + form.commitment_numbers[:1])
    assert form.commitment_numbers[1].status == FieldStatus.ok


def test_model_position_attached_to_fields():
    """מיקום מהמודל (0-1000, y לפני x) נשמר כ-[x0, y0, x1, y1] ביחס לדף; מיקום לא תקין או שדה ריק: בלי מיקום."""
    from app.schema import ModelOutput

    def at(text, box):
        return ModelField(text=text, confidence=0.9, box_2d=box)

    out = ModelOutput(first_name=at("ישראל", [100, 200, 120, 300]), last_name=at(None, [1, 2, 3, 4]),
                      id_number=at("11223344", [500, 900, 400, 950]),
                      central_numbers=[ModelNumber(text="947768", confidence=1, label="מרכזי",
                                                   box_2d=[50, 700, 80, 800])],
                      received_date_stamp=at("31.08.2026", [600, 100, 640, 250]),
                      received_date_handwritten=mf(None), sender=at("שמיר", [10, 20, 30]), commitment_numbers=[])
    form = build_form(out, 1)
    assert form.first_name.box == [0.2, 0.1, 0.3, 0.12]
    assert form.last_name.box is None and form.id_number.box is None and form.sender.box is None
    assert form.received_date.box == [0.1, 0.6, 0.25, 0.64]
    assert form.central_numbers[0].box == [0.7, 0.05, 0.8, 0.08]
