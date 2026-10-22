"use client";

import { create } from "zustand";

export const DEFAULT_TRACK = "ai-eng";
const KEY = "recall.track";

interface TrackStore {
  track: string;
  /** False until the saved choice has been read, so pages do not connect to the wrong track. */
  hydrated: boolean;
  hydrate: () => void;
  setTrack: (slug: string) => void;
}

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // private windows and blocked storage: fall back to the default
  }
}

export const useTrack = create<TrackStore>((set, get) => ({
  track: DEFAULT_TRACK,
  hydrated: false,
  hydrate: () => {
    if (get().hydrated) return;
    set({ track: read() || DEFAULT_TRACK, hydrated: true });
  },
  setTrack: (slug) => {
    try {
      window.localStorage.setItem(KEY, slug);
    } catch {
      // the choice still applies for this visit
    }
    set({ track: slug, hydrated: true });
  },
}));
