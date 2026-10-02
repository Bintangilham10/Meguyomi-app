import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { MemoryBank } from "@/components/memory-bank";
import { StudioHeader, StudioFooter } from "@/components/studio-chrome";
import { StudioIcon } from "@/components/studio-icon";

export default async function MemoryPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return (
    <div className="app-shell">
      <StudioHeader username={user.username} active="memory" />
      <main id="main-content" className="studio-main memory-main">
        <div className="memory-heading">
          <div>
            <p className="hero-kicker">
              <span className="kicker-line" /> 02 / TRANSLATION MEMORY
            </p>
            <h1>
              Dialog mereka.
              <br />
              <span>Sentuhan kamu.</span>
            </h1>
            <p>
              Simpan istilah, rapikan dialog, dan bikin terjemahan terasa lebih
              kamu. Koreksi dipakai lagi saat teks yang sama muncul di chapter
              berikutnya.
            </p>
          </div>
          <span className="memory-emblem" aria-hidden="true">
            <StudioIcon name="book" />
          </span>
        </div>
        <MemoryBank />
      </main>
      <StudioFooter />
    </div>
  );
}
