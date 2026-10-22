import { defineConfig } from "@playwright/test";

// Expects the full stack to be running (`make dev`).
export default defineConfig({
  testDir: "tests/e2e",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000" },
});
