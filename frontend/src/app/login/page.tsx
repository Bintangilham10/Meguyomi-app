import Image from "next/image";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";

import { LoginForm } from "./login-form";


export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect("/");
  }

  return (
    <main
      id="main-content"
      className="grid min-h-[100dvh] bg-[var(--surface)] lg:grid-cols-[minmax(28rem,1.05fr)_minmax(26rem,0.95fr)]"
    >
      <section className="relative hidden overflow-hidden bg-[var(--ink)] p-10 text-white lg:flex lg:flex-col lg:justify-between xl:p-14">
        <div className="halftone absolute inset-0 opacity-60" aria-hidden="true" />
        <div
          className="absolute -right-24 top-16 size-[28rem] rounded-full bg-[var(--accent)]"
          aria-hidden="true"
        />
        <div className="relative z-10 flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-[10px] bg-white font-black text-[var(--ink)]">
            M
          </span>
          <p className="display-face text-xl">MEGUYOMI</p>
        </div>
        <div className="relative z-10 mb-4 max-w-lg">
          <h1 className="display-face text-5xl leading-[1.03] xl:text-6xl">
            Manga Jepang, dibaca dalam bahasamu.
          </h1>
          <p className="mt-5 max-w-md text-lg leading-8 text-[var(--ink-muted)]">
            Satu meja privat untuk mengunggah, menerjemahkan, memulihkan progres, dan
            mengunduh PDF.
          </p>
        </div>
        <Image
          src="/meguyomi-translator.png"
          alt="Ilustrasi penerjemah manga Meguyomi"
          width={1024}
          height={1536}
          priority
          className="mascot-float absolute -bottom-36 -right-20 h-[42rem] w-auto max-w-none object-contain xl:-right-10 xl:h-[48rem]"
        />
      </section>

      <section className="relative flex items-center justify-center px-5 py-10 sm:px-10">
        <div
          className="paper-halftone absolute inset-x-0 top-0 h-32 opacity-40 lg:hidden"
          aria-hidden="true"
        />
        <div className="w-full max-w-md">
          <div className="relative mb-12 flex items-center gap-3 lg:hidden">
            <span className="grid size-11 place-items-center rounded-[10px] bg-[var(--ink)] font-black text-white">
              M
            </span>
            <p className="display-face text-xl">MEGUYOMI</p>
          </div>
          <p className="mb-4 w-fit rounded-[8px] bg-[var(--accent-wash)] px-3 py-1.5 text-sm font-bold text-[var(--accent-strong)]">
            Workspace privat
          </p>
          <h2 className="display-face text-4xl leading-tight sm:text-5xl">
            Buka meja kerjamu.
          </h2>
          <p className="mt-4 max-w-sm leading-7 text-[var(--muted)]">
            Masuk dengan akun yang sudah dikonfigurasi pada server Meguyomi.
          </p>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
