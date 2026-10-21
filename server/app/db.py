import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import delete, event, exists, func, inspect, or_, text
from sqlmodel import Session, SQLModel, create_engine, select

from .schema import (SINGLE_FIELDS, Commitment, CommitmentNumber, ExtractedForm, FieldStatus,
                     FieldValue, RecordKind, RecordState)
from .validation import check_correction, check_number_correction

load_dotenv()
log = logging.getLogger("medextract")

DEMO_MAX_RECORDS = 1000
DEMO_MAX_AGE_DAYS = 7
VISIBLE_KINDS = (RecordKind.sample.value, RecordKind.user.value)
NUMBER_KINDS = ("central", "commitment")

_engine = None


class RecordError(Exception):
    """פעולה על רשומה שנכשלה: קוד HTTP והודעה בעברית."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def make_engine(url: str, schema: str | None = None):
    """יוצרת חיבור למסד; schema = סכמה נפרדת (לבדיקות)."""
    engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                           connect_args={"connect_timeout": 10})
    if schema:
        @event.listens_for(engine, "connect")
        def _set_path(conn, _):
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}"')
            conn.commit()
    return engine


def get_engine():
    """מחזירה חיבור יחיד למסד לפי DATABASE_URL."""
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL לא מוגדר ב-.env")
        _engine = make_engine(url)
    return _engine


def ping() -> bool:
    """בודקת שהמסד עונה (SELECT 1)."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def _session() -> Session:
    """סשן שבו האובייקטים נשארים קריאים אחרי commit."""
    return Session(get_engine(), expire_on_commit=False)


# עמודות שנוספו אחרי שהטבלאות כבר נוצרו במסד (create_all לא משנה טבלה קיימת)
ADDED_COLUMNS = {
    "commitments": ["model_used"] + [f"{f}_box" for f in SINGLE_FIELDS],
    "commitment_numbers": ["box"],
}


