import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import DateTime
from sqlmodel import Field as DBField
from sqlmodel import SQLModel


# ---------- מה שהמודל מחזיר (בלי סטטוס: את הסטטוס קובע הקוד) ----------

class ModelField(BaseModel):
    """שדה אחד כפי שהמודל קרא אותו."""
    text: str | None = Field(None, description="הטקסט בדיוק כפי שכתוב בטופס, בלי תיקונים. null אם השדה לא נמצא")
    confidence: float = Field(0.0, ge=0, le=1, description="ביטחון המודל בקריאה, 0 עד 1")
    unclear_reason: str | None = Field(None, description="אם הקריאה לא ודאית: למה (כתב יד, מדבקה חתוכה, טשטוש)")
    box_2d: list[float] | None = Field(None, description="מיקום הערך בעמוד: [ymin, xmin, ymax, xmax] בסקלה 0-1000")


class ModelNumber(ModelField):
    """מספר מרכזי או מספר התחייבות, עם התווית שליד המספר בטופס."""
    label: str | None = Field(None, description="התווית שליד המספר בטופס, למשל: מרכזי, התחייבות, דרישה, דגימה, אסמכתא")


class ModelOutput(BaseModel):
    """התשובה המלאה של המודל לעמוד אחד."""
    page_rotation: int = Field(0, description="כמה מעלות הדף מסובב: 0, 90, 180 או 270")
    first_name: ModelField
    last_name: ModelField
    id_number: ModelField
    central_numbers: list[ModelNumber] = Field(default_factory=list)
    received_date_stamp: ModelField = Field(description="תאריך מחותמת 'התקבל'")
    received_date_handwritten: ModelField = Field(description="תאריך בכתב יד מתחת למספר המרכזי בלבד")
    sender: ModelField = Field(description="הגורם השולח: קופת חולים או בית חולים, מתוך הרשימה")
    commitment_numbers: list[ModelNumber] = Field(default_factory=list)


# ---------- הרשומה הסופית (אחרי בדיקות בקוד) ----------

class FieldStatus(str, Enum):
    ok = "ok"
    review = "review"
    not_found = "not_found"


class FieldValue(BaseModel):
    """שדה אחד ברשומה הסופית: ערך, ערך כפי שנקרא, ביטחון, סטטוס וסיבה."""
    value: str | None = None
    raw_value: str | None = None
    confidence: float = 0.0
    status: FieldStatus = FieldStatus.not_found
    review_reason: str | None = None
    box: list[float] | None = None  # מיקום בעמוד [x0, y0, x1, y1] ביחס לגודל הדף (0-1); לא חלק מהתמונה


class ExtractedForm(BaseModel):
    """רשומה אחת לעמוד: שבעת השדות של האתגר, מספרים כרשימות."""
    form_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source_page: int | None = None
    first_name: FieldValue
    last_name: FieldValue
    id_number: FieldValue
    central_numbers: list[FieldValue] = Field(default_factory=list)
    received_date: FieldValue
    sender: FieldValue
    commitment_numbers: list[FieldValue] = Field(default_factory=list)
    page_rotation: int = 0
    model: str | None = None  # איזה מודל קרא את העמוד (למדידה בלבד, לא מוצג במסך)


# ---------- טבלאות המסד (החלטה 24) ----------

SINGLE_FIELDS = ("first_name", "last_name", "id_number", "received_date", "sender")


class RecordState(str, Enum):
    pending = "pending"
    approved = "approved"
    failed = "failed"


class RecordKind(str, Enum):
    sample = "sample"
    user = "user"
    test = "test"


def _now() -> datetime:
    """הזמן הנוכחי ב-UTC."""
    return datetime.now(timezone.utc)


def _time_field(**kw):
    """עמודת זמן עם אזור זמן."""
    return DBField(sa_type=DateTime(timezone=True), **kw)


class Commitment(SQLModel, table=True):
    """רשומת התחייבות: חמשת השדות הבודדים (ערך, כפי שנקרא, סטטוס, סיבה) וסטטוס כללי."""
    __tablename__ = "commitments"
    id: str = DBField(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    kind: str = DBField(default=RecordKind.user.value, index=True)
    state: str = DBField(default=RecordState.pending.value, index=True)
    needs_review: bool = True
    batch_id: str | None = DBField(default=None, index=True)
    source_file: int | None = None
    source_page: int | None = None
    page_rotation: int = 0
    error_code: str | None = None
    error_message: str | None = None
    model_used: str | None = None  # למדידה ולדוח בלבד; לא נשלח לממשק (החלטה 34)

    first_name_value: str | None = None
    first_name_raw: str | None = None
    first_name_status: str = FieldStatus.not_found.value
    first_name_reason: str | None = None
    last_name_value: str | None = None
    last_name_raw: str | None = None
    last_name_status: str = FieldStatus.not_found.value
    last_name_reason: str | None = None
    id_number_value: str | None = None
    id_number_raw: str | None = None
    id_number_status: str = FieldStatus.not_found.value
    id_number_reason: str | None = None
    received_date_value: str | None = None
    received_date_raw: str | None = None
    received_date_status: str = FieldStatus.not_found.value
    received_date_reason: str | None = None
    sender_value: str | None = DBField(default=None, index=True)
    sender_raw: str | None = None
    sender_status: str = FieldStatus.not_found.value
    sender_reason: str | None = None

    # מיקום כל שדה בעמוד, "x0,y0,x1,y1" ביחס לגודל הדף (ללוח הצד בלבד)
    first_name_box: str | None = None
    last_name_box: str | None = None
    id_number_box: str | None = None
    received_date_box: str | None = None
    sender_box: str | None = None

    created_at: datetime = _time_field(default_factory=_now, index=True)
    updated_at: datetime = _time_field(default_factory=_now)
    approved_at: datetime | None = _time_field(default=None)


class CommitmentNumber(SQLModel, table=True):
    """מספר אחד (מרכזי או התחייבות) עם סטטוס משלו, שייך לרשומה."""
    __tablename__ = "commitment_numbers"
    id: int | None = DBField(default=None, primary_key=True)
    commitment_id: str = DBField(foreign_key="commitments.id", index=True, ondelete="CASCADE")
    kind: str  # central / commitment
    position: int = 0
    value: str | None = DBField(default=None, index=True)
    raw_value: str | None = None
    status: str = FieldStatus.not_found.value
    review_reason: str | None = None
    box: str | None = None  # מיקום בעמוד, "x0,y0,x1,y1" ביחס לגודל הדף
