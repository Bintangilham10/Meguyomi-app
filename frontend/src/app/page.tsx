import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";

import { logoutAction } from "./actions";


export default async function Home() {
  const user = await getCurrentUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4 lg:px-10">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
              Meguyomi
            </p>
            <p className="mt-1 text-sm text-[var(--muted)]">Workspace milik {user.username}</p>
          </div>
          <form action={logoutAction}>
            <button
              type="submit"
              className="border border-[var(--border)] px-4 py-2 text-sm font-semibold transition hover:border-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              Keluar
            </button>
          </form>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 py-12 lg:px-10">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
          Dashboard
        </p>
        <h1 className="mt-4 max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
          Mulai terjemahan manga berikutnya.
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-[var(--muted)]">
          Autentikasi sudah aktif. Alur upload PDF dan daftar pekerjaan akan
          ditambahkan pada tahap berikutnya.
        </p>

        <section className="mt-10 border border-dashed border-[var(--border-strong)] bg-[var(--surface)] p-8 sm:p-10">
          <h2 className="text-lg font-semibold">Belum ada pekerjaan terjemahan</h2>
          <p className="mt-2 max-w-xl leading-7 text-[var(--muted)]">
            Setelah fitur upload tersedia, status PDF akan tampil di area ini.
          </p>
        </section>
      </main>
    </div>
  );
}
