// סינון הרשומות: בדיקה אם יש סינון, והסינון שכל כרטיס סיכום מפעיל

import type { ListParams } from "../api/types";

export type CardKey = "total" | "approved" | "review" | "failed";

/** האם יש סינון פעיל כלשהו. */
export function hasFilters(f: ListParams): boolean {
  return Object.values(f).some((v) => v !== undefined && v !== "");
}

/** הסינון שמופעל בלחיצה על כרטיס סיכום (מצב ובדיקה בלבד; חיפוש וגורם נשמרים). */
export const CARD_FILTERS: Record<CardKey, Pick<ListParams, "state" | "needs_review">> = {
  total: { state: undefined, needs_review: undefined },
  approved: { state: "approved", needs_review: undefined },
  review: { state: "pending", needs_review: true },
  failed: { state: "failed", needs_review: undefined },
};

/** איזה כרטיס תואם לסינון הנוכחי (להדגשה). */
export function activeCard(f: ListParams): CardKey | null {
  const match = (Object.keys(CARD_FILTERS) as CardKey[]).find(
    (k) => CARD_FILTERS[k].state === f.state && CARD_FILTERS[k].needs_review === f.needs_review,
  );
  return match ?? null;
}
