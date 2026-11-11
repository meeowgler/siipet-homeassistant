import { render } from "lit";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { SiiPetVisitEditor } from "../src/edit-view";
import {
  catsResult,
  DAY,
  fakeHass,
  find,
  findAll,
  LINGERING,
  mount,
  POOP,
  sent,
  settle,
  stubConfirmationDialog,
  stubTileParts,
  text,
  type TestCard,
  withLocale,
} from "./helpers";

beforeAll(async () => {
  stubTileParts();
  await import("../src/siipet-visits-card");
});

// A test that needs a delete confirmation stubs window.loadCardHelpers itself;
// this keeps it at the tile part stub's default between tests.
beforeEach(() => {
  stubTileParts();
});

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

type Part = HTMLElement & Record<string, unknown>;

/** Tap a timeline row and return the editor that opens. */
async function openVisit(card: TestCard, index = 0): Promise<HTMLElement> {
  findAll(card, ".visit")[index].dispatchEvent(
    new CustomEvent("action", { detail: { action: "tap" } }),
  );
  await settle(card);
  const editor = find(card, "siipet-visit-editor");
  expect(editor).not.toBeNull();
  return editor!;
}

function inEditor(editor: HTMLElement, selector: string): Part | null {
  return editor.shadowRoot!.querySelector(selector) as Part | null;
}

function allInEditor(editor: HTMLElement, selector: string): Part[] {
  return [...editor.shadowRoot!.querySelectorAll(selector)] as Part[];
}

function pickType(editor: HTMLElement, type: string): void {
  inEditor(editor, "ha-control-select.type")!.dispatchEvent(
    new CustomEvent("value-changed", { detail: { value: type } }),
  );
}

async function typeMemo(editor: HTMLElement, value: string): Promise<void> {
  const input = inEditor(editor, ".memo-input") as unknown as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event("input"));
  await settle();
}

