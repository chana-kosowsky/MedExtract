import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, commitments as api, getSenders } from "../api/client";
import type { Commitment, CommitmentList, ListParams, NumberKind, SingleField } from "../api/types";
import type { Notify } from "./useToast";

/** כמה רשומות נטענות בכל פעם (החדשות קודם). */
export const PAGE_SIZE = 50;

const EMPTY: CommitmentList = {
  total: 0,
  counts: { pending: 0, approved: 0, failed: 0 },
  pending_review: 0,
  items: [],
};

/** הרשומות מהמסד: טעינה, רענון, תיקון ואישור. כל שינוי מעדכן את השורה מיד. */
export function useCommitments(params: ListParams = {}, notify?: Notify) {
  const [data, setData] = useState<CommitmentList>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [senderList, setSenderList] = useState<{ name: string; short: string }[]>([]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const paramsKey = JSON.stringify(params);
  const latest = useRef(0);

  // חיפוש או סינון חדש מתחיל שוב מהעמוד הראשון
  useEffect(() => setLimit(PAGE_SIZE), [paramsKey]);

  // הרענון מביא את כל מה שכבר מוצג, כדי שעדכון חי לא יקצר את הרשימה
  const refresh = useCallback(async () => {
    const call = ++latest.current;
    try {
      const next = await api.list({ ...JSON.parse(paramsKey), limit });
      if (call === latest.current) setData(next);
    } catch (e) {
      if (call === latest.current) setError(e instanceof ApiError ? e.message : "טעינת הרשומות נכשלה.");
    } finally {
      if (call === latest.current) setLoading(false);
    }
  }, [paramsKey, limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    getSenders().then(setSenderList).catch(() => setSenderList([]));
  }, []);
  // השמות המלאים (להשלמה ולסינון), ושם קצר לכל גורם לתצוגה בטבלה
  const senders = useMemo(() => senderList.map((s) => s.name), [senderList]);
  const shortNames = useMemo(() => Object.fromEntries(senderList.map((s) => [s.name, s.short])), [senderList]);

  // מריצה שינוי בשרת, מחליפה את השורה בתשובה, מודיעה שנשמר, ומרעננת ספירות ברקע
  const mutate = useCallback(
    async (action: () => Promise<Commitment>, done: string | ((c: Commitment) => string)) => {
      setError(null);
      try {
        const updated = await action();
        setData((d) => ({ ...d, items: d.items.map((c) => (c.id === updated.id ? updated : c)) }));
        notify?.(typeof done === "string" ? done : done(updated));
        refresh();
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "השמירה נכשלה.");
        return false;
      }
    },
    [refresh, notify],
  );

  const actions = {
    correctField: (id: string, field: SingleField, value: string) =>
      mutate(
        () => api.correctField(id, field, value),
        (c) => (c[field].status === "review" ? "התיקון נשמר, אבל הערך עדיין לא עובר בדיקה" : "התיקון נשמר"),
      ),
    addNumber: (id: string, kind: NumberKind, value: string) =>
      mutate(() => api.addNumber(id, kind, value), "המספר נוסף"),
    correctNumber: (id: string, numberId: number, value: string) =>
      mutate(() => api.correctNumber(id, numberId, value), "התיקון נשמר"),
    deleteNumber: (id: string, numberId: number) => mutate(() => api.deleteNumber(id, numberId), "המספר נמחק"),
    confirmField: (id: string, field: SingleField) => mutate(() => api.confirmField(id, field), "השדה אושר"),
    confirmNumber: (id: string, numberId: number) => mutate(() => api.confirmNumber(id, numberId), "המספר אושר"),
    approve: (id: string) => mutate(() => api.approve(id), "הרשומה אושרה"),
    remove: async (id: string) => {
      setError(null);
      try {
        await api.remove(id);
        setData((d) => ({ ...d, items: d.items.filter((c) => c.id !== id) }));
        notify?.("הרשומה נמחקה");
        refresh();
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "המחיקה נכשלה.");
        return false;
      }
    },
    // רשומה נוספת מאותו עמוד: נכנסת מיד אחרי המקור, ומוחזר המזהה שלה כדי לפתוח אותה
    addSibling: async (id: string) => {
      setError(null);
      try {
        const added = await api.addSibling(id);
        setData((d) => {
          const at = d.items.findIndex((c) => c.id === id) + 1;
          return { ...d, total: d.total + 1, items: [...d.items.slice(0, at), added, ...d.items.slice(at)] };
        });
        notify?.("נוספה רשומה מאותו עמוד. אפשר להקליד את מספר ההתחייבות");
        refresh();
        return added.id;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "ההוספה נכשלה.");
        return null;
      }
    },
    approveSafe: async () => {
      setError(null);
      try {
        const { approved } = await api.approveSafe();
        notify?.(approved ? `אושרו ${approved} רשומות שכל השדות בהן תקינים` : "אין רשומות בטוחות לאישור");
        await refresh();
        return approved;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "האישור נכשל.");
        return 0;
      }
    },
  };

  const showMore = useCallback(() => {
    setLoading(true);
    setLimit((n) => n + PAGE_SIZE);
  }, []);

  return {
    ...data,
    loading,
    error,
    senders,
    shortNames,
    refresh,
    showMore,
    showError: setError,
    clearError: () => setError(null),
    actions,
  };
}

export type RecordActions = ReturnType<typeof useCommitments>["actions"];
