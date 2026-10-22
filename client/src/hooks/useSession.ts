import { useCallback, useEffect, useState } from "react";
import { ApiError, auth, SESSION_EXPIRED } from "../api/client";
import type { Session } from "../api/types";

export type SessionStatus = "checking" | "login" | "in";

/** מצב הכניסה: בודק מול השרת כשהוא ער, כניסה ויציאה, וחזרה למסך הכניסה כשהשרת דוחה בקשה. */
export function useSession(serverReady: boolean) {
  const [status, setStatus] = useState<SessionStatus>("checking");
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (!serverReady) return;
    auth
      .session()
      .then((s) => {
        setSession(s);
        setStatus(!s.required || s.user ? "in" : "login");
      })
      .catch(() => setStatus("login"));
  }, [serverReady]);

  useEffect(() => {
    const expired = () => setStatus("login");
    window.addEventListener(SESSION_EXPIRED, expired);
    return () => window.removeEventListener(SESSION_EXPIRED, expired);
  }, []);

  /** מחזירה הודעת שגיאה בעברית, או null כשהכניסה הצליחה. */
  const login = useCallback(async (username: string, password: string) => {
    try {
      await auth.login(username, password);
      setSession((s) => (s ? { ...s, user: username } : s));
      setStatus("in");
      return null;
    } catch (e) {
      return e instanceof ApiError ? e.message : "הכניסה נכשלה. אפשר לנסות שוב.";
    }
  }, []);

  const logout = useCallback(async () => {
    await auth.logout().catch(() => undefined);
    setSession((s) => (s ? { ...s, user: null } : s));
    setStatus("login");
  }, []);

  return { status, session, login, logout, canLogout: !!session?.required };
}
