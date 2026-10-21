// עזרי תצוגה: זמן וגודל קובץ

/** שניות לתצוגה בפורמט דקות:שניות (2:05). */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** משך במילים: "40 שניות" מתחת לדקה, אחרת "כ-12 דקות". */
export function formatSpan(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} שניות` : `כ-${Math.round(s / 60)} דקות`;
}

/** גודל קובץ קריא (KB / MB). */
export function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
