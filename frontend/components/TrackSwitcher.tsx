"use client";

import { useEffect, useState } from "react";
import { listTracks, type TrackOut } from "@/lib/api";
import { useTrack } from "@/lib/track";

export function TrackSwitcher() {
  const { track, setTrack, hydrate } = useTrack();
  const [tracks, setTracks] = useState<TrackOut[]>([]);
  useEffect(() => {
    hydrate();
    listTracks().then(setTracks).catch(() => undefined);
  }, [hydrate]);
  if (tracks.length === 0) return null;
  return (
    <label className="flex items-center gap-2 text-xs opacity-80">
      Track
      <select
        value={track}
        onChange={(e) => setTrack(e.target.value)}
        className="min-h-9 rounded-md border border-neutral-300 bg-transparent px-2 py-1 text-sm dark:border-neutral-700"
      >
        {tracks.map((t) => (
          <option key={t.slug} value={t.slug}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  );
}
