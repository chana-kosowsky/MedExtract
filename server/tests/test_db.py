import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import db
from app.main import app
from app.schema import Commitment, ExtractedForm, FieldStatus, FieldValue, RecordKind

OK, REVIEW = FieldStatus.ok, FieldStatus.review


def fv(value, status=OK, reason=None):
    """שדה לבדיקה."""
    return FieldValue(value=value, raw_value=value, confidence=0.9, status=status, review_reason=reason)


def make_form(**over) -> ExtractedForm:
    """רשומה מלאה ותקינה, עם אפשרות לשנות שדות."""
    base = dict(
        source_page=1, first_name=fv("ישראל", REVIEW, "שם"), last_name=fv("כהן", REVIEW, "שם"),
        id_number=fv("011223344"), received_date=fv("13/08/2026"), sender=fv("שניידר"),
        central_numbers=[fv("947468"), fv("947469")], commitment_numbers=[fv("12345678")])
    return ExtractedForm(**{**base, **over})


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    """כל בדיקה מתחילה מטבלה ריקה (בסכמת הבדיקה בלבד)."""
    db.reset_demo()
    with Session(db.get_engine()) as s:
        db._delete_ids(s, list(s.exec(select(Commitment.id)).all()))
        s.commit()


def test_save_and_read_back(client):
    """רשומה נשמרת עם כל המספרים, לפי הסדר."""
    rid = db.save_form(make_form(), "b1", 1)
    r = client.get(f"/api/commitments/{rid}").json()
    assert r["state"] == "pending" and r["batch_id"] == "b1" and r["source_page"] == 1
    assert r["id_number"] == {"value": "011223344", "raw_value": "011223344", "status": "ok",
                              "review_reason": None, "box": None}
    assert [n["value"] for n in r["central_numbers"]] == ["947468", "947469"]
    assert [n["value"] for n in r["commitment_numbers"]] == ["12345678"]
    assert r["needs_review"] is True


def test_health_answers_head(client):
    """שירות הפינג שולח HEAD: גם עליו עונים 200 ובודקים את המסד."""
    assert client.get("/health").json() == {"status": "ok", "db": "ok"}
    assert client.head("/health").status_code == 200


def test_model_saved_but_not_sent_to_screen(client):
    """איזה מודל קרא את העמוד נשמר במסד (למדידה), ולא נשלח לממשק (החלטה 34)."""
    rid = db.save_form(make_form(model="claude-opus-5-5"), "b1", 1)
    with Session(db.get_engine()) as s:
        assert s.get(Commitment, rid).model_used == "claude-opus-5-5"
    assert "model_used" not in client.get(f"/api/commitments/{rid}").json()
    assert "model_used" not in client.get("/api/commitments").json()["items"][0]


def test_positions_saved_and_kept_after_correction(client):
    """מיקום כל שדה ומספר נשמר ונשלח ללקוח; תיקון ערך לא מוחק את המיקום."""
    f = make_form()
    f.id_number.box = [0.1, 0.2, 0.3, 0.25]
    f.central_numbers[0].box = [0.7, 0.05, 0.8, 0.08]
    rid = db.save_form(f, "b1", 1)
    client.patch(f"/api/commitments/{rid}/fields/id_number", json={"value": "11223344"})
    r = client.get(f"/api/commitments/{rid}").json()
    assert r["id_number"]["box"] == [0.1, 0.2, 0.3, 0.25] and r["id_number"]["value"] == "11223344"
    assert r["central_numbers"][0]["box"] == [0.7, 0.05, 0.8, 0.08]
    assert r["central_numbers"][1]["box"] is None and r["sender"]["box"] is None


def test_failed_page_saved_and_locked(client):
    """עמוד שנכשל נשמר בסטטוס 'נכשל', ואי אפשר לאשר אותו."""
    rid = db.save_failure("b1", 1, 3, "bad_page", "העמוד פגום")
    r = client.get(f"/api/commitments/{rid}").json()
    assert (r["state"], r["error_code"], r["source_page"]) == ("failed", "bad_page", 3)
    assert client.post(f"/api/commitments/{rid}/approve").status_code == 400


def test_correction_runs_code_checks(client):
    """תיקון ת"ז עם ספרת ביקורת שגויה נשאר לבדיקה (אפשרות א'); תיקון תקין = ok."""
    rid = db.save_form(make_form(id_number=fv("1122334", REVIEW, "ת\"ז קצרה מדי")), "b1", 1)
    bad = client.patch(f"/api/commitments/{rid}/fields/id_number", json={"value": "123456789"}).json()
    assert bad["id_number"]["status"] == "review"
    assert bad["id_number"]["review_reason"] == "ספרת ביקורת לא תקינה"
    assert bad["id_number"]["raw_value"] == "1122334"
    good = client.patch(f"/api/commitments/{rid}/fields/id_number", json={"value": "011223344"}).json()
    assert good["id_number"]["status"] == "ok"


