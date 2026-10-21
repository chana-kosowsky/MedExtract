import { ImageOff, LoaderCircle, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { Box } from "../../../api/types";
import { usePageImage } from "../../../hooks/usePageImage";
import { padded } from "../../../lib/focus";
import "./PagePreview.css";

interface Props {
  file: File | null;
  page: number | null;
  sample: boolean;
  focus?: Box | null;
}

const ZOOMS = [1, 1.5, 2, 3];
const FOCUS_ZOOM = 2; // כשמסמנים שדה: 200%, מספיק לקרוא כתב יד

/** מיקום המסגרת כמשתני CSS (המיקום הוא נתון, לא עיצוב; העיצוב ב-PagePreview.css). */
function frameVars([x0, y0, x1, y1]: Box): CSSProperties {
  return {
    "--fx": `${x0 * 100}%`,
    "--fy": `${y0 * 100}%`,
    "--fw": `${(x1 - x0) * 100}%`,
    "--fh": `${(y1 - y0) * 100}%`,
  } as CSSProperties;
}

/** הודעה במקום התמונה (אין קובץ, או שהציור נכשל). */
function Missing({ title, text }: { title: string; text: string }) {
  return (
    <div className="preview-missing">
      <ImageOff className="preview-missing-icon" />
      <p className="preview-missing-title">{title}</p>
      <p className="preview-missing-text">{text}</p>
    </div>
  );
}

/** תמונת העמוד המקורי של הרשומה בלבד (לא שאר הקובץ), עם הגדלה. שדה מסומן: מסגרת סביבו וקפיצה אליו. אם אין קובץ: הסבר. */
export default function PagePreview({ file, page, sample, focus = null }: Props) {
  const image = usePageImage(file, page);
  const [zoom, setZoom] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const frame = focus ? padded(focus) : null;
  useEffect(() => setZoom(0), [file, page]);
  useEffect(() => setLoaded(false), [image.url]);

  // שדה חדש מסומן: הגדלה (אם עוד לא מוגדל) וגלילה כך שהשדה במרכז
  useEffect(() => {
    if (frame) setZoom((z) => Math.max(z, FOCUS_ZOOM));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- לפי המיקום עצמו, לא לפי אובייקט חדש
  }, [focus?.join()]);

  useEffect(() => {
    const box = scroller.current;
    const page = sheet.current;
    if (!frame || !loaded || !box || !page) return;
    const cx = ((frame[0] + frame[2]) / 2) * page.offsetWidth + page.offsetLeft;
    const cy = ((frame[1] + frame[3]) / 2) * page.offsetHeight + page.offsetTop;
    box.scrollTo({ left: cx - box.clientWidth / 2, top: cy - box.clientHeight / 2, behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.join(), zoom, loaded]);

  if (!file) {
    return (
      <Missing
        title="תמונת הטופס לא זמינה"
        text={
          sample
            ? "אלה תוצאות שמורות מריצה קודמת. תמונות הטפסים לא נשמרות במערכת."
            : "מטעמי פרטיות הטפסים לא נשמרים במערכת. התמונה מוצגת רק בזמן העבודה על הקובץ שהועלה, עד לרענון הדף."
        }
      />
    );
  }
  if (image.failed) {
    return <Missing title="לא הצלחנו להציג את העמוד" text="הקובץ לא נפתח בדפדפן. השדות שחולצו נשמרו וזמינים לעריכה." />;
  }

  return (
    <div className="preview">
      <div className="preview-tools">
        <button
          className="btn btn-ghost preview-zoom"
          onClick={() => setZoom((z) => z - 1)}
          disabled={zoom === 0}
          aria-label="הקטנה"
          title="הקטנה"
        >
          <ZoomOut className="icon-sm" />
        </button>
        <span className="preview-zoom-value">{Math.round(ZOOMS[zoom] * 100)}%</span>
        <button
          className="btn btn-ghost preview-zoom"
          onClick={() => setZoom((z) => z + 1)}
          disabled={zoom === ZOOMS.length - 1}
          aria-label="הגדלה"
          title="הגדלה"
        >
          <ZoomIn className="icon-sm" />
        </button>
      </div>
      {/* ltr: גלילה לרוחב בלי ההיפוך של מימין לשמאל, כדי שהחישוב של המיקום יהיה פשוט */}
      <div className="preview-image" dir="ltr" ref={scroller}>
        {image.url ? (
          <div className={`preview-sheet preview-zoom-${zoom}`} ref={sheet}>
            <img src={image.url} alt="תמונת הטופס" onLoad={() => setLoaded(true)} />
            {frame && <div className="preview-frame" style={frameVars(frame)} aria-hidden="true" />}
          </div>
        ) : (
          <div className="preview-loading">
            <LoaderCircle className="icon-sm spin" />
            מכין את תמונת העמוד…
          </div>
        )}
      </div>
    </div>
  );
}
