import type { Metadata } from "next";

import "./globals.css";


export const metadata: Metadata = {
  title: "Meguyomi",
  description: "Penerjemah manga PDF Jepang ke bahasa Indonesia.",
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