def test_name_correction_is_ok_and_empty_is_not_found(client):
    """שם שתוקן ידנית = ok; מחיקת ערך = not_found."""
    rid = db.save_form(make_form(), "b1", 1)
    r = client.patch(f"/api/commitments/{rid}/fields/first_name", json={"value": " משה "}).json()
    assert r["first_name"]["value"] == "משה" and r["first_name"]["status"] == "ok"
    r = client.patch(f"/api/commitments/{rid}/fields/sender", json={"value": ""}).json()
    assert r["sender"]["status"] == "not_found"


def test_sender_correction_not_in_list_kept_and_flagged(client):
    """גורם שתוקן לשם שלא ברשימה: נשמר כפי שהוקלד ומסומן."""
    rid = db.save_form(make_form(), "b1", 1)
    r = client.patch(f"/api/commitments/{rid}/fields/sender", json={"value": "מרפאה פרטית"}).json()
    assert r["sender"]["value"] == "מרפאה פרטית" and r["sender"]["status"] == "review"


def test_numbers_add_correct_delete(client):
    """הוספה, תיקון ומחיקה של מספרים, עם בדיקות קוד לכל מספר."""
    rid = db.save_form(make_form(), "b1", 1)
    r = client.post(f"/api/commitments/{rid}/numbers", json={"kind": "central", "value": "94747"}).json()
    added = r["central_numbers"][-1]
    assert added["value"] == "94747" and added["status"] == "review"
    r = client.patch(f"/api/commitments/{rid}/numbers/{added['id']}", json={"value": "947470"}).json()
    assert r["central_numbers"][-1]["status"] == "ok"
    r = client.delete(f"/api/commitments/{rid}/numbers/{added['id']}").json()
    assert [n["value"] for n in r["central_numbers"]] == ["947468", "947469"]
    assert client.post(f"/api/commitments/{rid}/numbers", json={"kind": "x", "value": "1"}).status_code == 400


def test_split_record_per_commitment(client):
    """כמה מספרי התחייבות בטופס: רשומה לכל אחד, עם כל המרכזיים, מסומנת לבדיקה (החלטה 26)."""
    form = make_form(commitment_numbers=[fv("12345678"), fv("87654321", REVIEW, "ספרה לא ברורה")])
    ids = db.save_extracted(form, "b1", 1)
    assert len(ids) == 2
    recs = [client.get(f"/api/commitments/{i}").json() for i in ids]
    assert [r["commitment_numbers"][0]["value"] for r in recs] == ["12345678", "87654321"]
    for r in recs:
        assert len(r["commitment_numbers"]) == 1
        assert [n["value"] for n in r["central_numbers"]] == ["947468", "947469"]
        assert r["commitment_numbers"][0]["status"] == "review" and r["needs_review"]
        assert "נמצאו 2 מספרי התחייבות" in r["commitment_numbers"][0]["review_reason"]
        assert (r["source_page"], r["last_name"]["value"]) == (1, "כהן")
    assert recs[1]["commitment_numbers"][0]["review_reason"].startswith("ספרה לא ברורה")


def test_single_commitment_not_split(client):
    """מספר התחייבות אחד או בלי מספר: רשומה אחת, בלי סימון פיצול."""
    one = db.save_extracted(make_form(), "b1", 1)
    none = db.save_extracted(make_form(commitment_numbers=[]), "b1", 2)
    assert len(one) == len(none) == 1
    r = client.get(f"/api/commitments/{one[0]}").json()
    assert r["commitment_numbers"][0]["status"] == "ok"


def test_one_commitment_number_per_record(client):
    """אי אפשר להוסיף מספר התחייבות שני; לרשומה בלי מספר אפשר להוסיף אחד."""
    rid = db.save_form(make_form(), "b1", 1)
    res = client.post(f"/api/commitments/{rid}/numbers", json={"kind": "commitment", "value": "11112222"})
    assert res.status_code == 400
    empty = db.save_form(make_form(commitment_numbers=[]), "b1", 2)
    res = client.post(f"/api/commitments/{empty}/numbers", json={"kind": "commitment", "value": "11112222"})
    assert res.status_code == 200 and len(res.json()["commitment_numbers"]) == 1


