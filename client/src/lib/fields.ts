// השדות בסדר של האתגר, עם הכותרות בעברית, והסבר לשדה לא בטוח

import type { Commitment, FieldValue, NumberKind, SingleField } from "../api/types";

/** האם לא חולץ מהעמוד אף שדה ואף מספר (אז מוצגת הודעה אחת במקום שבעה תאים ריקים). */
export function nothingExtracted(r: Commitment): boolean {
  const fields: SingleField[] = ["first_name", "last_name", "id_number", "received_date", "sender"];
  return fields.every((f) => !r[f].value) && r.central_numbers.length === 0 && r.commitment_numbers.length === 0;
}

/** הסבר לשדה לא בטוח: הסיבה, ומה נקרא בטופס אם שונה מהערך. null לשדה תקין. */
export function reviewTip(field: FieldValue): string | null {
  if (field.status === "ok") return null;
  if (field.status === "not_found") return "לא נמצא בטופס. אפשר להשלים ידנית.";
  const read = field.raw_value && field.raw_value !== field.value ? `נקרא בטופס: ${field.raw_value}` : null;
  return [field.review_reason, read].filter(Boolean).join(" · ") || "לא בטוח, כדאי לבדוק";
}

export type Column =
  | { kind: "field"; key: SingleField; label: string; placeholder?: string }
  | { kind: "numbers"; key: NumberKind; label: string; max?: number };

export const COLUMNS: Column[] = [
  { kind: "field", key: "first_name", label: "שם פרטי" },
  { kind: "field", key: "last_name", label: "שם משפחה" },
  { kind: "field", key: "id_number", label: "ת״ז" },
  { kind: "numbers", key: "central", label: "מספר מרכזי" },
  { kind: "field", key: "received_date", label: "תאריך קבלה", placeholder: "DD/MM/YYYY" },
  { kind: "field", key: "sender", label: "גורם שולח" },
  // רשומה לכל התחייבות (החלטה 26): מספר התחייבות אחד לרשומה
  { kind: "numbers", key: "commitment", label: "מספר התחייבות", max: 1 },
];