describe("edit view", () => {
  it("leaves the camera out of the header of a visit without a camera label", async () => {
    const card = await mount(fakeHass());
    const editor = await openVisit(card, 1);

    expect(text(inEditor(editor, '.header [slot="secondary"]'))).toBe(
      "Sun, Sep 27 · Lingering · 25 s",
    );
  });

  it("opens a visit and resolves its recording", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);

    expect(find(card, ".timeline")).toBeNull();
    expect(text(inEditor(editor, '.header [slot="primary"]'))).toBe("20:11 · Luna");
    expect(text(inEditor(editor, '.header [slot="secondary"]'))).toBe(
      "Sun, Sep 27 · Poop · 57 s · Soft stool · Bathroom",
    );
    expect(sent(fake).at(-1)).toEqual({
      type: "media_source/resolve_media",
      media_content_id: "media-source://siipet/visit/ev-1",
    });
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1.mp4");
    expect(video.getAttribute("poster")).toBe(POOP.cover);
    expect(inEditor(editor, ".stool-photo")?.getAttribute("src")).toBe(POOP.stool);
    expect(text(inEditor(editor, ".stool-label"))).toBe("Stool photo");
    expect(text(inEditor(editor, ".reasons"))).toBe("Soft stool");
  });

  it("labels the stool photo even when the visit has no abnormal reasons", async () => {
    const day = { summary: { visits: 1, pee: 0, poop: 1, abnormal: 0 } };
    const fake = fakeHass({
      day: { ...day, visits: [{ ...POOP, abnormal: false, abnormal_reasons: [] }] },
    });
    const editor = await openVisit(await mount(fake));
    expect(inEditor(editor, ".stool-photo")?.getAttribute("src")).toBe(POOP.stool);
    expect(text(inEditor(editor, ".stool-label"))).toBe("Stool photo");
    expect(text(inEditor(editor, ".reasons"))).toBe("");
  });

  it("shows the stool photo whole as a small thumbnail to the right of its label", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    const row = inEditor(editor, ".stool-row")!;
    const photo = inEditor(editor, ".stool-photo") as unknown as HTMLElement;
    expect(row.lastElementChild).toBe(photo);
    expect(
      inEditor(editor, ".stool-label")!.compareDocumentPosition(photo) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const computed = getComputedStyle(photo);
    expect(computed.objectFit).toBe("contain");
    expect(computed.height).toBe("56px");
    expect(computed.width).toBe("auto");
  });

  it("opens the stool photo full screen on a tap anywhere on its row", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    const dialog = inEditor(editor, ".stool-dialog") as unknown as HTMLDialogElement;
    expect(dialog.open).toBe(false);
    expect(inEditor(editor, ".stool-row")?.getAttribute("role")).toBe("button");

    inEditor(editor, ".stool-label")!.dispatchEvent(new Event("click", { bubbles: true }));
    await settle();

    expect(dialog.open).toBe(true);
    expect(inEditor(editor, ".stool-dialog-photo")?.getAttribute("src")).toBe(POOP.stool);
  });

  it("sizes the full screen stool photo to the dialog and keeps it whole", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    inEditor(editor, ".stool-row")!.dispatchEvent(new Event("click"));
    await settle();
    const computed = getComputedStyle(
      inEditor(editor, ".stool-dialog-photo") as unknown as HTMLElement,
    );
    expect(computed.width).toBe("100%");
    expect(computed.height).toBe("100%");
    expect(computed.objectFit).toBe("contain");
  });

  it("opens the stool photo full screen on Enter on its row", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    inEditor(editor, ".stool-row")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await settle();

    const dialog = inEditor(editor, ".stool-dialog") as unknown as HTMLDialogElement;
    expect(dialog.open).toBe(true);
  });

  it("shows the reasons of a visit without a stool photo in a row that opens nothing", async () => {
    const day = { summary: { visits: 1, pee: 0, poop: 1, abnormal: 1 } };
    const fake = fakeHass({ day: { ...day, visits: [{ ...POOP, stool: null }] } });
    const editor = await openVisit(await mount(fake));
    const row = inEditor(editor, ".stool-row")!;
    expect(text(inEditor(editor, ".reasons"))).toBe("Soft stool");
    expect(row.getAttribute("role")).toBeNull();
    expect(row.getAttribute("tabindex")).toBeNull();
    expect(inEditor(editor, ".stool-label")).toBeNull();
    expect(inEditor(editor, ".stool-photo")).toBeNull();
  });

  it("closes the full screen stool photo on a tap on the close button", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    inEditor(editor, ".stool-row")!.dispatchEvent(new Event("click"));
    await settle();
    const dialog = inEditor(editor, ".stool-dialog") as unknown as HTMLDialogElement;
    expect(dialog.open).toBe(true);

    inEditor(editor, ".stool-dialog-close")!.dispatchEvent(new Event("click", { bubbles: true }));
    await settle();

    expect(dialog.open).toBe(false);
  });

  it("closes the full screen stool photo on a tap on the enlarged photo or the backdrop", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    inEditor(editor, ".stool-row")!.dispatchEvent(new Event("click"));
    await settle();
    const dialog = inEditor(editor, ".stool-dialog") as unknown as HTMLDialogElement;
    expect(dialog.open).toBe(true);

    dialog.dispatchEvent(new Event("click", { bubbles: true }));
    await settle();

    expect(dialog.open).toBe(false);
  });

  it("keeps the stool dialog hidden in its styles until it opens", () => {
    const cssText = (SiiPetVisitEditor.styles as { cssText?: string }[])
      .map((style) => style.cssText ?? "")
      .join("\n");
    expect(cssText).toMatch(/\.stool-dialog:not\(\[open\]\)\s*\{[^}]*display:\s*none/);
    expect(cssText).not.toMatch(/\.stool-dialog\s*\{[^}]*display:\s*flex/);
  });

  it("gives the video a full-width 9:16 box up to 70vh that crops instead of side bars", () => {
    const cssText = (SiiPetVisitEditor.styles as { cssText?: string }[])
      .map((style) => style.cssText ?? "")
      .join("\n");
    const videoRule = cssText.match(/video\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(videoRule).toMatch(/(^|[^-])width:\s*100%/);
    expect(videoRule).toMatch(/aspect-ratio:\s*9 \/ 16/);
    expect(videoRule).toMatch(/max-height:\s*70vh/);
    expect(videoRule).toMatch(/object-fit:\s*cover/);
    expect(videoRule).not.toMatch(/align-self:\s*center/);
  });

  it("shows the whole recording in full screen", () => {
    const cssText = (SiiPetVisitEditor.styles as { cssText?: string }[])
      .map((style) => style.cssText ?? "")
      .join("\n");
    expect(cssText).toMatch(/video:fullscreen\s*\{[^}]*object-fit:\s*contain/);
  });

  it("renders no stool dialog for a visit without a stool photo", async () => {
    const editor = await openVisit(await mount(fakeHass()), 1);
    expect(inEditor(editor, ".stool-dialog")).toBeNull();
  });

  it("explains a recording that the browser cannot play", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    inEditor(editor, "video")!.dispatchEvent(new Event("error"));
    await settle();
    expect(text(inEditor(editor, ".video-note"))).toBe(
      "This browser cannot play the recording. Safari and the Home Assistant app can.",
    );
  });

  it("renews the recording after a playback error", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);
    inEditor(editor, "video")!.dispatchEvent(new Event("error"));
    await settle();
    expect(inEditor(editor, "video")).toBeNull();

    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        return { url: "https://video.example/ev-1-renewed.mp4", mime_type: "video/mp4" };
      }
      return original(message);
    });
    // A new visit object with the same event id, as a refreshed day read gives it.
    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video).not.toBeNull();
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-renewed.mp4");
  });

  it("recovers a renewal that was already pending when the playback error happened", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    let releaseRenewal!: () => void;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        if (resolves === 1) {
          return { url: "https://video.example/ev-1-a.mp4", mime_type: "video/mp4" };
        }
        return new Promise((resolve) => {
          releaseRenewal = () =>
            resolve({ url: "https://video.example/ev-1-b.mp4", mime_type: "video/mp4" });
        });
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    inEditor(editor, "video")!.dispatchEvent(new Event("error"));
    await settle();
    expect(inEditor(editor, "video")).toBeNull();

    releaseRenewal();
    await settle(card);

    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video).not.toBeNull();
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-b.mp4");
  });

  it("does not ask for a recording that is on the camera only", async () => {
    const day = { summary: { visits: 1, pee: 0, poop: 1, abnormal: 1 } };
    const fake = fakeHass({ day: { ...day, visits: [{ ...POOP, has_video: false }] } });
    const editor = await openVisit(await mount(fake));
    expect(inEditor(editor, "video")).toBeNull();
    expect(text(inEditor(editor, ".video-note"))).toBe("Recording is on the camera only.");
    expect(sent(fake).map((message) => message.type)).not.toContain("media_source/resolve_media");
  });

  it("keeps Save off until a field changes, then sends only the change", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);
    expect(inEditor(editor, ".save")?.disabled).toBe(true);

    pickType(editor, "pee");
    await settle();
    expect(inEditor(editor, ".save")?.disabled).toBe(false);
    fake.callWS.mockClear();

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(fake.callService).toHaveBeenCalledWith(
      "siipet",
      "update_visit",
      { event_id: "ev-1", type: "pee" },
      undefined,
      false,
    );
    expect(find(card, "siipet-visit-editor")).toBeNull();
    expect(sent(fake).map((message) => message.type)).toEqual([
      "siipet/cats",
      "siipet/day",
      "siipet/calendar",
    ]);
  });

  it("keeps at least one cat on", async () => {
    const fake = fakeHass();
    const editor = await openVisit(await mount(fake));
    const [luna, milo] = allInEditor(editor, "ha-control-button.cat");
    expect(luna.classList.contains("on")).toBe(true);

    luna.click();
    await settle();
    expect(luna.classList.contains("on")).toBe(true);

    milo.click();
    await settle();
    luna.click();
    await settle();
    expect(luna.classList.contains("on")).toBe(false);
    expect(milo.classList.contains("on")).toBe(true);

    inEditor(editor, ".save")!.click();
    await settle();
    expect(fake.callService.mock.calls[0][2]).toEqual({ event_id: "ev-1", cats: ["dev-milo"] });
  });

  it("asks for a type when a visit of unknown type gets a cat", async () => {
    const fake = fakeHass({
      cats: catsResult({ unknown: { device_id: "dev-unknown", waiting: 1 } }),
    });
    const card = await mount(fake, { cat: "dev-unknown" });
    const editor = await openVisit(card);
    expect(text(inEditor(editor, '.header [slot="primary"]'))).toBe("03:12 · Unknown");

    allInEditor(editor, "ha-control-button.cat")[0].click();
    await settle();
    expect(inEditor(editor, ".save")?.disabled).toBe(true);
    expect(text(inEditor(editor, ".hint"))).toBe("Pick a type as well.");

    pickType(editor, "poop");
    await settle();
    inEditor(editor, ".save")!.click();
    await settle();
    expect(fake.callService.mock.calls[0][2]).toEqual({
      event_id: "ev-9",
      cats: ["dev-luna"],
      type: "poop",
    });
  });

  it("counts the memo characters and sends the memo trimmed", async () => {
    const fake = fakeHass();
    const editor = await openVisit(await mount(fake));
    await typeMemo(editor, "  soft  ");
    expect(text(inEditor(editor, ".counter"))).toBe("8/200");
    expect(inEditor(editor, ".memo-input")?.getAttribute("maxlength")).toBe("200");

    inEditor(editor, ".save")!.click();
    await settle();
    expect(fake.callService.mock.calls[0][2]).toEqual({ event_id: "ev-1", note: "soft" });
  });

  it("shows the error of a failed save and keeps the inputs", async () => {
    const fake = fakeHass();
    fake.callService.mockRejectedValue({
      code: "home_assistant_error",
      message: "SiiPet could not save the visit",
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    await typeMemo(editor, "soft");

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(find(card, "siipet-visit-editor")).toBe(editor);
    expect(text(inEditor(editor, ".error"))).toBe("SiiPet could not save the visit");
    expect((inEditor(editor, ".memo-input") as unknown as HTMLInputElement).value).toBe("soft");
  });

  it("keeps the Save and Delete text in a span", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    expect(inEditor(editor, ".save")!.querySelector("span")?.textContent).toBe("Save");
    expect(inEditor(editor, ".delete")?.label).toBe("Delete");
    expect(inEditor(editor, ".delete")!.querySelector("span")?.textContent).toBe("Delete");
  });

  it("opens a confirmation dialog with a warning before deleting", async () => {
    const showConfirmationDialog = stubConfirmationDialog(true);
    const editor = await openVisit(await mount(fakeHass()));

    inEditor(editor, ".delete")!.click();
    await settle();

    expect(showConfirmationDialog).toHaveBeenCalledWith(editor, {
      title: "Delete this visit?",
      text: "SiiPet deletes the visit and its recording. You cannot undo this.",
      confirmText: "Delete",
      dismissText: "Cancel",
      destructive: true,
    });
  });

  it("deletes after confirming the dialog", async () => {
    stubConfirmationDialog(true);
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);

    inEditor(editor, ".delete")!.click();
    await settle(card);

    expect(fake.callService).toHaveBeenCalledWith(
      "siipet",
      "delete_visit",
      { event_id: "ev-1" },
      undefined,
      false,
    );
    expect(find(card, "siipet-visit-editor")).toBeNull();
  });

  it("keeps the editor open and does not delete when the dialog is canceled", async () => {
    stubConfirmationDialog(false);
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);

    inEditor(editor, ".delete")!.click();
    await settle(card);

    expect(fake.callService).not.toHaveBeenCalled();
    expect(find(card, "siipet-visit-editor")).toBe(editor);
  });

  it("falls back to window.confirm when the card helpers have no confirmation dialog", async () => {
    const confirm = vi.fn().mockReturnValue(true);
    vi.stubGlobal("confirm", confirm);
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);

    inEditor(editor, ".delete")!.click();
    await settle(card);

    expect(confirm).toHaveBeenCalledWith(
      "Delete this visit?\nSiiPet deletes the visit and its recording. You cannot undo this.",
    );
    expect(fake.callService).toHaveBeenCalledWith(
      "siipet",
      "delete_visit",
      { event_id: "ev-1" },
      undefined,
      false,
    );
  });

  it("keeps the value-changed event of the type inside the editor", async () => {
    const card = await mount(fakeHass());
    const editor = await openVisit(card);
    const heard = vi.fn();
    card.addEventListener("value-changed", heard);
    inEditor(editor, "ha-control-select.type")!.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: "pee" },
        bubbles: true,
        composed: true,
      }),
    );
    await settle(card);
    card.removeEventListener("value-changed", heard);

    expect(heard).not.toHaveBeenCalled();
    expect(inEditor(editor, ".save")?.disabled).toBe(false);
  });

  it("renders each type's name next to its icon in one row", async () => {
    const editor = await openVisit(await mount(fakeHass()));
    const options = inEditor(editor, "ha-control-select.type")?.options as {
      value: string;
      label?: string;
      ariaLabel?: string;
      icon: unknown;
    }[];
    const pee = options.find((option) => option.value === "pee")!;
    expect(pee.label).toBeUndefined();
    expect(pee.ariaLabel).toBe("Pee");

    const container = document.createElement("div");
    render(pee.icon, container);
    expect(text(container)).toBe("Pee");
    expect(container.querySelector("ha-icon")?.getAttribute("icon")).toBe("mdi:water");
  });

  it("shows Delete only to admins", async () => {
    const editor = await openVisit(await mount(fakeHass({}, false)));
    expect(inEditor(editor, ".delete")).toBeNull();
  });

  it("goes back from the header and brings the visit into view", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card, 1);
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    fake.callWS.mockClear();

    inEditor(editor, ".header")!.dispatchEvent(
      new CustomEvent("action", { detail: { action: "tap" } }),
    );
    await settle(card);
    expect(find(card, "siipet-visit-editor")).toBeNull();
    expect(sent(fake)).toEqual([]);
    expect(scroll).toHaveBeenCalledOnce();
    expect(scroll.mock.contexts[0]).toBe(find(card, '.visit[data-event="ev-2"]'));
  });

  it("keeps the editor open for a back tap during a held save", async () => {
    const fake = fakeHass();
    let release!: (value?: unknown) => void;
    fake.callService.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    const card = await mount(fake);
    const editor = await openVisit(card);
    pickType(editor, "pee");
    await settle();

    inEditor(editor, ".save")!.click();
    await settle();

    inEditor(editor, ".header")!.dispatchEvent(
      new CustomEvent("action", { detail: { action: "tap" } }),
    );
    await settle(card);
    expect(find(card, "siipet-visit-editor")).toBe(editor);

    release();
    await settle(card);
    expect(find(card, "siipet-visit-editor")).toBeNull();
  });

  it("disables the cats, the type, and the memo while a save is pending", async () => {
    const fake = fakeHass();
    let release!: (value?: unknown) => void;
    fake.callService.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
    const card = await mount(fake);
    const editor = await openVisit(card);
    pickType(editor, "pee");
    await settle();

    inEditor(editor, ".save")!.click();
    await settle();

    expect(inEditor(editor, ".save")?.disabled).toBe(true);
    expect(inEditor(editor, ".delete")?.disabled).toBe(true);
    const [luna, milo] = allInEditor(editor, "ha-control-button.cat");
    expect(luna.disabled).toBe(true);
    expect(inEditor(editor, "ha-control-select.type")?.disabled).toBe(true);
    expect((inEditor(editor, ".memo-input") as unknown as HTMLInputElement).disabled).toBe(true);

    // The guard on the handler matters as much as the `disabled` property: the
    // stubbed tile parts do not enforce it themselves.
    milo.click();
    await settle();
    expect(milo.classList.contains("on")).toBe(false);

    release();
    await settle(card);
  });

  it("ignores a close event for a visit other than the one shown", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);
    fake.callWS.mockClear();

    editor.dispatchEvent(
      new CustomEvent("siipet-close", { detail: { changed: true, eventId: "ev-2" } }),
    );
    await settle(card);

    expect(find(card, "siipet-visit-editor")).toBe(editor);
    expect(sent(fake).map((message) => message.type)).toEqual([
      "siipet/cats",
      "siipet/day",
      "siipet/calendar",
    ]);
  });

  it("sends the type again after a save fails with a partial edit", async () => {
    const fake = fakeHass();
    fake.callService.mockRejectedValueOnce({
      code: "home_assistant_error",
      message: "SiiPet could not finish the edit",
      translation_key: "edit_partial",
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const [, milo] = allInEditor(editor, "ha-control-button.cat");
    milo.click();
    await settle();

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(find(card, "siipet-visit-editor")).toBe(editor);
    expect(text(inEditor(editor, ".error"))).toBe("SiiPet could not finish the edit");
    expect(inEditor(editor, ".save")?.disabled).toBe(false);

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(fake.callService).toHaveBeenLastCalledWith(
      "siipet",
      "update_visit",
      { event_id: "ev-1", cats: ["dev-luna", "dev-milo"], type: "poop" },
      undefined,
      false,
    );
  });

  it("shows a partial edit in the language of the profile", async () => {
    const fake = fakeHass();
    fake.hass = withLocale(fake.hass, { language: "pl" });
    fake.callService.mockRejectedValueOnce({
      code: "home_assistant_error",
      message: "SiiPet could not finish the edit",
      translation_domain: "siipet",
      translation_key: "edit_partial",
      translation_placeholders: {
        event_id: "ev-1",
        error: "timeout",
        type: "poop",
      },
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const [, milo] = allInEditor(editor, "ha-control-button.cat");
    milo.click();
    await settle();

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(text(inEditor(editor, ".error"))).toBe(
      "SiiPet mógł nie zastosować całej zmiany wizyty ev-1: timeout. Sprawdź wizytę, a potem wywołaj akcję ponownie z typem poop.",
    );

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(fake.callService).toHaveBeenLastCalledWith(
      "siipet",
      "update_visit",
      { event_id: "ev-1", cats: ["dev-luna", "dev-milo"], type: "poop" },
      undefined,
      false,
    );
  });

  it.each([
    { action: "save", fails: false },
    { action: "save", fails: true },
    { action: "delete", fails: false },
    { action: "delete", fails: true },
  ])("tells when a $action starts and ends (fails: $fails)", async ({ action, fails }) => {
    stubConfirmationDialog(true);
    const fake = fakeHass();
    if (fails) {
      fake.callService.mockRejectedValue({ message: "boom" });
    }
    const editor = document.createElement("siipet-visit-editor") as HTMLElement &
      Record<string, unknown>;
    editor.hass = fake.hass;
    editor.visit = POOP;
    editor.cats = catsResult().cats;
    const events: string[] = [];
    editor.addEventListener("siipet-busy", (ev) => {
      events.push(`busy=${(ev as CustomEvent<{ busy: boolean }>).detail.busy}`);
    });
    editor.addEventListener("siipet-close", () => events.push("close"));
    document.body.append(editor);
    await settle();

    if (action === "save") {
      pickType(editor, "pee");
      await settle();
      inEditor(editor, ".save")!.click();
    } else {
      inEditor(editor, ".delete")!.click();
    }
    await settle();

    expect(events).toEqual(
      fails ? ["busy=true", "busy=false"] : ["busy=true", "close", "busy=false"],
    );
  });

  it("keeps the form when a refresh brings a new visit object for the same event", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);
    await typeMemo(editor, "note");

    const refreshed = {
      ...POOP,
      cover: "/api/siipet/image/cover/ev-1?authSig=z",
      stool: "/api/siipet/image/stool/ev-1?authSig=z",
    };
    fake.results.day = { ...fake.results.day, visits: [refreshed, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    const reopened = find(card, "siipet-visit-editor");
    expect(reopened).toBe(editor);
    const video = inEditor(reopened!, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("poster")).toBe(refreshed.cover);
    expect(inEditor(reopened!, ".stool-photo")?.getAttribute("src")).toBe(refreshed.stool);
    expect((inEditor(reopened!, ".memo-input") as unknown as HTMLInputElement).value).toBe("note");
  });

  it("renews the recording URL on a refresh when the video is not playing", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        return { url: `https://video.example/ev-1-${resolves}.mp4`, mime_type: "video/mp4" };
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-1.mp4");

    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-2.mp4");
  });

  it("does not renew the recording URL while the video is playing", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        return { url: `https://video.example/ev-1-${resolves}.mp4`, mime_type: "video/mp4" };
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-1.mp4");
    await video.play();

    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-1.mp4");
  });

  it("keeps the current recording after a failed renewal", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        if (resolves === 1) {
          return { url: "https://video.example/ev-1-a.mp4", mime_type: "video/mp4" };
        }
        throw { message: "Media not found" };
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-a.mp4");

    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    const stillVideo = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(stillVideo).not.toBeNull();
    expect(stillVideo.getAttribute("src")).toBe("https://video.example/ev-1-a.mp4");
    expect(inEditor(editor, ".video-note")).toBeNull();
  });

  it("keeps the current recording when the video starts while a renewal is pending", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    let releaseSecond!: () => void;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        if (resolves === 1) {
          return { url: "https://video.example/ev-1-a.mp4", mime_type: "video/mp4" };
        }
        return new Promise((resolve) => {
          releaseSecond = () =>
            resolve({ url: "https://video.example/ev-1-b.mp4", mime_type: "video/mp4" });
        });
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-a.mp4");

    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    await video.play();
    releaseSecond();
    await settle(card);

    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-a.mp4");
  });

  it("applies only the latest resolve when two answer out of order", async () => {
    const fake = fakeHass();
    const original = fake.callWS.getMockImplementation() as (
      message: Record<string, unknown>,
    ) => Promise<unknown>;
    let resolves = 0;
    let releaseFirstRenewal!: () => void;
    fake.callWS.mockImplementation(async (message: Record<string, unknown>) => {
      if (message.type === "media_source/resolve_media") {
        resolves += 1;
        if (resolves === 1) {
          return { url: "https://video.example/ev-1-0.mp4", mime_type: "video/mp4" };
        }
        if (resolves === 2) {
          return new Promise((resolve) => {
            releaseFirstRenewal = () =>
              resolve({ url: "https://video.example/ev-1-1.mp4", mime_type: "video/mp4" });
          });
        }
        return { url: "https://video.example/ev-1-2.mp4", mime_type: "video/mp4" };
      }
      return original(message);
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const video = inEditor(editor, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-0.mp4");

    // First refresh: its renewal (the 2nd resolve call) is held.
    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    // Second refresh: its renewal (the 3rd resolve call) answers right away.
    fake.results.day = { ...fake.results.day, visits: [{ ...POOP }, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-2.mp4");

    // The held first renewal answers last and must not override the second's answer.
    releaseFirstRenewal();
    await settle(card);
    expect(video.getAttribute("src")).toBe("https://video.example/ev-1-2.mp4");
  });

  it("keeps the opened visit as the Save baseline through a refresh", async () => {
    const fake = fakeHass();
    const card = await mount(fake);
    const editor = await openVisit(card);
    pickType(editor, "pee");
    await settle();

    const refreshed = {
      ...POOP,
      note: "from the app",
      cover: "/api/siipet/image/cover/ev-1?authSig=z",
      stool: "/api/siipet/image/stool/ev-1?authSig=z",
    };
    fake.results.day = { ...fake.results.day, visits: [refreshed, LINGERING] };
    fake.listeners.get("ready")!();
    await settle(card);

    const reopened = find(card, "siipet-visit-editor");
    expect(reopened).toBe(editor);
    const video = inEditor(reopened!, "video") as unknown as HTMLVideoElement;
    expect(video.getAttribute("poster")).toBe(refreshed.cover);
    expect(inEditor(reopened!, ".stool-photo")?.getAttribute("src")).toBe(refreshed.stool);

    inEditor(reopened!, ".save")!.click();
    await settle(card);
    expect(fake.callService).toHaveBeenCalledWith(
      "siipet",
      "update_visit",
      { event_id: "ev-1", type: "pee" },
      undefined,
      false,
    );
  });

  it("keeps the partial edit flag across an unrelated failure", async () => {
    const fake = fakeHass();
    fake.callService
      .mockRejectedValueOnce({
        code: "home_assistant_error",
        message: "SiiPet could not finish the edit",
        translation_key: "edit_partial",
      })
      .mockRejectedValueOnce({ code: "home_assistant_error", message: "Connection lost" });
    const card = await mount(fake);
    const editor = await openVisit(card);
    const [, milo] = allInEditor(editor, "ha-control-button.cat");
    milo.click();
    await settle();

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(text(inEditor(editor, ".error"))).toBe("SiiPet could not finish the edit");

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(text(inEditor(editor, ".error"))).toBe("Connection lost");

    inEditor(editor, ".save")!.click();
    await settle(card);
    expect(fake.callService).toHaveBeenLastCalledWith(
      "siipet",
      "update_visit",
      { event_id: "ev-1", cats: ["dev-luna", "dev-milo"], type: "poop" },
      undefined,
      false,
    );
  });

  it("shows the message of a failed video resolve", async () => {
    const fake = fakeHass({
      fail: { "media_source/resolve_media": { message: "Media not found" } },
    });
    const editor = await openVisit(await mount(fake));
    expect(text(inEditor(editor, ".video-note"))).toBe("Media not found");
  });

  it("shows the error of a failed delete and keeps the editor open", async () => {
    stubConfirmationDialog(true);
    const fake = fakeHass();
    fake.callService.mockRejectedValue({
      code: "home_assistant_error",
      message: "SiiPet could not delete the visit",
    });
    const card = await mount(fake);
    const editor = await openVisit(card);

    inEditor(editor, ".delete")!.click();
    await settle(card);

    expect(find(card, "siipet-visit-editor")).toBe(editor);
    expect(text(inEditor(editor, ".error"))).toBe("SiiPet could not delete the visit");
  });
});

describe("locale", () => {
  it("shows the date and time of the visit in the profile locale", async () => {
    const fake = fakeHass();
    fake.hass = withLocale(fake.hass, {
      language: "pl",
      time_format: "language",
    });
    const card = await mount(fake);
    const editor = await openVisit(card);
    expect(text(inEditor(editor, '.header [slot="primary"]'))).toBe("20:11 · Luna");
    expect(text(inEditor(editor, '.header [slot="secondary"]'))).toContain("niedz., 27 wrz");
  });

  it("shows the editor in Polish", async () => {
    const fake = fakeHass();
    fake.hass = withLocale(fake.hass, { language: "pl" });
    const card = await mount(fake);
    const editor = await openVisit(card);
    expect(inEditor(editor, ".save")!.querySelector("span")?.textContent).toBe("Zapisz");
    expect(inEditor(editor, ".delete")?.label).toBe("Usuń");
    expect(inEditor(editor, ".memo-input")?.getAttribute("placeholder")).toBe("Notatka");

    const showConfirmationDialog = stubConfirmationDialog(false);
    inEditor(editor, ".delete")!.click();
    await settle(card);
    expect(showConfirmationDialog).toHaveBeenCalledWith(editor, {
      title: "Usunąć tę wizytę?",
      text: "SiiPet usunie wizytę i jej nagranie. Tego nie można cofnąć.",
      confirmText: "Usuń",
      dismissText: "Anuluj",
      destructive: true,
    });
  });

  it("translates the video note again after a language change", async () => {
    const fake = fakeHass({ day: { ...DAY, visits: [{ ...POOP, has_video: false }] } });
    fake.hass = withLocale(fake.hass, { language: "pl" });
    const card = await mount(fake);
    const editor = await openVisit(card);
    expect(text(inEditor(editor, ".video-note"))).toBe("Nagranie jest tylko w kamerze.");

    card.hass = withLocale(fake.hass, { language: "en" });
    await settle(card);
    expect(text(inEditor(editor, ".video-note"))).toBe("Recording is on the camera only.");
  });
});
