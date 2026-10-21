from app.barcodes import Barcode, read_barcodes, reconcile
from app.schema import ExtractedForm, FieldStatus, FieldValue

OK, REVIEW = FieldStatus.ok, FieldStatus.review
CENTRAL = Barcode("947768", "Code128", 0.081)


def fv(value, status=OK, reason=None):
    """שדה לבדיקה."""
    return FieldValue(value=value, raw_value=value, confidence=0.9, status=status, review_reason=reason)


def form(central, commitment=()):
    """רשומה עם המספרים שנבדקים בלבד."""
    empty = FieldValue()
    return ExtractedForm(first_name=empty, last_name=empty, id_number=empty, received_date=empty, sender=empty,
                         central_numbers=[fv(v) for v in central], commitment_numbers=[fv(v) for v in commitment])


def test_central_signature():
    """מדבקה מרכזית: Code 128, 6 ספרות, ברוחב של כ-8% מהדף. רחב יותר או אורך אחר: לא מרכזית."""
    assert CENTRAL.is_central
    assert not Barcode("436702", "Code128", 0.112).is_central
    assert not Barcode("12602233", "Code128", 0.08).is_central
    assert not Barcode("947768", "Code39", 0.08).is_central


def test_central_matching_barcode_is_verified():
    """המספר שנקרא זהה לברקוד המרכזי: מאומת (ok), גם אם סומן קודם."""
    f = form([])
    f.central_numbers = [fv("947768", REVIEW, "כתב יד")]
    r = reconcile(f, [CENTRAL])
    assert r.central_numbers[0].status == OK and r.central_numbers[0].value == "947768"


def test_central_digit_misread_taken_from_barcode():
    """ספרה אחת שונה מהברקוד: הערך מהברקוד, מסומן, עם מה שהמודל קרא."""
    r = reconcile(form(["947168"]), [CENTRAL])
    n = r.central_numbers[0]
    assert n.value == "947768" and n.status == REVIEW and "947168" in n.review_reason


def test_wrong_number_as_central_is_flagged():
    """מספר בלי ברקוד ברשימת המרכזיים: נשאר ומסומן; המרכזי האמיתי מאומת."""
    r = reconcile(form(["141046589", "947476"]), [Barcode("947476", "Code128", 0.081)])
    by_value = {n.value: n for n in r.central_numbers}
    assert by_value["947476"].status == OK
    assert by_value["141046589"].status == REVIEW
    assert "לא נמצאה מדבקה מרכזית" in by_value["141046589"].review_reason


def test_other_barcode_in_centrals_moved_to_commitments():
    """מספר ברשימת המרכזיים שזהה לברקוד שאינו מרכזי (עמוד 4): עובר להתחייבויות, מסומן."""
    r = reconcile(form(["436702", "946621"]), [Barcode("436702", "Code128", 0.112),
                                               Barcode("946621", "Code128", 0.081)])
    assert [n.value for n in r.central_numbers] == ["946621"] and r.central_numbers[0].status == OK
    moved = r.commitment_numbers[0]
    assert moved.value == "436702" and moved.status == REVIEW and "הועבר" in moved.review_reason


def test_moved_when_barcode_ends_with_number():
    """ברקוד עם קידומת (20107646 מול 107646, עמוד 2): עובר כפי שנקרא, בלי הקידומת."""
    r = reconcile(form(["948205", "107646"]), [Barcode("948205", "Code128", 0.078),
                                               Barcode("20107646", "Code128", 0.097)])
    assert [n.value for n in r.central_numbers] == ["948205"]
    assert [n.value for n in r.commitment_numbers] == ["107646"]


def test_not_moved_without_central_sticker_or_when_already_listed():
    """בלי מדבקה מרכזית שזוהתה לא מעבירים; מספר שכבר ברשימת ההתחייבויות לא נכפל."""
    other = Barcode("436702", "Code128", 0.112)
    r = reconcile(form(["436702"]), [other])
    assert [n.value for n in r.central_numbers] == ["436702"] and r.commitment_numbers == []
    r = reconcile(form(["436702", "946621"], ["436702"]), [other, Barcode("946621", "Code128", 0.081)])
    assert [n.value for n in r.commitment_numbers] == ["436702"]
    assert [n.value for n in r.central_numbers] == ["946621"]


