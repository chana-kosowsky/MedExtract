import { CircleCheck, CircleX, Clock, LoaderCircle, Play, Square, TriangleAlert, Upload, Zap } from "lucide-react";
import type { Job, PageResult } from "../../../api/types";
import { MANUAL_MINUTES_PER_FORM } from "../../../config";
import { formatDuration, formatSpan } from "../../../lib/format";
import "./ProgressPanel.css";

interface Props {
  job: Job;
  elapsed: number;
  canResume: boolean;
  remaining: number;
  sending: boolean;
  stopping: boolean;
  error: string | null;
  onCancel: () => void;
  onResume: () => void;
  onNew: () => void;
}

const TITLES: Record<Job["state"], string> = {
  running: "קוראים את הטפסים…",
  done: "העיבוד הסתיים",
  cancelled: "העיבוד הופסק",
  quota_stopped: "מכסת הבקשות למודל נגמרה",
  error: "אירעה שגיאה בעיבוד",
};

/** משבצת אחת לכל עמוד: הצליח, נכשל, בעבודה או ממתין. */
function PageTile({ index, result, current }: { index: number; result?: PageResult; current: boolean }) {
  if (result) {
    const failed = !result.ok || !!result.save_error;
    const tip = result.save_error ?? result.error_message ?? `קובץ ${result.file_index}, עמוד ${result.page}`;
    return (
      <li className={failed ? "tile tile-failed" : "tile tile-done"} title={tip}>
        {failed ? <CircleX /> : <CircleCheck />}
        <span>{index + 1}</span>
      </li>
    );
  }
  return (
    <li className={current ? "tile tile-current" : "tile tile-waiting"}>
      {current && <LoaderCircle className="spin" />}
      <span>{index + 1}</span>
    </li>
  );
}

/** התקדמות חיה: פס, מונה זמן, השוואה להקלדה ידנית ומשבצת לכל עמוד. */
export default function ProgressPanel(props: Props) {
  const { job, elapsed, canResume, remaining, sending, stopping, error, onCancel, onResume, onNew } = props;
  const running = job.state === "running";
  const percent = job.total_pages ? Math.round((job.processed / job.total_pages) * 100) : 0;
  // בזמן העיבוד: הזמן הצפוי לכל ההעלאה. בסוף: רק הטפסים שעובדו בפועל.
  const forms = running ? job.total_pages : job.succeeded;
  const manualSeconds = forms * MANUAL_MINUTES_PER_FORM * 60;
  const savedSeconds = manualSeconds - elapsed;
  const failures = job.results.filter((r) => !r.ok);

  return (
    <section className="card progress">
      <header className="progress-head">
        <div>
          <h2 className="progress-title">{TITLES[job.state]}</h2>
          <p className="progress-sub">
            {job.processed} מתוך {job.total_pages} עמודים
            {job.failed > 0 && ` · ${job.failed} לא עובדו`}
          </p>
        </div>
        <div className="progress-clock">
          <Clock />
          <span>{formatDuration(elapsed)}</span>
        </div>
      </header>

      <div className="progress-track">
        <div className={running ? "progress-fill progress-fill-running" : "progress-fill"} style={{ width: `${percent}%` }} />
      </div>

      <ol className="progress-tiles">
        {Array.from({ length: job.total_pages }, (_, i) => (
          <PageTile key={i} index={i} result={job.results[i]} current={running && i === job.results.length} />
        ))}
      </ol>

      <div className="progress-compare">
        <div className="compare-item">
          <span className="compare-label">הקלדה ידנית</span>
          <span className="compare-value compare-manual">{formatSpan(manualSeconds)}</span>
        </div>
        <div className="compare-item">
          <span className="compare-label">MedExtract</span>
          <span className="compare-value compare-fast">
            <Zap />
            {formatSpan(elapsed)}
          </span>
        </div>
        {!running && savedSeconds > 0 && (
          <div className="compare-item compare-saved">
            <span className="compare-label">נחסכו ב-{job.succeeded} טפסים</span>
            <span className="compare-value">{formatSpan(savedSeconds)} עבודה</span>
          </div>
        )}
      </div>

      {!running && job.message && (
        <p className={job.state === "done" ? "progress-message" : "progress-message progress-message-warn"}>
          {job.state !== "done" && <TriangleAlert className="icon-sm" />}
          {job.message}
        </p>
      )}

      {!running && failures.length > 0 && (
        <ul className="progress-failures">
          {failures.map((r) => (
            <li key={`${r.file_index}-${r.page}`}>
              קובץ {r.file_index}, עמוד {r.page}: {r.error_message}
            </li>
          ))}
        </ul>
      )}

      {error && <p className="progress-error">{error}</p>}

      <footer className="progress-footer">
        {running ? (
          <button className="btn btn-danger" onClick={onCancel} disabled={stopping}>
            {stopping ? <LoaderCircle className="icon-sm spin" /> : <Square className="icon-sm" />}
            {stopping ? "העיבוד ייעצר אחרי העמוד הנוכחי…" : "עצירה"}
          </button>
        ) : (
          <>
            <button className="btn btn-secondary" onClick={onNew}>
              <Upload className="icon-sm" />
              העלאה חדשה
            </button>
            {canResume && (
              <button className="btn btn-primary" onClick={onResume} disabled={sending}>
                {sending ? <LoaderCircle className="icon-sm spin" /> : <Play className="icon-sm" />}
                {sending ? "שליחת הקבצים…" : `המשך מהמקום שעצר (${remaining} עמודים נותרו)`}
              </button>
            )}
          </>
        )}
      </footer>
    </section>
  );
}
