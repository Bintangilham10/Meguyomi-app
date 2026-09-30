import type { Metadata } from "next";

import "./globals.css";


export const metadata: Metadata = {
  title: "Meguyomi | Manga favorit. Bahasa kita.",
  description: "Workspace privat untuk menerjemahkan manga PDF Jepang dan Mandarin ke bahasa Indonesia dengan mesin lokal tanpa API key.",
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body>
        <a className="skip-link" href="#main-content">
          Lewati ke konten
        </a>
        {children}
      </body>
    </html>
  );
}
