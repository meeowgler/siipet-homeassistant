// Each test file has its own element registry, so this file can load the card before the app.

import { expect, it } from "vitest";

import { stubTileParts } from "./helpers";

it("defines its elements when the module loads, before the app defines home-assistant", async () => {
  // The app page has the root element in its HTML before the app bundle defines it.
  document.body.append(document.createElement("home-assistant"));
  stubTileParts();
  await import("../src/siipet-visits-card");
  const entries = (window as { customCards?: { type: string }[] }).customCards;
  expect(entries?.some((entry) => entry.type === "siipet-visits-card")).toBe(true);
  expect(customElements.get("home-assistant")).toBeUndefined();
  expect(customElements.get("siipet-visits-card")).toBeDefined();
  expect(customElements.get("siipet-visit-editor")).toBeDefined();
});