def init() -> None:
    """יוצרת את הטבלאות אם הן לא קיימות, ומוסיפה עמודות חדשות לטבלה קיימת."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    insp = inspect(engine)
    for table, columns in ADDED_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for col in columns:
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR"))


def _now() -> datetime:
    """הזמן הנוכחי ב-UTC."""
    return datetime.now(timezone.utc)


# ---------- כלל הנראות וההרשאה (המקום היחיד; התחברות תתווסף כאן) ----------

def visible(stmt):
    """בדמו המשותף כל המבקרים רואים את רשומות הדוגמה והמשתמש (החלטה 25)."""
    return stmt.where(Commitment.kind.in_(VISIBLE_KINDS))


def _editable(s: Session, record_id: str) -> Commitment:
    """מחזירה רשומה שמותר לשנות, או שגיאה בעברית."""
    c = s.exec(visible(select(Commitment).where(Commitment.id == record_id))).first()
    if not c:
        raise RecordError(404, "הרשומה לא נמצאה.")
    if c.kind == RecordKind.sample.value:
        raise RecordError(403, "רשומת דוגמה היא לקריאה בלבד.")
    if c.state == RecordState.failed.value:
        raise RecordError(400, "עמוד שנכשל בעיבוד אי אפשר לתקן או לאשר.")
    return c


# ---------- המרה בין רשומה לטבלאות ----------

def _set_field(c: Commitment, name: str, fv: FieldValue, keep_raw: bool = False) -> None:
    """כותבת שדה בודד לעמודות שלו."""
    setattr(c, f"{name}_value", fv.value)
    if not keep_raw:
        setattr(c, f"{name}_raw", fv.raw_value)
    setattr(c, f"{name}_status", fv.status.value)
    setattr(c, f"{name}_reason", fv.review_reason)
    if not keep_raw:  # בתיקון הערך המקום בעמוד לא משתנה
        setattr(c, f"{name}_box", _box_str(fv.box))


def _box_str(box: list[float] | None) -> str | None:
    """מיקום בעמוד לשמירה במסד: "x0,y0,x1,y1"."""
    return ",".join(str(v) for v in box) if box else None


def _box_list(box: str | None) -> list[float] | None:
    """מיקום בעמוד כפי שנשלח ללקוח: [x0, y0, x1, y1]."""
    return [float(v) for v in box.split(",")] if box else None


def _numbers(s: Session, record_id: str) -> list[CommitmentNumber]:
    """המספרים של רשומה, לפי סוג וסדר."""
    return list(s.exec(select(CommitmentNumber).where(CommitmentNumber.commitment_id == record_id)
                       .order_by(CommitmentNumber.kind, CommitmentNumber.position)))


def _refresh(c: Commitment, numbers: list[CommitmentNumber]) -> None:
    """מעדכנת 'דורש בדיקה' (שדה שאינו ok, או רשימת מספרים ריקה) וזמן עדכון."""
    ok = FieldStatus.ok.value
    c.needs_review = (any(getattr(c, f"{f}_status") != ok for f in SINGLE_FIELDS)
                      or any(n.status != ok for n in numbers)
                      or {n.kind for n in numbers} != set(NUMBER_KINDS))
    c.updated_at = _now()


def _to_dict(c: Commitment, numbers: list[CommitmentNumber]) -> dict:
    """רשומה כפי שהיא מוחזרת ללקוח."""
    out = c.model_dump(exclude={"model_used"}
                       | {f"{f}_{p}" for f in SINGLE_FIELDS for p in ("value", "raw", "status", "reason", "box")})
    for f in SINGLE_FIELDS:
        out[f] = {"value": getattr(c, f"{f}_value"), "raw_value": getattr(c, f"{f}_raw"),
                  "status": getattr(c, f"{f}_status"), "review_reason": getattr(c, f"{f}_reason"),
                  "box": _box_list(getattr(c, f"{f}_box"))}
    for kind in NUMBER_KINDS:
        out[f"{kind}_numbers"] = [
            {"id": n.id, "value": n.value, "raw_value": n.raw_value, "status": n.status,
             "review_reason": n.review_reason, "box": _box_list(n.box)} for n in numbers if n.kind == kind]
    return out


# ---------- שמירה מהצינור ----------

def save_form(form: ExtractedForm, batch_id: str | None, source_file: int | None,
              kind: str = RecordKind.user.value) -> str:
    """שומרת רשומה שחולצה, עם המספרים שלה, ומחזירה את המזהה."""
    with _session() as s:
        c = Commitment(kind=kind, batch_id=batch_id, source_file=source_file,
                       source_page=form.source_page, page_rotation=form.page_rotation, model_used=form.model)
        for f in SINGLE_FIELDS:
            _set_field(c, f, getattr(form, f))
        numbers = [CommitmentNumber(commitment_id=c.id, kind=k, position=i, value=fv.value,
                                    raw_value=fv.raw_value, status=fv.status.value,
                                    review_reason=fv.review_reason, box=_box_str(fv.box))
                   for k in NUMBER_KINDS for i, fv in enumerate(getattr(form, f"{k}_numbers"))]
        _refresh(c, numbers)
        s.add(c)
        s.flush()
        s.add_all(numbers)
        s.commit()
        return c.id


def split_commitments(form: ExtractedForm) -> list[ExtractedForm]:
    """רשומה לכל מספר התחייבות, עם כל המספרים המרכזיים (החלטה 26). פיצול מסומן לבדיקה."""
    numbers = form.commitment_numbers
    if len(numbers) <= 1:
        return [form]
    note = f"בטופס נמצאו {len(numbers)} מספרי התחייבות, ונוצרה רשומה לכל אחד"
    out = []
    for n in numbers:
        reason = " · ".join(r for r in (n.review_reason, note) if r)
        flagged = n.model_copy(update={"status": FieldStatus.review, "review_reason": reason})
        out.append(form.model_copy(update={"commitment_numbers": [flagged]}))
    return out


def save_extracted(form: ExtractedForm, batch_id: str | None, source_file: int | None,
                   kind: str = RecordKind.user.value) -> list[str]:
    """שומרת עמוד שחולץ: רשומה לכל התחייבות. מחזירה את המזהים."""
    return [save_form(f, batch_id, source_file, kind) for f in split_commitments(form)]


def save_failure(batch_id: str | None, source_file: int | None, source_page: int | None,
                 code: str, message: str) -> str:
    """שומרת עמוד שנכשל בעיבוד כרשומה בסטטוס 'נכשל' (החלטה 28)."""
    with _session() as s:
        c = Commitment(batch_id=batch_id, source_file=source_file, source_page=source_page,
                       state=RecordState.failed.value, error_code=code, error_message=message)
        s.add(c)
        s.commit()
        return c.id


def delete_quota_failures(batch_id: str) -> int:
    """לפני המשך העלאה: מוחקת עמודים שסומנו 'נכשל' בגלל מכסה, כי הם יעובדו מחדש."""
    with _session() as s:
        ids = s.exec(visible(select(Commitment.id)).where(
            Commitment.batch_id == batch_id, Commitment.state == RecordState.failed.value,
            Commitment.error_code == "quota")).all()
        n = _delete_ids(s, list(ids))
        s.commit()
    return n


def save_page(batch_id: str, result) -> str:
    """שומרת תוצאת עמוד מהצינור: רשומה לכל התחייבות (מוחזרת הראשונה), או רשומת כשל."""
    if result.ok:
        return save_extracted(result.form, batch_id, result.file_index)[0]
    return save_failure(batch_id, result.file_index, result.page, result.error_code, result.error_message)


# ---------- קריאה, חיפוש וסינון ----------

def list_commitments(q: str | None = None, sender: str | None = None, state: str | None = None,
                     needs_review: bool | None = None, batch_id: str | None = None,
                     limit: int = 200, offset: int = 0) -> dict:
    """רשימת רשומות עם חיפוש טקסט, סינון וספירה לפי סטטוס."""
    stmt = visible(select(Commitment))
    if q and q.strip():
        q = q.strip()
        stmt = stmt.where(or_(
            Commitment.first_name_value.icontains(q, autoescape=True),
            Commitment.last_name_value.icontains(q, autoescape=True),
            Commitment.id_number_value.icontains(q, autoescape=True),
            exists().where(CommitmentNumber.commitment_id == Commitment.id,
                           CommitmentNumber.value.icontains(q, autoescape=True)),
        ))
    if sender:
        stmt = stmt.where(Commitment.sender_value == sender)
    if state:
        stmt = stmt.where(Commitment.state == state)
    if needs_review is not None:
        stmt = stmt.where(Commitment.needs_review == needs_review)
    if batch_id:
        stmt = stmt.where(Commitment.batch_id == batch_id)

    with _session() as s:
        total = s.exec(select(func.count()).select_from(stmt.subquery())).one()
        rows = list(s.exec(stmt.order_by(Commitment.created_at.desc(), Commitment.batch_id,
                                         Commitment.source_file, Commitment.source_page)
                           .limit(limit).offset(offset)))
        nums = list(s.exec(select(CommitmentNumber)
                           .where(CommitmentNumber.commitment_id.in_([c.id for c in rows]))
                           .order_by(CommitmentNumber.kind, CommitmentNumber.position)))
        counts = dict(s.exec(visible(select(Commitment.state, func.count()))
                             .group_by(Commitment.state)).all())
        to_review = s.exec(visible(select(func.count()).select_from(Commitment)).where(
            Commitment.state == RecordState.pending.value, Commitment.needs_review == True)).one()  # noqa: E712
    by_record = {}
    for n in nums:
        by_record.setdefault(n.commitment_id, []).append(n)
    return {
        "total": total,
        "counts": {st.value: counts.get(st.value, 0) for st in RecordState},
        "pending_review": to_review,
        "items": [_to_dict(c, by_record.get(c.id, [])) for c in rows],
    }


def get_commitment(record_id: str) -> dict:
    """רשומה אחת עם המספרים שלה."""
    with _session() as s:
        c = s.exec(visible(select(Commitment).where(Commitment.id == record_id))).first()
        if not c:
            raise RecordError(404, "הרשומה לא נמצאה.")
        return _to_dict(c, _numbers(s, record_id))


# ---------- תיקון ואישור ----------

def _after_change(s: Session, c: Commitment, action: str) -> dict:
    """אחרי תיקון: הרשומה חוזרת ל'ממתין', נשמרת, ונרשם לוג בלי תוכן."""
    c.state, c.approved_at = RecordState.pending.value, None
    numbers = _numbers(s, c.id)
    _refresh(c, numbers)
    s.add(c)
    s.commit()
    log.info("commitment=%s %s", c.id, action)
    return _to_dict(c, numbers)


def correct_field(record_id: str, field: str, value: str | None) -> dict:
    """מתקנת שדה בודד; הערך החדש עובר את בדיקות הקוד (אפשרות א')."""
    if field not in SINGLE_FIELDS:
        raise RecordError(400, "שדה לא מוכר.")
    with _session() as s:
        c = _editable(s, record_id)
        _set_field(c, field, check_correction(field, value), keep_raw=True)
        return _after_change(s, c, f"field={field} corrected")


CONFIRMED_REASON = "אושר ידנית"


def _after_confirm(s: Session, c: Commitment, action: str) -> dict:
    """אחרי אישור שדה: מעדכנת 'דורש בדיקה' ושומרת. מצב הרשומה (ממתין/אושר) לא משתנה."""
    numbers = _numbers(s, c.id)
    _refresh(c, numbers)
    s.add(c)
    s.commit()
    log.info("commitment=%s %s", c.id, action)
    return _to_dict(c, numbers)


def confirm_field(record_id: str, field: str) -> dict:
    """הבודקת אישרה שהערך בשדה נכון: הכתום יורד גם אם בדיקת הקוד לא עברה (האדם הוא הסמכות)."""
    if field not in SINGLE_FIELDS:
        raise RecordError(400, "שדה לא מוכר.")
    with _session() as s:
        c = _editable(s, record_id)
        if not getattr(c, f"{field}_value"):
            raise RecordError(400, "אין ערך לאשר. אפשר להקליד ערך בשדה.")
        setattr(c, f"{field}_status", FieldStatus.ok.value)
        setattr(c, f"{field}_reason", CONFIRMED_REASON)
        return _after_confirm(s, c, f"field={field} confirmed")


def confirm_number(record_id: str, number_id: int) -> dict:
    """הבודקת אישרה שמספר נכון: הכתום יורד."""
    with _session() as s:
        c = _editable(s, record_id)
        n = _number(s, c, number_id)
        n.status, n.review_reason = FieldStatus.ok.value, CONFIRMED_REASON
        s.add(n)
        s.flush()
        return _after_confirm(s, c, f"number={number_id} confirmed")


def _number(s: Session, c: Commitment, number_id: int) -> CommitmentNumber:
    """מספר ששייך לרשומה, או שגיאה."""
    n = s.get(CommitmentNumber, number_id)
    if not n or n.commitment_id != c.id:
        raise RecordError(404, "המספר לא נמצא ברשומה.")
    return n


def _apply_number(n: CommitmentNumber, value: str, sender: str | None) -> None:
    """כותבת ערך מספר שתוקן אחרי בדיקת קוד."""
    fv = check_number_correction(n.kind, value, sender)
    n.value, n.status, n.review_reason = fv.value, fv.status.value, fv.review_reason


def correct_number(record_id: str, number_id: int, value: str) -> dict:
    """מתקנת מספר קיים."""
    if not (value or "").strip():
        raise RecordError(400, "מספר ריק. כדי להסיר מספר יש למחוק אותו.")
    with _session() as s:
        c = _editable(s, record_id)
        n = _number(s, c, number_id)
        _apply_number(n, value, c.sender_value)
        s.add(n)
        return _after_change(s, c, f"number={number_id} corrected")


def add_number(record_id: str, kind: str, value: str) -> dict:
    """מוסיפה מספר שהמודל החמיץ."""
    if kind not in NUMBER_KINDS:
        raise RecordError(400, "סוג מספר לא מוכר.")
    if not (value or "").strip():
        raise RecordError(400, "מספר ריק.")
    with _session() as s:
        c = _editable(s, record_id)
        if kind == "commitment" and any(n.kind == kind for n in _numbers(s, c.id)):
            raise RecordError(400, "לכל רשומה יש מספר התחייבות אחד. אפשר לתקן את המספר הקיים.")
        last = s.exec(select(func.max(CommitmentNumber.position))
                      .where(CommitmentNumber.commitment_id == c.id, CommitmentNumber.kind == kind)).one()
        n = CommitmentNumber(commitment_id=c.id, kind=kind, position=(last or 0) + 1)
        _apply_number(n, value, c.sender_value)
        s.add(n)
        s.flush()
        return _after_change(s, c, f"number added kind={kind}")


def delete_number(record_id: str, number_id: int) -> dict:
    """מוחקת מספר שגוי מהרשומה."""
    with _session() as s:
        c = _editable(s, record_id)
        s.delete(_number(s, c, number_id))
        s.flush()
        return _after_change(s, c, f"number={number_id} deleted")


def delete_commitment(record_id: str) -> None:
    """מוחקת רשומה מיותרת (למשל מספר שנקרא בטעות כהתחייבות). רשומות דוגמה לא נמחקות."""
    with _session() as s:
        c = s.exec(visible(select(Commitment).where(Commitment.id == record_id))).first()
        if not c:
            raise RecordError(404, "הרשומה לא נמצאה.")
        if c.kind == RecordKind.sample.value:
            raise RecordError(403, "רשומת דוגמה היא לקריאה בלבד.")
        _delete_ids(s, [c.id])
        s.commit()
    log.info("commitment=%s deleted", record_id)


def approve(record_id: str) -> dict:
    """מאשרת רשומה (האדם הוא הסמכות: אפשר לאשר גם עם שדות לבדיקה)."""
    with _session() as s:
        c = _editable(s, record_id)
        c.state, c.approved_at = RecordState.approved.value, _now()
        s.add(c)
        s.commit()
        log.info("commitment=%s approved", c.id)
        return _to_dict(c, _numbers(s, c.id))


def approve_safe(batch_id: str | None = None) -> int:
    """מאשרת יחד את כל הרשומות הממתינות שכל השדות בהן ok."""
    stmt = visible(select(Commitment)).where(
        Commitment.kind == RecordKind.user.value, Commitment.state == RecordState.pending.value,
        Commitment.needs_review == False)  # noqa: E712
    if batch_id:
        stmt = stmt.where(Commitment.batch_id == batch_id)
    with _session() as s:
        rows = list(s.exec(stmt))
        for c in rows:
            c.state, c.approved_at = RecordState.approved.value, _now()
            s.add(c)
        s.commit()
    log.info("approved %d safe commitments", len(rows))
    return len(rows)


# ---------- ניקוי הדמו ----------

def _delete_ids(s: Session, ids: list[str]) -> int:
    """מוחקת רשומות לפי מזהים, עם המספרים שלהן."""
    if ids:
        s.exec(delete(CommitmentNumber).where(CommitmentNumber.commitment_id.in_(ids)))
        s.exec(delete(Commitment).where(Commitment.id.in_(ids)))
    return len(ids)


def cleanup_demo() -> int:
    """מוחקת רשומות משתמש בנות יותר מ-7 ימים, ושומרת לכל היותר 1,000 (נתוני דוגמה לא נמחקים)."""
    user = Commitment.kind == RecordKind.user.value
    with _session() as s:
        old = s.exec(select(Commitment.id).where(
            user, Commitment.created_at < _now() - timedelta(days=DEMO_MAX_AGE_DAYS))).all()
        extra = s.exec(select(Commitment.id).where(user).order_by(Commitment.created_at.desc())
                       .offset(DEMO_MAX_RECORDS)).all()
        n = _delete_ids(s, list(set(old) | set(extra)))
        s.commit()
    if n:
        log.info("cleanup removed %d demo records", n)
    return n


def reset_demo() -> int:
    """איפוס לפני הצגה: מוחקת את כל רשומות המשתמש והבדיקה, בלי לגעת בנתוני הדוגמה."""
    with _session() as s:
        ids = s.exec(select(Commitment.id).where(Commitment.kind != RecordKind.sample.value)).all()
        n = _delete_ids(s, list(ids))
        s.commit()
    return n


if __name__ == "__main__":
    if sys.argv[1:] == ["reset-demo"]:
        init()
        print(f"נמחקו {reset_demo()} רשומות דמו. נתוני הדוגמה נשארו.")
    else:
        print("שימוש: python -m app.db reset-demo")
