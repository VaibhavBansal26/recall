import { describe, expect, it } from "vitest";
import { describeProgress, looksLikeLink, shortUri } from "@/lib/sources";

describe("looksLikeLink", () => {
  it.each([
    "https://example.com/post",
    "http://example.com",
    "www.example.com/a?b=1",
    "example.com/post",
    "https://youtu.be/dQw4w9WgXcQ",
    "  https://example.com/x  ",
  ])("treats %s as a link", (s) => expect(looksLikeLink(s)).toBe(true));

  it.each([
    "",
    "Retrieval augmented generation fetches documents first.",
    "see https://example.com for details",
    "Dr. Smith said hello",
    "just words",
  ])("treats %j as text", (s) => expect(looksLikeLink(s)).toBe(false));
});

describe("progress wording", () => {
  it("names the pipeline stage while processing", () => {
    expect(describeProgress("processing", "extracting")).toBe("Extracting notes with citations");
    expect(describeProgress("processing", null)).toBe("Processing");
    expect(describeProgress("ready", null)).toBe("Ready to approve");
    expect(describeProgress("needs_track", null)).toBe("Which track?");
  });

  it("shortens addresses and hides content hashes", () => {
    expect(shortUri("https://www.example.com/post/")).toBe("example.com/post");
    expect(shortUri("sha256:abc")).toBe("pasted text or uploaded file");
  });
});
