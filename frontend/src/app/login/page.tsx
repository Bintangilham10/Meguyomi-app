import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";

import { LoginForm } from "./login-form";


export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/");
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_0.9fr]">
      <section className="hidden bg-[var(--ink)] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--mint)]">
          Meguyomi
        </p>
        <div className="max-w-xl">
          <p className="text-sm uppercase tracking-[0.16em] text-[var(--mint)]">
            Workspace privat
          </p>
          <h1 className="mt-5 text-5xl font-semibold leading-tight tracking-tight">
            Terjemahkan manga tanpa kehilangan alur halamannya.
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-[var(--ink-muted)]">
            Upload PDF Jepang, pantau pemrosesan, periksa pratinjau, lalu unduh
            versi bahasa Indonesia dari satu tempat.
          </p>
        </div>
        <p className="text-sm text-[var(--ink-muted)]">MVP · Jepang ke Indonesia</p>
      </section>

      <section className="flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-md">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--accent)] lg:hidden">
            Meguyomi
          </p>
          <h2 className="mt-5 text-3xl font-semibold tracking-tight">Masuk ke workspace</h2>
          <p className="mt-3 leading-7 text-[var(--muted)]">
            Gunakan akun privat yang dikonfigurasi pada server.
          </p>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