def test_delete_record(client):
    """מחיקת רשומה מוחקת גם את המספרים; רשומת דוגמה לא נמחקת."""
    rid = db.save_form(make_form(), "b1", 1)
    assert client.delete(f"/api/commitments/{rid}").status_code == 204
    assert client.get(f"/api/commitments/{rid}").status_code == 404
    assert client.delete(f"/api/commitments/{rid}").status_code == 404
    sample = db.save_form(make_form(), None, 1, kind=RecordKind.sample.value)
    assert client.delete(f"/api/commitments/{sample}").status_code == 403


def test_add_sibling_from_same_page(client):
    """רשומה נוספת מאותו עמוד: אותם פרטים, מיקומים ומספרים מרכזיים, בלי מספר התחייבות, ממתינה ולבדיקה."""
    form = make_form()
    form.id_number.box = [0.1, 0.2, 0.3, 0.25]
    rid = db.save_form(form, "b1", 2)
    client.post(f"/api/commitments/{rid}/approve")
    r = client.post(f"/api/commitments/{rid}/sibling")
    assert r.status_code == 201
    new = r.json()
    assert new["id"] != rid and (new["batch_id"], new["source_file"], new["source_page"]) == ("b1", 2, 1)
    assert new["id_number"]["value"] == "011223344" and new["id_number"]["box"] == [0.1, 0.2, 0.3, 0.25]
    assert [n["value"] for n in new["central_numbers"]] == ["947468", "947469"]
    assert new["commitment_numbers"] == [] and new["needs_review"] and new["state"] == "pending"
    assert client.get(f"/api/commitments/{rid}").json()["state"] == "approved"  # המקור לא השתנה
    sample = db.save_form(make_form(), None, 1, kind=RecordKind.sample.value)
    assert client.post(f"/api/commitments/{sample}/sibling").status_code == 403


def test_confirm_field_clears_flag_even_if_check_fails(client):
    """אישור שדה: הכתום יורד גם בת"ז עם ספרת ביקורת שגויה; הרשומה נשארת ממתינה."""
    rid = db.save_form(make_form(id_number=fv("11223345", REVIEW, "ספרת ביקורת לא תקינה")), "b1", 1)
    r = client.post(f"/api/commitments/{rid}/fields/id_number/confirm").json()
    assert r["id_number"]["status"] == "ok" and r["id_number"]["value"] == "11223345"
    assert r["state"] == "pending"


def test_confirm_all_fields_makes_record_safe(client):
    """אחרי אישור השמות (השדות הכתומים היחידים), הרשומה נספרת כבטוחה."""
    rid = db.save_form(make_form(), "b1", 1)
    for field in ("first_name", "last_name"):
        r = client.post(f"/api/commitments/{rid}/fields/{field}/confirm").json()
    assert r["needs_review"] is False
    assert client.post("/api/commitments/approve-safe").json() == {"approved": 1}


def test_confirm_on_approved_record_keeps_it_approved(client):
    """אישור שדה ברשומה שכבר אושרה לא מחזיר אותה לממתין (בניגוד לתיקון)."""
    rid = db.save_form(make_form(), "b1", 1)
    client.post(f"/api/commitments/{rid}/approve")
    r = client.post(f"/api/commitments/{rid}/fields/first_name/confirm").json()
    assert r["state"] == "approved" and r["first_name"]["status"] == "ok"


def test_confirm_empty_field_and_number(client):
    """שדה ריק אי אפשר לאשר; מספר מסומן מאושר ויורד ממנו הכתום."""
    rid = db.save_form(make_form(sender=fv(None, FieldStatus.not_found),
                                 central_numbers=[fv("94747", REVIEW, "קצר")]), "b1", 1)
    assert client.post(f"/api/commitments/{rid}/fields/sender/confirm").status_code == 400
    num = client.get(f"/api/commitments/{rid}").json()["central_numbers"][0]
    r = client.post(f"/api/commitments/{rid}/numbers/{num['id']}/confirm").json()
    assert r["central_numbers"][0]["status"] == "ok"
    assert client.post(f"/api/commitments/{rid}/fields/nope/confirm").status_code == 400


def test_approve_and_edit_returns_to_pending(client):
    """אישור רשומה; תיקון אחרי אישור מחזיר אותה ל'ממתין'."""
    rid = db.save_form(make_form(), "b1", 1)
    r = client.post(f"/api/commitments/{rid}/approve").json()
    assert r["state"] == "approved" and r["approved_at"]
    r = client.patch(f"/api/commitments/{rid}/fields/last_name", json={"value": "לוי"}).json()
    assert r["state"] == "pending" and r["approved_at"] is None


