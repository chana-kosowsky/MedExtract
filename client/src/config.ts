// קבועים של הממשק

/** מגבלות ההעלאה (זהות לשרת, server/app/pipeline.py). */
export const LIMITS = { maxFiles: 30, maxFileMB: 20, maxTotalMB: 50, maxPages: 30 };

/** סוגי הקבצים שאפשר לבחור. */
export const ACCEPTED_FILES = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";

/** כמה דקות לוקח להקליד טופס ידנית (לפי האתגר: 30 טפסים בשעה). */
export const MANUAL_MINUTES_PER_FORM = 2;

/** כל כמה זמן נבדקת התקדמות העיבוד. */
export const POLL_MS = 1500;
