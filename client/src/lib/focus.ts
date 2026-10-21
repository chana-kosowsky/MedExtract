import type { Box, Commitment, FieldValue, SingleField } from "../api/types";

/** השדה שמסומן בטופס בלוח הצד: שדה בודד, או מספר לפי המזהה שלו. */
export type FocusKey = SingleField | `n${number}`;

/** המיקום בעמוד של שדה או מספר ברשומה, אם ידוע. */
export function boxOf(r: Commitment, key: FocusKey | null): Box | null {
  if (!key) return null;
  if (key.startsWith("n")) {
    const id = Number(key.slice(1));
    return [...r.central_numbers, ...r.commitment_numbers].find((n) => n.id === id)?.box ?? null;
  }
  return r[key as SingleField].box ?? null;
}

/** השדה הראשון שדורש בדיקה ויש לו מיקום, לפי סדר השדות במסך (כדי לסמן אותו כשהלוח נפתח). */
export function firstFlagged(r: Commitment, order: (SingleField | "central" | "commitment")[]): FocusKey | null {
  const flagged = (f: FieldValue) => f.status === "review" && !!f.box;
  for (const key of order) {
    if (key === "central" || key === "commitment") {
      const n = (key === "central" ? r.central_numbers : r.commitment_numbers).find(flagged);
      if (n) return `n${n.id}`;
    } else if (flagged(r[key])) {
      return key;
    }
  }
  return null;
}

/** מרווח קבוע סביב המיקום, כדי שהמסגרת תכלול גם את הספרות שמודפסות מתחת לברקוד או מעליו. */
export function padded([x0, y0, x1, y1]: Box): Box {
  const dy = 0.025;
  const dx = 0.01;
  return [Math.max(0, x0 - dx), Math.max(0, y0 - dy), Math.min(1, x1 + dx), Math.min(1, y1 + dy)];
}
