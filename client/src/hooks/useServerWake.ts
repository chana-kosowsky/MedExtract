import { useCallback, useEffect, useState } from "react";
import { checkHealth } from "../api/client";

const RETRY_MS = 3000;
const SLOW_MS = 4000;
const GIVE_UP_MS = 90_000;

export type WakeStatus = "connecting" | "slow" | "ready" | "failed";

/** מחכה שהשרת יתעורר (ב-Render הוא נרדם אחרי 15 דקות), עם ניסיונות חוזרים. */
export function useServerWake() {
  const [status, setStatus] = useState<WakeStatus>("connecting");
  const [dbOk, setDbOk] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    const start = Date.now();
    const slowTimer = setTimeout(() => !stopped && setStatus((s) => (s === "connecting" ? "slow" : s)), SLOW_MS);

    async function tryOnce() {
      try {
        const db = await checkHealth();
        if (stopped) return;
        setDbOk(db);
        setStatus("ready");
      } catch {
        if (stopped) return;
        if (Date.now() - start > GIVE_UP_MS) setStatus("failed");
        else setTimeout(tryOnce, RETRY_MS);
      }
    }
    tryOnce();
    return () => {
      stopped = true;
      clearTimeout(slowTimer);
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setStatus("connecting");
    setAttempt((a) => a + 1);
  }, []);

  return { status, dbOk, retry };
}