def test_two_central_stickers_both_stay():
    """שתי מדבקות מרכזיות (עמוד 12): שתיהן נשארות מרכזיות ומאומתות, שום דבר לא עובר."""
    r = reconcile(form(["947468", "947469"]), [Barcode("947468", "Code128", 0.08),
                                               Barcode("947469", "Code128", 0.08),
                                               Barcode("12043641", "Code128", 0.141)])
    assert [n.value for n in r.central_numbers] == ["947468", "947469"]
    assert all(n.status == OK for n in r.central_numbers) and r.commitment_numbers == []


def test_central_missed_by_model_added_from_barcode():
    """המודל לא קרא מספר מרכזי: נוסף מהברקוד, מסומן."""
    r = reconcile(form([]), [CENTRAL])
    assert [n.value for n in r.central_numbers] == ["947768"]
    assert r.central_numbers[0].status == REVIEW and "המודל לא קרא" in r.central_numbers[0].review_reason


def test_commitment_digit_fixed_only_when_clearly_same_number():
    """התחייבות: ספרה שונה מברקוד באותו אורך = מהברקוד ומסומן; אורך שונה או הבדל גדול = לא נוגעים."""
    codes = [CENTRAL, Barcode("11001", "Code39", 0.1), Barcode("20107646", "Code128", 0.1)]
    r = reconcile(form(["947768"], ["77001", "107646", "55555"]), codes)
    m = {n.raw_value: n for n in r.commitment_numbers}
    assert m["77001"].value == "11001" and m["77001"].status == REVIEW
    assert m["107646"].value == "107646" and m["107646"].status == OK
    assert m["55555"].value == "55555"


def test_commitment_letter_kept_when_barcode_has_none():
    """אות שהמודל ראה בטופס לא נמחקת בגלל ברקוד בלי אות."""
    r = reconcile(form(["947768"], ["X132797"]), [CENTRAL, Barcode("132797", "Code39", 0.11)])
    assert r.commitment_numbers[0].value == "X132797"


def test_no_barcodes_more_than_one_central_flagged():
    """בלי ברקודים (צילום מסך): יותר ממספר מרכזי אחד מסומן; אחד בלבד לא משתנה."""
    r = reconcile(form(["947501", "94750125"]), [])
    assert all(n.status == REVIEW for n in r.central_numbers)
    assert reconcile(form(["947501"]), []).central_numbers[0].status == OK


def test_number_gets_barcode_position():
    """מספר שיש לו ברקוד מקבל את מיקום הברקוד (גם עם אות או קידומת); מספר בלי ברקוד שומר את המיקום שהיה לו."""
    f = form(["947768"], ["X132797", "107646", "55555"])
    f.commitment_numbers[2].box = [0.1, 0.1, 0.2, 0.2]
    r = reconcile(f, [Barcode("947768", "Code128", 0.081, (0.7, 0.1, 0.78, 0.13)),
                      Barcode("132797", "Code39", 0.11, (0.1, 0.5, 0.2, 0.52)),
                      Barcode("20107646", "Code128", 0.1, (0.3, 0.3, 0.4, 0.32))])
    assert r.central_numbers[0].box == [0.7, 0.1, 0.78, 0.13]
    assert [n.box for n in r.commitment_numbers] == [[0.1, 0.5, 0.2, 0.52], [0.3, 0.3, 0.4, 0.32],
                                                     [0.1, 0.1, 0.2, 0.2]]


def test_barcode_position_read_from_image():
    """המיקום שנקרא מתמונה אמיתית הוא יחסי לגודל הדף (0-1) ונופל על הברקוד."""
    import io

    import zxingcpp
    from PIL import Image

    code = Image.fromarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, "947768", width=300, height=80))
    page = Image.new("L", (1000, 1400), 255)
    page.paste(code, (600, 200))
    buf = io.BytesIO()
    page.save(buf, "PNG")
    [b] = read_barcodes(buf.getvalue())
    x0, y0, x1, y1 = b.box
    w, h = code.size  # הברקוד נמצא בתוך השטח שהודבק
    assert 0.6 <= x0 < x1 <= (600 + w) / 1000 and 200 / 1400 <= y0 < y1 <= (200 + h) / 1400


def test_bad_image_returns_no_barcodes():
    """תמונה פגומה לא מפילה את העמוד: אין ברקודים."""
    assert read_barcodes(b"not an image") == []
