import { redirect } from "next/navigation";
import { CharacterStage } from "@/components/character-stage";
import { StudioBrand, StudioFooter } from "@/components/studio-chrome";
import { getCurrentUser } from "@/lib/auth";
import { LoginForm } from "./login-form";

export default async function LoginPage() {
  if (await getCurrentUser()) redirect("/");

  return (
    <div className="app-shell login-shell">
      <header className="login-header">
        <StudioBrand />
        <span className="login-header-note">
          YOUR NEXT CHAPTER STARTS HERE.
        </span>
      </header>
      <main id="main-content" className="login-main">
        <section className="login-intro">
          <p className="hero-kicker">
            <span className="kicker-line" /> MANGA. MANHUA. BAHASA KITA.
          </p>
          <h1 className="hero-title">
            Cerita bagus.
            <br />
            <span>
              Tanpa batas<em>.</em>
            </span>
          </h1>
          <p className="hero-lead">
            Studio kecil untuk petualangan besar. Terjemahkan manga favoritmu
            dengan mesin lokal, ditemani Alya.
          </p>
        </section>
        <section className="login-panel" aria-labelledby="login-title">
          <span className="login-panel-index">01 / WELCOME BACK</span>
          <div className="login-greeting" aria-hidden="true">
            hello<span>!</span>
          </div>
          <h2 id="login-title">
            Masuk ke studio<span>.</span>
          </h2>
          <p>
            Chapter berikutnya sudah menunggu. Masuk dengan akun Meguyomi kamu.
          </p>
          <LoginForm />
          <p className="login-note">
            Gunakan akun yang sudah dikonfigurasi di server lokalmu.
          </p>
          <div className="login-panel-footer">
            <span>LOCAL FIRST</span>
            <span>JP / ZH &rarr; ID</span>
          </div>
        </section>
        <CharacterStage compact />
      </main>
      <StudioFooter />
    </div>
  );
}
