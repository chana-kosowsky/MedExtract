import { CircleCheck } from "lucide-react";
import type { ToastMessage } from "../../../hooks/useToast";
import "./Toast.css";

/** הודעת האישור הקצרה בתחתית המסך (נקראת גם על ידי קוראי מסך). */
export default function Toast({ toast, onDismiss }: { toast: ToastMessage | null; onDismiss: () => void }) {
  return (
    <div className="toast-area" role="status" aria-live="polite">
      {toast && (
        <button key={toast.id} className="toast" onClick={onDismiss}>
          <CircleCheck className="icon-sm" />
          {toast.text}
        </button>
      )}
    </div>
  );
}
