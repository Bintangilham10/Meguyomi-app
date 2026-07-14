"use client";

import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { parseApiErrorMessage } from "@/lib/job-contract";
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

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setSelectedName(null);
      setFeedback({
        kind: "success",
        message: "PDF diterima dan masuk ke antrean pekerjaan.",
      });
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
    <form onSubmit={handleSubmit} className="mt-6" noValidate>
      <label
        htmlFor="manga-pdf"
        className="block border border-dashed border-[var(--border-strong)] bg-[var(--background)] p-6 transition focus-within:border-[var(--accent)] sm:p-8"
      >
        <span className="block text-base font-semibold">Pilih PDF manga</span>
        <span id="pdf-help" className="mt-2 block text-sm leading-6 text-[var(--muted)]">
          PDF Jepang, maksimal 50 MB dan 100 halaman. PDF terenkripsi tidak didukung.
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
          className="mt-5 block w-full text-sm text-[var(--muted)] file:mr-4 file:border file:border-[var(--border-strong)] file:bg-[var(--surface)] file:px-4 file:py-2 file:font-semibold file:text-[var(--foreground)] hover:file:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent)] disabled:opacity-60"
        />
        {selectedName ? (
          <span className="mt-4 block break-all text-sm font-medium text-[var(--foreground)]">
            Terpilih: {selectedName}
          </span>
        ) : null}
      </label>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center">
        <button
          type="submit"
          disabled={isUploading}
          className="inline-flex min-h-11 items-center justify-center bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isUploading ? "Mengunggah dan memeriksa…" : "Unggah PDF"}
        </button>
        <p
          role={feedback?.kind === "error" ? "alert" : "status"}
          aria-live="polite"
          className={
            feedback?.kind === "error"
              ? "text-sm text-[var(--danger)]"
              : "text-sm text-[var(--accent-strong)]"
          }
        >
          {feedback?.message ?? "File asli disimpan privat di server Meguyomi."}
        </p>
      </div>
    </form>
  );
}
