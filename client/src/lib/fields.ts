// השדות בסדר של האתגר, עם הכותרות בעברית, והסבר לשדה לא בטוח

import type { Commitment, FieldValue, NumberKind, SingleField } from "../api/types";

/** האם לא חולץ מהעמוד אף שדה ואף מספר (אז מוצגת הודעה אחת במקום שבעה תאים ריקים). */
export function nothingExtracted(r: Commitment): boolean {
  const fields: SingleField[] = ["first_name", "last_name", "id_number", "received_date", "sender"];
  return fields.every((f) => !r[f].value) && r.central_numbers.length === 0 && r.commitment_numbers.length === 0;
}

// הסיבות הקבועות שהקוד כותב (server/app/validation.py, barcodes.py, db.py). כל טקסט אחר הוא הסבר חופשי של המודל
const CODE_REASONS = [
  "התאמה חלקית לרשימה", "כמה גורמים אפשריים", "גורם לא ברשימה", "תו לא ספרתי", "ת\"ז", "ספרת ביקורת",
  "השנה לא כתובה", "פורמט תאריך", "תאריך לא קיים", "תאריך עתידי", "תאריך ישן", "חותמת ותאריך",
  "מספר מרכזי אינו", "התווית בטופס", "אות או תו", "מספר התחייבות קצר", "אין תווית ליד המספר", "תווית 'דגימה'",
  "מופיע גם כמרכזי", "זהה לת", "נלקח מהברקוד", "לא נמצאה מדבקה", "נמצא בברקוד", "הועבר מרשימת",
  "יותר ממספר מרכזי", "בטופס נמצאו",
];
const NAME_REASON = "שם, אין בדיקה אוטומטית";
const MAX_READ_SHOWN = 30; // "נקרא בטופס" ארוך יותר מוצג רק בלוח הצד

/** אותיות וספרות בלבד, כדי ש-18.06.2026 ו-18/06/2026 ייחשבו אותו ערך. */
const bare = (s: string) => s.replace(/[^\p{L}\p{N}]/gu, "");

/** הסבר קצר לבועה על שדה לא בטוח: סיבה קבועה אחת מהקוד (או "לא בטוח בקריאה"), ומה נקרא בטופס אם שונה. */
export function reviewTip(field: FieldValue): string | null {
  if (field.status === "ok") return null;
  if (field.status === "not_found") return "לא נמצא בטופס. אפשר להשלים ידנית.";
  const parts = (field.review_reason ?? "").split(/[;·]/).map((p) => p.trim());
  const lines: string[] = [];
  if (parts.includes(NAME_REASON)) lines.push("שם: כדאי לבדוק מול הטופס");
  const code = parts.find((p) => CODE_REASONS.some((c) => p.startsWith(c)));
  if (code) lines.push(code);
  if (lines.length === 0) lines.push("לא בטוח בקריאה, כדאי לבדוק");
  const raw = field.raw_value;
  if (raw && raw.length <= MAX_READ_SHOWN && bare(raw) !== bare(field.value ?? "")) lines.push(`נקרא בטופס: ${raw}`);
  return lines.join(" · ");
}

/** ההסבר המלא (כולל הסבר המודל), ללוח הצד. null לשדה תקין או כשאין הסבר. */
export function fullReason(field: FieldValue): string | null {
  if (field.status !== "review" || !field.review_reason) return null;
  const raw = field.raw_value && bare(field.raw_value) !== bare(field.value ?? "") ? ` · נקרא בטופס: ${field.raw_value}` : "";
  return field.review_reason + raw;
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
