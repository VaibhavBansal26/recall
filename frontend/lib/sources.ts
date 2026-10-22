/** Pure helpers for the sources screen. */

/** A single link (with or without a scheme) rather than pasted text. */
export function looksLikeLink(input: string): boolean {
  const t = input.trim();
  if (/\s/.test(t) || t.length === 0) return false;
  return /^https?:\/\/\S+$/i.test(t) || /^(www\.)?[\w-]+(\.[\w-]+)*\.[a-z]{2,}(\/\S*)?$/i.test(t);
}

export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  fetching: "Fetching",
  processing: "Processing",
  needs_track: "Which track?",
  ready: "Ready to approve",
  approved: "Approved",
  failed: "Failed",
};

const STAGE_LABEL: Record<string, string> = {
  fetching: "Fetching the page",
  chunking: "Splitting into chunks",
  classifying: "Choosing a track",
  extracting: "Extracting notes with citations",
  filing: "Filing notes",
};

export function describeProgress(status: string, stage: string | null): string {
  if (status === "processing" || status === "fetching") {
    return (stage && STAGE_LABEL[stage]) || STATUS_LABEL[status];
  }
  return STATUS_LABEL[status] ?? status;
}

export function shortUri(uri: string): string {
  if (uri.startsWith("sha256:")) return "pasted text or uploaded file";
  return uri.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}
