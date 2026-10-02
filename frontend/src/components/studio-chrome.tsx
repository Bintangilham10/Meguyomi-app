import Link from "next/link";
import { logoutAction } from "@/app/actions";
import { StudioIcon } from "@/components/studio-icon";

export function StudioBrand() {
  return (
    <Link
      href="/"
      className="brand-lockup"
      aria-label="Meguyomi, beranda studio"
    >
      <span className="brand-mark" aria-hidden="true">
        m<span>.</span>
      </span>
      <span className="brand-copy">
        <strong>
          meguyomi<span> /</span>
        </strong>
        <small>MANGA TRANSLATION STUDIO</small>
      </span>
    </Link>
  );
}

export function StudioHeader({
  username,
  active = "studio",
}: {
  username: string;
  active?: "studio" | "memory";
}) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <StudioBrand />
        <nav className="top-nav" aria-label="Navigasi utama">
          <Link
            href="/"
            className="top-nav-link"
            aria-current={active === "studio" ? "page" : undefined}
          >
            Studio<span className="nav-index">01</span>
          </Link>
          <Link
            href="/memory"
            className="top-nav-link"
            aria-current={active === "memory" ? "page" : undefined}
          >
            Bank terjemahan<span className="nav-index">02</span>
          </Link>
        </nav>
        <div className="topbar-account">
          <span className="account-avatar" aria-hidden="true">
            {username.slice(0, 1).toUpperCase()}
          </span>
          <span className="account-name">{username}</span>
          <form action={logoutAction}>
            <button type="submit" className="logout-button">
              Keluar
            </button>
          </form>
        </div>
      </div>
    </header>
  );
}

export function StudioFooter() {
  return (
    <footer className="site-footer">
      <span>
        MEGUYOMI <span className="footer-slash">/</span> CERITA TANPA BATAS
        BAHASA.
      </span>
      <span>
        Local engine. Otaku energy. <StudioIcon name="spark" />
      </span>
    </footer>
  );
}
