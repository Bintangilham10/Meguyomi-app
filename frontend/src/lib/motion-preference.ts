"use client";

import { useSyncExternalStore } from "react";

const storageKey = "meguyomi.motion-paused";
const changeEvent = "meguyomi-motion-change";
const reducedMotionQuery = "(prefers-reduced-motion: reduce)";
let fallbackPaused: boolean | null = null;

function readPaused() {
  if (fallbackPaused !== null) return fallbackPaused;
  try {
    return localStorage.getItem(storageKey) === "true";
  } catch {
    return false;
  }
}

function subscribePaused(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(changeEvent, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(changeEvent, onChange);
  };
}

function setPaused(value: boolean) {
  fallbackPaused = value;
  try {
    localStorage.setItem(storageKey, String(value));
    fallbackPaused = null;
  } catch {
    // Keep the control usable when the browser blocks local storage.
  }
  window.dispatchEvent(new Event(changeEvent));
}

function subscribeReducedMotion(onChange: () => void) {
  const media = window.matchMedia(reducedMotionQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

const serverSnapshot = () => false;
const readReducedMotion = () => window.matchMedia(reducedMotionQuery).matches;

export function useMotionPreference() {
  const paused = useSyncExternalStore(
    subscribePaused,
    readPaused,
    serverSnapshot,
  );
  const reducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    readReducedMotion,
    serverSnapshot,
  );
  return { paused, reducedMotion, setPaused };
}
