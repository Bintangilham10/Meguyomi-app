import type { Metadata } from "next";

import "./globals.css";


export const metadata: Metadata = {
  title: "Meguyomi | Manga Translation Desk",
  description: "Workspace privat untuk menerjemahkan manga PDF dari berbagai bahasa ke bahasa Indonesia.",
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
