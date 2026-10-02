"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { SOURCE_LANGUAGES, sourceLanguageLabel, type SourceLanguage } from "@/lib/source-language";

type Entry = { id: number; source_text: string; translated_text: string; source_language: SourceLanguage; category: string; usage_count: number };
const inputClass = "field-control mt-2";
const buttonClass = "secondary-action";

export function MemoryBank() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [source, setSource] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState<SourceLanguage>("ja");
  const [languageFilter, setLanguageFilter] = useState("");
  const [target, setTarget] = useState("");
  const [category, setCategory] = useState("verified");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const [readyLanguages, setReadyLanguages] = useState<Record<string, { ready: boolean }>>({});
  const [suggestions, setSuggestions] = useState<{ source_text: string; translated_text: string; similarity: number }[]>([]);
  const sourceInput = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/memory?page=${page}&q=${encodeURIComponent(filter)}${languageFilter ? `&source_language=${languageFilter}` : ""}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Bank terjemahan belum dapat dimuat.");
        const data = await response.json();
        if (!Array.isArray(data.data) || typeof data.total !== "number") throw new Error("Respons bank tidak valid.");
        setEntries(data.data); setTotal(data.total); setLoading(false);
      }).catch(error => { if (!controller.signal.aborted) { setError(String(error.message)); setLoading(false); } });
    fetch("/api/memory/status", { signal: controller.signal })
      .then(response => response.ok ? response.json() : { ready: false })
      .then(data => { setReady(data.ready === true); setReadyLanguages(data.languages ?? {}); })
      .catch(() => { if (!controller.signal.aborted) setReady(false); });
    return () => controller.abort();
  }, [page, filter, languageFilter, revision]);

  function refresh() { setLoading(true); setRevision(value => value + 1); }

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch("/api/memory", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_text: source, translated_text: target, category, source_language: sourceLanguage }) });
      if (!response.ok) throw new Error("Entri belum tersimpan. Periksa teks dan sesi login.");
      setSource(""); setTarget(""); setSuggestions([]); setNotice("Entri tersimpan untuk pekerjaan berikutnya."); refresh();
    } catch (error) { setError(error instanceof Error ? error.message : "Gagal menyimpan entri."); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/memory/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Entri belum dapat dihapus.");
      setNotice("Entri dihapus."); if (entries.length === 1 && page > 1) setPage(page - 1); refresh();
    } catch (error) { setError(error instanceof Error ? error.message : "Gagal menghapus entri."); }
    finally { setBusy(false); }
  }

  async function importFile(file?: File) {
    if (!file) return;
    setBusy(true); setError(""); setNotice("");
    let imported = 0;
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("File impor maksimal 20 MB.");
      const entries: unknown = JSON.parse(await file.text());
      if (!Array.isArray(entries) || entries.length === 0) throw new Error("File harus berisi daftar entri JSON.");
      for (let start = 0; start < entries.length; start += 100) {
        const batch = entries.slice(start, start + 100);
        const response = await fetch("/api/memory/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(batch) });
        if (!response.ok) throw new Error(`Impor berhenti setelah ${imported} entri. Periksa format entri berikutnya.`);
        imported += batch.length;
      }
      setNotice(`${imported} entri diimpor.`);
    } catch (error) { setError(error instanceof Error ? error.message : "File tidak dapat diimpor."); }
    finally { setBusy(false); refresh(); }
  }

  async function findSuggestions() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/memory/suggestions?q=${encodeURIComponent(source)}&source_language=${sourceLanguage}`);
      if (!response.ok) throw new Error("Saran belum dapat dimuat.");
      const data = await response.json(); setSuggestions(data.data);
      if (!data.data.length) setNotice("Belum ada entri mirip yang sudah dikoreksi.");
    } catch { setError("Saran belum dapat dimuat."); }
    finally { setBusy(false); }
  }

  return (
    <div className="memory-bank">
      <p className="memory-status" role="status">
        {ready === null ? "Memeriksa mesin lokal..." : ready && readyLanguages[sourceLanguage]?.ready ? `Mesin lokal ${sourceLanguageLabel(sourceLanguage)} siap. Gambar dan teks diproses di komputer ini.` : `Mesin lokal ${sourceLanguageLabel(sourceLanguage)} belum siap. Selesaikan pemasangan model sesuai README, lalu jalankan kembali layanan lokal.`}
      </p>
      {error && <p role="alert" className="mt-4 rounded-[8px] bg-[var(--accent-wash)] p-4 font-bold">{error}</p>}
      {notice && <p role="status" className="mt-4 font-bold">{notice}</p>}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.5fr)]">
        <form onSubmit={save} className="memory-panel h-fit">
          <h2 className="display-face text-2xl">Tambah / koreksi</h2>
          <label className="mt-5 block font-bold" htmlFor="memory-language">Bahasa sumber entri</label>
          <select id="memory-language" disabled={busy} value={sourceLanguage} onChange={event => { setSourceLanguage(event.target.value as SourceLanguage); setSuggestions([]); setNotice(""); }} className={inputClass}>
            {SOURCE_LANGUAGES.map(language => <option key={language.value} value={language.value}>{language.label}</option>)}
          </select>
          <label className="mt-4 block font-bold" htmlFor="memory-source">Teks sumber</label>
          <textarea id="memory-source" ref={sourceInput} lang={sourceLanguage} required maxLength={1000} rows={4} value={source} onChange={event => { setSource(event.target.value); setSuggestions([]); }} className={inputClass} />
          <label className="mt-4 block font-bold" htmlFor="memory-target">Terjemahan Indonesia</label>
          <textarea id="memory-target" required maxLength={1000} rows={4} value={target} onChange={event => setTarget(event.target.value)} className={inputClass} />
          <label htmlFor="memory-category" className="mt-4 block font-bold">Jenis entri</label>
          <select id="memory-category" value={category} onChange={event => setCategory(event.target.value)} className={inputClass}>
            <option value="verified">Sudah dikoreksi</option><option value="glossary">Istilah / frasa tetap</option>
          </select>
          <p className="mt-3 text-sm leading-6 text-[var(--muted)]">Entri dipakai untuk teks lengkap yang cocok. Kalimat mirip tetap diterjemahkan ulang agar perubahan arti tidak terlewat.</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button disabled={busy} className="primary-action">{busy ? "Memproses..." : "Simpan entri"}</button>
            <button type="button" disabled={busy || source.trim().length < 3} onClick={findSuggestions} className={buttonClass}>Cari yang mirip</button>
          </div>
          {suggestions.length > 0 && <div className="mt-5 space-y-3"><p className="text-sm font-bold">Saran untuk ditinjau:</p>{suggestions.map((entry, index) => <button key={index} type="button" onClick={() => setTarget(entry.translated_text)} className="block w-full rounded border border-[var(--ink)] p-3 text-left"><span lang={sourceLanguage} className="block break-words">{entry.source_text}</span><span className="mt-1 block text-sm">{entry.translated_text}</span></button>)}</div>}
        </form>
        <section aria-label="Daftar bank terjemahan" className="memory-panel min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="display-face text-2xl">{total} entri tersimpan</h2>
            <a href={`/api/memory/export${languageFilter ? `?source_language=${languageFilter}` : ""}`} download="meguyomi-bank.json" className="font-bold underline underline-offset-4">Ekspor JSON</a>
          </div>
          <label className="mt-4 block text-sm font-bold">Impor bank JSON<input type="file" accept="application/json,.json" disabled={busy} onChange={event => { void importFile(event.target.files?.[0]); event.target.value = ""; }} className="mt-2 block w-full text-sm" /></label>
          <p className="mt-2 text-sm text-[var(--muted)]">Bahasa mengikuti setiap entri dalam file. File lama tanpa bahasa dianggap Jepang.</p>
          <label htmlFor="memory-language-filter" className="mt-4 block text-sm font-bold">Filter bahasa</label>
          <select id="memory-language-filter" value={languageFilter} onChange={event => { setLanguageFilter(event.target.value); setPage(1); setLoading(true); }} className={inputClass}>
            <option value="">Semua bahasa</option>
            {SOURCE_LANGUAGES.map(language => <option key={language.value} value={language.value}>{language.label}</option>)}
          </select>
          <form onSubmit={event => { event.preventDefault(); setPage(1); setFilter(query); setError(""); refresh(); }} className="mt-5 flex items-end gap-2">
            <label className="min-w-0 flex-1 text-sm font-bold" htmlFor="memory-search">Cari teks sumber atau Indonesia<input id="memory-search" maxLength={1000} value={query} onChange={event => setQuery(event.target.value)} className={inputClass} /></label>
            <button className={buttonClass}>Cari</button>
          </form>
          <div aria-busy={loading} className="mt-5 divide-y divide-[var(--border)]">
            {loading ? <p className="py-6">Memuat bank...</p> : entries.length === 0 ? <p className="py-6 leading-7 text-[var(--muted)]">Belum ada entri untuk ditampilkan. Tambahkan frasa atau mulai terjemahkan manga untuk mengisi bank.</p> : entries.map(entry => (
              <article key={entry.id} className="py-5">
                <p className="text-xs font-bold text-[var(--accent-strong)]">{entry.category === "machine" ? "DRAF MODEL" : entry.category === "glossary" ? "ISTILAH / FRASA TETAP" : "SUDAH DIKOREKSI"} / Dipakai {entry.usage_count} kali</p>
                <p className="mt-2 text-xs font-bold">{sourceLanguageLabel(entry.source_language)} ke Indonesia</p>
                <p lang={entry.source_language} className="mt-2 whitespace-pre-wrap break-words text-lg">{entry.source_text}</p>
                <p className="mt-2 whitespace-pre-wrap break-words leading-7">{entry.translated_text}</p>
                <div className="mt-3 flex gap-4 text-sm"><button disabled={busy} onClick={() => { setSource(entry.source_text); setSourceLanguage(entry.source_language); setTarget(entry.translated_text); setCategory(entry.category === "glossary" ? "glossary" : "verified"); setSuggestions([]); sourceInput.current?.focus(); }} className="font-bold underline underline-offset-4">Koreksi</button><button disabled={busy} onClick={() => remove(entry.id)} className="underline underline-offset-4">Hapus entri</button></div>
              </article>
            ))}
          </div>
          <nav aria-label="Halaman bank terjemahan" className="mt-5 flex flex-wrap items-center gap-3">
            <button disabled={page <= 1 || loading} onClick={() => { setLoading(true); setPage(page - 1); }} className={buttonClass}>Sebelumnya</button>
            <span className="text-sm">{page} / {Math.max(1, Math.ceil(total/20))}</span>
            <button disabled={page*20 >= total || loading} onClick={() => { setLoading(true); setPage(page + 1); }} className={buttonClass}>Berikutnya</button>
          </nav>
        </section>
      </div>
    </div>
  );
}
