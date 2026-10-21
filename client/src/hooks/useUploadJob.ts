import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, uploads, type ResumeInfo } from "../api/client";
import type { Job, PageResult } from "../api/types";
import { POLL_MS } from "../config";

/** מה שנשמר מהריצות הקודמות של אותה העלאה (לפני "המשך"). */
interface Carry {
  results: PageResult[];
  elapsed: number;
  total: number;
}

/** הודעת סיכום לפי הספירה המצטברת (השרת סופר רק את הריצה האחרונה). */
function summary(job: Job, succeeded: number, failed: number): string | null {
  if (job.state === "done") return `הסתיים: ${succeeded} עמודים עובדו, ${failed} נכשלו.`;
  if (job.state === "cancelled") return `העיבוד הופסק. ${succeeded} עמודים עובדו.`;
  return job.message;
}

/** העלאה ומעקב חי אחרי העיבוד: התחלה, התקדמות, מונה זמן, עצירה והמשך מהמקום שעצר. */
export function useUploadJob(onPageSaved?: () => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [carry, setCarry] = useState<Carry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(0);
  const seen = useRef(0);
  // הקבצים של כל העלאה בישיבה הזו, להצגת הטופס בלוח הצד (בזיכרון הדפדפן בלבד)
  const filesByBatch = useRef(new Map<string, File[]>());

  const running = job?.state === "running";

  // מעקב אחרי ההתקדמות בשרת
  useEffect(() => {
    if (!job || !running) return;
    const timer = setInterval(async () => {
      try {
        const next = await uploads.get(job.id);
        setError(null);
        setJob(next);
        if (next.results.length > seen.current) {
          seen.current = next.results.length;
          onPageSaved?.();
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          // השרת הופעל מחדש והעבודה אבדה; העמודים שעובדו כבר שמורים, ואפשר להמשיך מהמקום שעצר
          setJob((j) => (j ? { ...j, state: "cancelled" } : j));
          setError("העיבוד נקטע כי השרת הופעל מחדש. העמודים שעובדו נשמרו, ואפשר להמשיך מהמקום שעצר.");
          onPageSaved?.();
          return;
        }
        setError(
          e instanceof ApiError && e.status === 0
            ? "החיבור לשרת נקטע. מתבצע ניסיון חוזר…"
            : e instanceof ApiError
              ? e.message
              : "שגיאה במעקב אחרי העיבוד.",
        );
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [job?.id, running, onPageSaved]);

  // מונה זמן חי; בסוף העיבוד מוצג הזמן שמדד השרת
  useEffect(() => {
    if (!running) {
      setStopping(false);
      if (job) setElapsed(job.elapsed_seconds);
      return;
    }
    const tick = setInterval(() => setElapsed((Date.now() - startedAt.current) / 1000), 250);
    return () => clearInterval(tick);
  }, [running, job]);

  // התצוגה המצטברת: הריצות הקודמות + הריצה הנוכחית
  const view = useMemo<Job | null>(() => {
    if (!job) return null;
    const results = [...(carry?.results ?? []), ...job.results];
    const succeeded = results.filter((r) => r.ok).length;
    const failed = results.length - succeeded;
    return {
      ...job,
      results,
      total_pages: carry?.total ?? job.total_pages,
      processed: results.length,
      succeeded,
      failed,
      message: summary(job, succeeded, failed),
    };
  }, [job, carry]);

  const totalElapsed = (carry?.elapsed ?? 0) + elapsed;

  // אפשר להמשיך כשהעיבוד נעצר (עצירה או מכסה), הקבצים עדיין בדפדפן ונשארו עמודים
  const kept = view?.results.filter((r) => r.error_code !== "quota") ?? [];
  const remaining = view ? view.total_pages - kept.length : 0;
  const canResume =
    !!view && files.length > 0 && remaining > 0 && (view.state === "cancelled" || view.state === "quota_stopped");

  // שולחת לשרת ומחזירה את העבודה החדשה (או null בשגיאה)
  const send = useCallback(async (list: File[], resume?: ResumeInfo) => {
    setError(null);
    setSending(true);
    try {
      const next = await uploads.start(list, crypto.randomUUID(), resume);
      seen.current = 0;
      startedAt.current = Date.now();
      return next;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "ההעלאה נכשלה.");
      return null;
    } finally {
      setSending(false);
    }
  }, []);

  const start = useCallback(
    async (list: File[]) => {
      const next = await send(list);
      if (!next) return;
      filesByBatch.current.set(next.batch_id, list);
      setFiles(list);
      setCarry(null);
      setJob(next);
    },
    [send],
  );

  const resume = useCallback(async () => {
    if (!view || !canResume) return;
    const previous = { results: kept, elapsed: totalElapsed, total: view.total_pages };
    const next = await send(files, {
      batchId: view.batch_id,
      skip: kept.map((r) => ({ file: r.file_index, page: r.page })),
    });
    if (!next) return;
    setCarry(previous);
    setJob(next);
  }, [view, canResume, kept, totalElapsed, files, send]);

  // העצירה נקלטת מיד; השרת עוצר אחרי שהעמוד הנוכחי מסתיים
  const cancel = useCallback(async () => {
    if (!job) return;
    setStopping(true);
    setJob(await uploads.cancel(job.id).catch(() => job));
  }, [job]);

  /** הקובץ המקורי של רשומה (העלאה + מספר קובץ), אם הוא עדיין בדפדפן. */
  const fileFor = useCallback(
    (batchId: string | null, fileIndex: number | null): File | null =>
      (batchId && fileIndex && filesByBatch.current.get(batchId)?.[fileIndex - 1]) || null,
    [],
  );

  const reset = useCallback(() => {
    setJob(null);
    setCarry(null);
    setFiles([]);
    setError(null);
    setElapsed(0);
  }, []);

  return {
    job: view,
    files,
    error,
    sending,
    stopping,
    elapsed: totalElapsed,
    running,
    canResume,
    remaining,
    start,
    resume,
    cancel,
    reset,
    fileFor,
  };
}
