// טיפוסי הנתונים, תואמים לתשובות השרת (server/app/db.py, pipeline.py)

export type FieldStatus = "ok" | "review" | "not_found";
export type RecordState = "pending" | "approved" | "failed";
export type JobState = "running" | "done" | "cancelled" | "quota_stopped" | "error";
export type SingleField = "first_name" | "last_name" | "id_number" | "received_date" | "sender";
export type NumberKind = "central" | "commitment";

/** מצב הכניסה: האם צריך להתחבר, מי מחובר, ופרטי משתמש הדמו להצגה (אם השרת מציג אותם). */
export interface Session {
  required: boolean;
  user: string | null;
  demo: { username: string; password: string } | null;
}

/** מיקום בעמוד [x0, y0, x1, y1], ביחס לגודל הדף (0-1). */
export type Box = [number, number, number, number];

export interface FieldValue {
  value: string | null;
  raw_value: string | null;
  status: FieldStatus;
  review_reason: string | null;
  box?: Box | null;
}

export interface NumberValue extends FieldValue {
  id: number;
}

export interface Commitment extends Record<SingleField, FieldValue> {
  id: string;
  kind: "sample" | "user" | "test";
  state: RecordState;
  needs_review: boolean;
  batch_id: string | null;
  source_file: number | null;
  source_page: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  central_numbers: NumberValue[];
  commitment_numbers: NumberValue[];
}

export interface CommitmentList {
  total: number;
  counts: Record<RecordState, number>;
  pending_review: number;
  items: Commitment[];
}

export interface ListParams {
  q?: string;
  sender?: string;
  state?: RecordState;
  needs_review?: boolean;
  batch_id?: string;
}

export interface PageResult {
  file_index: number;
  page: number;
  ok: boolean;
  error_code: string | null;
  error_message: string | null;
  record_id: string | null;
  save_error: string | null;
}

export interface Job {
  id: string;
  batch_id: string;
  state: JobState;
  message: string | null;
  total_pages: number;
  processed: number;
  succeeded: number;
  failed: number;
  elapsed_seconds: number;
  results: PageResult[];
}
