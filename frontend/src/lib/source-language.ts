export type SourceLanguage = "ja" | "zh-Hans" | "zh-Hant";
export type JobSourceLanguage = SourceLanguage | "auto";

export const SOURCE_LANGUAGES: { value: SourceLanguage; label: string }[] = [
  { value: "ja", label: "Jepang" },
  { value: "zh-Hans", label: "Mandarin (sederhana)" },
  { value: "zh-Hant", label: "Mandarin (tradisional)" },
];

export const JOB_SOURCE_LANGUAGES: { value: JobSourceLanguage; label: string }[] = [
  { value: "auto", label: "Deteksi otomatis" },
  ...SOURCE_LANGUAGES,
];

export function sourceLanguageLabel(value: JobSourceLanguage): string {
  return JOB_SOURCE_LANGUAGES.find(language => language.value === value)?.label ?? "Bahasa tidak dikenal";
}
