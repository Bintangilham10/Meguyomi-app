"use client";

import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { parseApiErrorMessage, parseJobResponse } from "@/lib/job-contract";
import { getJobStatusPresentation } from "@/lib/job-status";
import { validatePdfSelection } from "@/lib/upload-policy";
import {
  JOB_SOURCE_LANGUAGES,
  type JobSourceLanguage,
} from "@/lib/source-language";
import { StudioIcon } from "@/components/studio-icon";

type Feedback = { kind: "error" | "success"; message: string } | null;

export function UploadForm() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [sourceLanguage, setSourceLanguage] =
    useState<JobSourceLanguage>("auto");

  function selectFile(file?: File) {
    setFeedback(null);
    setSelectedFile(file ?? null);
    if (!file) {
      return;
    }
    const validationError = validatePdfSelection(file);
    if (validationError) {
      setFeedback({ kind: "error", message: validationError });
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isUploading) return;
    const file = selectedFile;
    if (!file) {
      setFeedback({
        kind: "error",
        message: "Pilih PDF yang ingin diterjemahkan.",
      });
      return;
    }

    const validationError = validatePdfSelection(file);
    if (validationError) {
      setFeedback({ kind: "error", message: validationError });
      return;
    }

    setIsUploading(true);
    setFeedback(null);
    try {
      const formData = new FormData();
      formData.set("file", file);
      formData.set("source_language", sourceLanguage);
      const response = await fetch("/api/jobs", {
        method: "POST",
        body: formData,
      });
      const body: unknown = await response.json().catch(() => null);

      if (!response.ok) {
        setFeedback({
          kind: "error",
          message: parseApiErrorMessage(body, "PDF tidak dapat diunggah."),
        });
        return;
      }

      const job = parseJobResponse(body);
      if (!job) {
        setFeedback({
          kind: "error",
          message: "Respons pekerjaan dari server tidak valid.",
        });
        return;
      }
      if (job.status === "FAILED") {
        setFeedback({
          kind: "error",
          message: getJobStatusPresentation(job.status, job.failureCode).detail,
        });
        router.refresh();
        return;
      }

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setSelectedFile(null);
      setFeedback({
        kind: "success",
        message: "PDF diterima dan masuk ke antrean pekerjaan.",
      });
      router.replace("/");
      router.refresh();
    } catch {
      setFeedback({
        kind: "error",
        message: "Koneksi terputus. Coba unggah kembali.",
      });
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="upload-console"
      noValidate
      aria-busy={isUploading}
    >
      <div className="console-head">
        <h2>
          <StudioIcon name="spark" /> Mulai chapter baru
        </h2>
        <span>01 / UPLOAD</span>
      </div>
      <div className="language-route">
        <div className="source-field">
          <label htmlFor="source-language" className="field-label">
            Bahasa sumber PDF
          </label>
          <select
            id="source-language"
            name="source_language"
            value={sourceLanguage}
            disabled={isUploading}
            aria-describedby="language-help"
            onChange={(event) =>
              setSourceLanguage(event.target.value as JobSourceLanguage)
            }
            className="field-control"
          >
            {JOB_SOURCE_LANGUAGES.map((language) => (
              <option key={language.value} value={language.value}>
                {language.label}
              </option>
            ))}
          </select>
        </div>
        <StudioIcon name="arrow" />
        <div className="target-field">
          <span className="field-label">Terjemahan</span>
          <span className="target-language">
            <span className="id-flag" aria-hidden="true" /> Indonesia
          </span>
        </div>
      </div>
      <p id="language-help" className="field-hint">
        Otomatis memeriksa bahasa di beberapa halaman. Pilih manual jika sudah
        tahu; satu bahasa sumber per PDF.
      </p>
      <label
        htmlFor="manga-pdf"
        className={`drop-zone${isDragging ? " is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!isUploading) setIsDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null))
            setIsDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          if (isUploading) return;
          if (event.dataTransfer.files.length !== 1) {
            setFeedback({
              kind: "error",
              message: "Pilih satu PDF untuk setiap unggahan.",
            });
            return;
          }
          if (fileInputRef.current) fileInputRef.current.value = "";
          selectFile(event.dataTransfer.files[0]);
        }}
      >
        <span className="drop-icon">
          <StudioIcon name="upload" />
        </span>
        <span className="drop-content">
          <span className="drop-title">
            {selectedFile ? selectedFile.name : "Tarik PDF ke sini"}
          </span>
          <span className="drop-link">
            {selectedFile
              ? "Klik untuk ganti file"
              : "atau klik untuk pilih file"}
          </span>
          <span id="pdf-help" className="drop-help">
            PDF / maks. 50 MB / 100 halaman / tanpa enkripsi
          </span>
        </span>
        <input
          ref={fileInputRef}
          id="manga-pdf"
          name="file"
          type="file"
          accept="application/pdf,.pdf"
          aria-describedby="pdf-help"
          disabled={isUploading}
          aria-label="Pilih PDF manga atau manhua"
          onChange={() => selectFile(fileInputRef.current?.files?.[0])}
          className="sr-only"
        />
      </label>

      <div className="submit-row">
        <button type="submit" disabled={isUploading} className="primary-action">
          {isUploading ? "Mengunggah dan memeriksa..." : "Unggah PDF"}
          <StudioIcon name="arrow" />
        </button>
        <p
          role={feedback?.kind === "error" ? "alert" : "status"}
          aria-live="polite"
          className={
            feedback?.kind === "error"
              ? "upload-feedback upload-feedback-error"
              : "upload-feedback"
          }
        >
          {feedback?.message ?? "File asli disimpan privat di server Meguyomi."}
        </p>
      </div>
    </form>
  );
}
