import { expect, test } from "@playwright/test";

test("typing in the ai-eng track stores utterances and captures a note", async ({ page }) => {
  await page.goto("/session");
  await expect(page.getByTestId("connection")).toHaveText("Connected");

  const said = `Reranking reorders retrieved chunks by relevance ${Date.now()}.`;
  await page.getByLabel("Message").fill(said);
  await page.getByRole("button", { name: "Send" }).click();

  const transcript = page.getByRole("list", { name: "Transcript" });
  await expect(transcript).toContainText("Reranking reorders retrieved chunks");
  await expect(transcript).toContainText("Got it, noted.");
  await expect(page.getByRole("list", { name: "Note list" })).toContainText("Reranking reorders");

  const sessionId = await page.getByTestId("session-id").textContent();
  const api = process.env.E2E_API_URL ?? "http://localhost:8000";
  const body = await (await page.request.get(`${api}/api/sessions/${sessionId}`)).json();
  expect(body.track).toBe("ai-eng");
  expect(body.utterances.map((u: { speaker: string }) => u.speaker)).toEqual([
    "user",
    "assistant",
  ]);
});
