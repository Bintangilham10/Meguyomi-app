"use client";

import dynamic from "next/dynamic";
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { StudioIcon } from "@/components/studio-icon";
import { useMotionPreference } from "@/lib/motion-preference";
import type { MascotAction } from "@/lib/yomi-model";
import type { MascotCommand } from "@/components/three-mascot";

const ThreeMascot = dynamic(
  () => import("@/components/three-mascot").then((module) => module.ThreeMascot),
  { ssr: false, loading: () => <div className="mascot-loading" role="status"><span className="mascot-loader" aria-hidden="true" />Menyiapkan Alya 3D...</div> },
);

const replies: Record<MascotAction, string[]> = {
  wave: ["Hai! Alya siap nemenin baca!", "Chapter baru? Aku ikut, ya!"],
  happy: ["H-hei... jangan tiba-tiba begitu!", "B-bukan berarti aku senang, ya."],
  read: ["Ssst... lagi seru-serunya baca!", "Satu chapter lagi, deh. Janji!"],
};

class SceneBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function CharacterStage({ compact = false }: { compact?: boolean }) {
  const stage = useRef<HTMLDivElement>(null);
  const { paused, reducedMotion, setPaused } = useMotionPreference();
  const [active, setActive] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [command, setCommand] = useState<MascotCommand>({ action: "wave", id: 0 });
  const onReady = useCallback(() => setReady(true), []);
  const onUnavailable = useCallback(() => setUnavailable(true), []);
  const reactToMascot = useCallback((action: MascotAction) => {
    setCommand((value) => ({ action, id: value.id + 1 }));
  }, []);

  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    let visible = false;
    const updateVisibility = () => setActive(visible && !document.hidden);
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) setMounted(true);
      updateVisibility();
    });
    observer.observe(element);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", updateVisibility); };
  }, []);

  const fallback = <div className="mascot-fallback" role="status">
    <StudioIcon name="spark" /><strong>Alya 3D belum bisa tampil.</strong>
    <p>Coba aktifkan akselerasi grafis atau buka di browser yang mendukung WebGL.</p>
    <button type="button" className="secondary-action" onClick={() => { setReady(false); setUnavailable(false); setAttempt((value) => value + 1); }}>Coba muat 3D lagi</button>
  </div>;

  return <div
    ref={stage}
    className={`character-stage character-stage-3d${compact ? " character-stage-compact" : ""}`}
    data-paused={paused || reducedMotion}
    data-inactive={!active}
    data-renderer={unavailable ? "unavailable" : ready ? "webgl" : "loading"}
    data-reaction={command.id ? command.action : "idle"}
    data-reaction-id={command.id}
  >
    <div className="visual-grid" aria-hidden="true" />
    <div className="mascot-portal" aria-hidden="true" />
    <div className="character-heading"><span><span className="studio-dot" /> YOUR ANIME READING COMPANION</span><span className="mascot-edition">3D / 01</span></div>
    <span className="character-wordmark" aria-hidden="true">ALYA</span>
    <div className="mascot-viewport" role="group" aria-label="Alya, maskot anime 3D interaktif. Sentuh kepala untuk membuatnya senang, buku untuk membaca, atau geser untuk memutar. Tombol interaksi tersedia di bawah.">
      {mounted && <SceneBoundary key={attempt} fallback={fallback}>
        {unavailable ? fallback : <ThreeMascot paused={paused} reducedMotion={reducedMotion} active={active} command={command} onReact={reactToMascot} onReady={onReady} onUnavailable={onUnavailable} />}
      </SceneBoundary>}
    </div>
    <div className="mascot-dialog"><span>ALYA SAYS</span><p aria-live="polite" aria-atomic="true">{command.id ? replies[command.action][Math.floor((command.id - 1) / 3) % 2] : "Kamu mau baca bareng?"}</p></div>
    <div className="mascot-panel-footer">
      <div className="mascot-title"><div><span>ALISA MIKHAILOVNA KUJOU / FAN MODEL</span><strong>Alya<em>.</em></strong></div><span className="mascot-mini-star" aria-hidden="true"><StudioIcon name="spark" /></span></div>
      <p className="mascot-help">Sentuh karakter untuk reaksi. Geser untuk putar.</p>
      <div className="mascot-actions" aria-label="Interaksi Alya">
        <button type="button" onClick={() => reactToMascot("wave")}><StudioIcon name="spark" />Sapa Alya</button>
        <button type="button" onClick={() => reactToMascot("happy")}>Elus kepala</button>
        <button type="button" onClick={() => reactToMascot("read")}><StudioIcon name="book" />Baca manga</button>
      </div>
      <button type="button" className="motion-toggle" aria-pressed={paused || reducedMotion} disabled={reducedMotion} title={reducedMotion ? "Mengikuti pengaturan kurangi gerakan di perangkatmu" : undefined} onClick={() => setPaused(!paused)}><StudioIcon name={paused ? "play" : "pause"} />{reducedMotion ? "Gerak dikurangi" : paused ? "Lanjut animasi" : "Jeda animasi"}</button>
    </div>
  </div>;
}
