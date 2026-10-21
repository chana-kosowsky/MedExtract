import { CloudUpload, FileText, Image, Lock, LoaderCircle, Sparkles, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { ACCEPTED_FILES, LIMITS } from "../../../config";
import { formatSize } from "../../../lib/format";
import "./UploadZone.css";

interface Props {
  sending: boolean;
  serverError: string | null;
  onStart: (files: File[]) => void;
}

/** בודקת את מגבלות ההעלאה בדפדפן (השרת בודק שוב). מחזירה הודעה או null. */
function checkFiles(files: File[]): string | null {
  const mb = 1024 * 1024;
  if (files.length > LIMITS.maxFiles) return `אפשר להעלות עד ${LIMITS.maxFiles} קבצים בפעם אחת.`;
  const big = files.find((f) => f.size > LIMITS.maxFileMB * mb);
  if (big) return `הקובץ "${big.name}" גדול מ-${LIMITS.maxFileMB}MB.`;
  if (files.reduce((s, f) => s + f.size, 0) > LIMITS.maxTotalMB * mb) return `ההעלאה גדולה מ-${LIMITS.maxTotalMB}MB.`;
  return null;
}

/** אזור גרירה ובחירה של טפסים, עם רשימת הקבצים וכפתור התחלה. */
export default function UploadZone({ sending, serverError, onStart }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const localError = checkFiles(files);
  const error = localError ?? serverError;

  function add(list: FileList | null) {
    if (list) setFiles((prev) => [...prev, ...Array.from(list)]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    add(e.dataTransfer.files);
  }

  return (
    <section className="card upload">
      <div
        className={dragging ? "upload-drop upload-drop-active" : "upload-drop"}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
      >
        <div className="upload-icon">
          <CloudUpload />
        </div>
        <h2 className="upload-title">גרירת טפסי ההתחייבות לכאן</h2>
        <p className="upload-hint">PDF סרוק או צילומים מהטלפון · עד {LIMITS.maxPages} עמודים בכל העלאה</p>
        <span className="btn btn-secondary">בחירת קבצים</span>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED_FILES}
          hidden
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="upload-files">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="upload-file">
              {f.type === "application/pdf" ? <FileText className="upload-file-icon" /> : <Image className="upload-file-icon" />}
              <span className="upload-file-name">{f.name}</span>
              <span className="upload-file-size">{formatSize(f.size)}</span>
              <button
                className="upload-file-remove"
                aria-label="הסרה"
                onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
              >
                <X className="icon-sm" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && <p className="upload-error">{error}</p>}

      <footer className="upload-footer">
        <p className="upload-privacy">
          <Lock className="icon-sm" />
          הטפסים נשלחים לקריאה במודל AI חיצוני (Claude, ובגיבוי Google Gemini) ולא נשמרים. במערכת נשמרים רק
          השדות שחולצו.
        </p>
        <button
          className="btn btn-primary upload-start"
          disabled={files.length === 0 || !!localError || sending}
          onClick={() => onStart(files)}
        >
          {sending ? <LoaderCircle className="icon-sm spin" /> : <Sparkles className="icon-sm" />}
          {sending
            ? "שליחת הקבצים…"
            : files.length > 0
              ? `התחלת עיבוד (${files.length} קבצים)`
              : "התחלת עיבוד"}
        </button>
      </footer>
    </section>
  );
}
