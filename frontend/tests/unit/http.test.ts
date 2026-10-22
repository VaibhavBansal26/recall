import { describe, expect, it } from "vitest";
import { wsUrl } from "@/lib/http";

describe("wsUrl", () => {
  it("uses the page's own host over wss when served same-origin on https", () => {
    expect(wsUrl("", { protocol: "https:", host: "recall.example.com" })).toBe(
      "wss://recall.example.com/ws/voice",
    );
  });

  it("uses ws on plain http same-origin", () => {
    expect(wsUrl("", { protocol: "http:", host: "localhost:8080" })).toBe(
      "ws://localhost:8080/ws/voice",
    );
  });

  it("derives the socket from an explicit API url in dev", () => {
    expect(wsUrl("http://localhost:8000", { protocol: "http:", host: "x" })).toBe(
      "ws://localhost:8000/ws/voice",
    );
    expect(wsUrl("https://api.example.com", { protocol: "http:", host: "x" })).toBe(
      "wss://api.example.com/ws/voice",
    );
  });
});
