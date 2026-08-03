"use client";

import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { parseApiErrorMessage, parseJobResponse } from "@/lib/job-contract";
import { getJobStatusPresentation } from "@/lib/job-status";
import { validatePdfSelection } from "@/lib/upload-policy";


type Feedback = { kind: "error" | "success"; message: string } | null;


export function UploadForm() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [isUploading, setIsUploading] = useState(false);

  function handleFileChange() {
    const file = fileInputRef.current?.files?.[0];
    setFeedback(null);
    setSelectedName(file?.name ?? null);
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
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setFeedback({ kind: "error", message: "Pilih PDF yang ingin diterjemahkan." });
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
      const response = await fetch("/api/jobs", { method: "POST", body: formData });
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
      setSelectedName(null);
      setFeedback({
        kind: "success",
        message: "PDF diterima dan masuk ke antrean pekerjaan.",
      });
      router.replace("/");
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
    <form onSubmit={handleSubmit} className="mt-8" noValidate>
      <label
        htmlFor="manga-pdf"
        className="paper-halftone group block cursor-pointer rounded-[14px] border-2 border-dashed border-[var(--border-strong)] bg-[var(--background)] p-5 transition hover:border-[var(--ink)] focus-within:border-[var(--accent)] focus-within:outline-2 focus-within:outline-offset-4 focus-within:outline-[var(--accent)] sm:p-6"
      >
        <span className="block text-lg font-bold">Taruh bab manga di meja</span>
        <span id="pdf-help" className="mt-2 block text-sm leading-6 text-[var(--muted)]">
          PDF manga dalam bahasa apa pun, maksimal 50 MB dan 100 halaman. PDF terenkripsi tidak didukung.
        </span>
        <input
          ref={fileInputRef}
          id="manga-pdf"
          name="file"
          type="file"
          accept="application/pdf,.pdf"
          aria-describedby="pdf-help"
          disabled={isUploading}
          onChange={handleFileChange}
          className="mt-5 block w-full text-sm text-[var(--muted)] file:mr-4 file:cursor-pointer file:rounded-[10px] file:border file:border-[var(--ink)] file:bg-[var(--surface)] file:px-4 file:py-2.5 file:font-bold file:text-[var(--foreground)] hover:file:bg-[var(--ink)] hover:file:text-white focus-visible:outline-none disabled:opacity-60"
        />
        {selectedName ? (
          <span className="mt-4 block w-fit max-w-full break-all rounded-[8px] bg-[var(--surface)] px-3 py-2 text-sm font-bold text-[var(--foreground)]">
            Terpilih: {selectedName}
          </span>
        ) : null}
      </label>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center">
        <button
          type="submit"
          disabled={isUploading}
          className="brand-shadow inline-flex min-h-12 shrink-0 items-center justify-center rounded-[10px] border border-[var(--ink)] bg-[var(--accent)] px-6 py-3 text-sm font-bold text-white transition focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-none disabled:transform-none"
        >
          {isUploading ? "Mengunggah dan memeriksa..." : "Unggah PDF"}
        </button>
        <p
          role={feedback?.kind === "error" ? "alert" : "status"}
          aria-live="polite"
          className={
            feedback?.kind === "error"
              ? "text-sm font-medium leading-6 text-[var(--danger)]"
              : "text-sm leading-6 text-[var(--muted)]"
          }
        >
          {feedback?.message ?? "File asli disimpan privat di server Meguyomi."}
        </p>
      </div>
    </form>
  );
}
