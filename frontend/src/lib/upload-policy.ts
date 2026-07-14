export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
const MAX_MULTIPART_OVERHEAD_BYTES = 1024 * 1024;
const PDF_CONTENT_TYPE = "application/pdf";


interface FileMetadata {
  name: string;
  type: string;
  size: number;
}


export function validatePdfSelection(file: FileMetadata): string | null {
  if (file.type !== PDF_CONTENT_TYPE || !file.name.toLowerCase().endsWith(".pdf")) {
    return "Pilih file PDF.";
  }
  if (file.size < 1) {
    return "PDF tidak boleh kosong.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "Ukuran PDF maksimal 50 MB.";
  }
  return null;
}


export function exceedsProxyRequestLimit(contentLength: string | null): boolean {
  if (contentLength === null) {
    return false;
  }
  const value = Number(contentLength);
  return (
    Number.isFinite(value) &&
    value > MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
  );
}
