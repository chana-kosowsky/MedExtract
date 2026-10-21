import { useCallback, useEffect, useRef, useState } from "react";

export interface ToastMessage {
  id: number;
  text: string;
}

const SHOW_MS = 2800;

/** הודעת אישור קצרה בפינה ("הרשומה אושרה"), שנעלמת לבד. הודעה חדשה מחליפה את הקודמת. */
export function useToast() {
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const next = useRef(0);

  const notify = useCallback((text: string) => setToast({ id: ++next.current, text }), []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), SHOW_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  return { toast, notify, dismiss: () => setToast(null) };
}

export type Notify = (text: string) => void;
