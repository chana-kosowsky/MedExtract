import { LoaderCircle, RotateCcw, ScanText } from "lucide-react";
import type { WakeStatus } from "../../../hooks/useServerWake";
import "./WakeScreen.css";

/** מסך פתיחה בזמן שהשרת מתעורר, או הודעה כשהוא לא זמין. */
export default function WakeScreen({ status, onRetry }: { status: WakeStatus; onRetry: () => void }) {
  return (
    <div className="wake">
      <div className="wake-logo">
        <ScanText />
      </div>
      <h1 className="wake-title">MedExtract</h1>
      {status === "failed" ? (
        <>
          <p className="wake-text">השרת לא זמין כרגע.</p>
          <button className="btn btn-primary" onClick={onRetry}>
            <RotateCcw className="icon-sm" />
            ניסיון חוזר
          </button>
        </>
      ) : (
        <>
          <LoaderCircle className="wake-spinner" />
          <p className="wake-text">
            {status === "slow" ? "השרת מתעורר משינה. זה לוקח עד דקה בפעם הראשונה…" : "מתחברים…"}
          </p>
        </>
      )}
    </div>
  );
}
