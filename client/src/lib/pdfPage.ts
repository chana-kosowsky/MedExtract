import type { PDFDocumentProxy } from "pdfjs-dist";

/** רוחב התמונה בפיקסלים: מספיק חד להגדלה של כתב יד. */
const TARGET_WIDTH = 1800;

const docs = new WeakMap<File, Promise<PDFDocumentProxy>>();

/** פותח את קובץ ה-PDF פעם אחת בלבד לכל קובץ (הספרייה נטענת רק בפעם הראשונה). */
function openPdf(file: File): Promise<PDFDocumentProxy> {
  let doc = docs.get(file);
  if (!doc) {
    doc = (async () => {
      const [pdfjs, worker] = await Promise.all([
        import("pdfjs-dist"),
        import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
      ]);
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      return pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    })();
    doc.catch(() => docs.delete(file));
    docs.set(file, doc);
  }
  return doc;
}

/** מצייר עמוד אחד מה-PDF לתמונה, בזיכרון הדפדפן בלבד. */
export async function renderPdfPage(file: File, pageNumber: number): Promise<Blob> {
  const doc = await openPdf(file);
  const page = await doc.getPage(pageNumber);
  const base = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: TARGET_WIDTH / base.width });
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(viewport.width);
  canvas.height = Math.round(viewport.height);
  await page.render({ canvas, viewport }).promise;
  page.cleanup();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("render"))), "image/jpeg", 0.9),
  );
}

/** האם הקובץ הוא PDF (לפי הסוג או הסיומת). */
export function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}