def test_approve_safe_only_all_ok(client):
    """'אשר את כל הבטוחות' מאשר רק רשומות שכל השדות בהן ok."""
    safe = make_form(first_name=fv("א"), last_name=fv("ב"))
    s1 = db.save_form(safe, "b1", 1)
    s2 = db.save_form(make_form(), "b1", 2)
    s3 = db.save_form(make_form(first_name=fv("א"), last_name=fv("ב"), commitment_numbers=[]), "b1", 3)
    assert client.post("/api/commitments/approve-safe").json() == {"approved": 1}
    states = {i: client.get(f"/api/commitments/{i}").json()["state"] for i in (s1, s2, s3)}
    assert states == {s1: "approved", s2: "pending", s3: "pending"}


def test_list_order_latest_upload_then_pages(client):
    """ההעלאה האחרונה למעלה; בתוכה לפי סדר העמודים, ורשומה שנוספה ידנית מיד אחרי המקור שלה."""
    first = {p: db.save_form(make_form(source_page=p), "old", 1) for p in (3, 1, 2)}
    later = [db.save_form(make_form(source_page=p), "new", 1) for p in (2, 1)]
    added = client.post(f"/api/commitments/{first[1]}/sibling").json()["id"]
    ids = [i["id"] for i in client.get("/api/commitments").json()["items"]]
    assert ids == [later[1], later[0], first[1], added, first[2], first[3]]


def test_search_and_filters(client):
    """חיפוש בשם, בת"ז ובמספרים; סינון לפי גורם, סטטוס ו'רק לבדיקה'; ספירה."""
    a = db.save_form(make_form(), "b1", 1)
    db.save_form(make_form(last_name=fv("לוי"), sender=fv("לאומית"),
                           central_numbers=[fv("950001")]), "b1", 2)
    db.save_failure("b1", 1, 3, "bad_page", "פגום")
    client.post(f"/api/commitments/{a}/approve")

    def ids(**params):
        return [i["id"] for i in client.get("/api/commitments", params=params).json()["items"]]

    assert ids(q="כהן") == [a]
    assert ids(q="947469") == [a]
    assert len(ids(q="950001")) == 1 and a not in ids(q="950001")
    assert len(ids(sender="לאומית")) == 1
    assert ids(state="approved") == [a]
    body = client.get("/api/commitments").json()
    assert body["total"] == 3
    assert body["counts"] == {"pending": 1, "approved": 1, "failed": 1}
    assert body["pending_review"] == 1
    assert ids(q="%") == []


def test_sample_records_are_read_only(client):
    """רשומת דוגמה נראית לכולם אבל אי אפשר לשנות אותה, ואיפוס לא מוחק אותה."""
    rid = db.save_form(make_form(), None, 1, kind=RecordKind.sample.value)
    assert client.get(f"/api/commitments/{rid}").status_code == 200
    assert client.post(f"/api/commitments/{rid}/approve").status_code == 403
    db.reset_demo()
    assert client.get(f"/api/commitments/{rid}").status_code == 200


def test_test_records_are_hidden(client):
    """רשומות בדיקה לא נראות במאגר המשותף (כלל הנראות)."""
    rid = db.save_form(make_form(), None, 1, kind=RecordKind.test.value)
    assert client.get(f"/api/commitments/{rid}").status_code == 404


def test_cleanup_old_and_overflow(monkeypatch):
    """ניקוי: רשומות משתמש ישנות נמחקות, ומעל התקרה נשארות רק החדשות; דוגמה נשארת."""
    monkeypatch.setattr(db, "DEMO_MAX_RECORDS", 2)
    old = db.save_form(make_form(), "b", 1)
    sample = db.save_form(make_form(), None, 1, kind=RecordKind.sample.value)
    with Session(db.get_engine()) as s:
        for rid in (old, sample):
            c = s.get(Commitment, rid)
            c.created_at = c.created_at - timedelta(days=8)
            s.add(c)
        s.commit()
    keep = [db.save_form(make_form(), "b", i) for i in range(3)]
    assert db.cleanup_demo() == 2
    with Session(db.get_engine()) as s:
        left = set(s.exec(select(Commitment.id)).all())
    assert left == {sample, keep[1], keep[2]}


def test_saved_record_survives_new_connection(test_schema):
    """קריטריון הסיום: רשומה שנוצרה, תוקנה ואושרה חוזרת מחיבור חדש לגמרי (כמו הפעלה מחדש)."""
    rid = db.save_form(make_form(), "b1", 1)
    db.correct_field(rid, "last_name", "לוי")
    db.approve(rid)

    real = db._engine
    db._engine = db.make_engine(os.environ["DATABASE_URL"], test_schema)
    try:
        r = db.get_commitment(rid)
    finally:
        db._engine.dispose()
        db._engine = real
    assert r["state"] == "approved"
    assert r["last_name"]["value"] == "לוי" and r["last_name"]["status"] == "ok"
    assert [n["value"] for n in r["central_numbers"]] == ["947468", "947469"]
