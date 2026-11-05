// The edit view of one visit: recording, stool photo, cats, type, memo, Save, and Delete.

import { css, html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";

import {
  deleteVisit,
  errorText,
  type Failure,
  isPartialEdit,
  resolveVideo,
  updateVisit,
} from "./api";
import { changedFields, type EditForm, initialForm } from "./changes";
import { dayLabel, durationText, timeLabel, TYPE_STYLE } from "./format";
import { localization, type Localization } from "./localize";
import { optionRow } from "./option-row";
import { cardStyles } from "./styles";
import type { Cat, HomeAssistant, Visit } from "./types";

const MEMO_LENGTH = 200;
const TYPES = ["pee", "poop", "lingering"] as const;

interface ConfirmationDialogParams {
  title?: string;
  text?: string;
  confirmText?: string;
  dismissText?: string;
  destructive?: boolean;
}

interface CardHelpers {
  showConfirmationDialog?: (
    element: HTMLElement,
    params: ConfirmationDialogParams,
  ) => Promise<boolean>;
}

interface HelperWindow {
  loadCardHelpers?: () => Promise<CardHelpers>;
  confirm(message?: string): boolean;
}

export interface CloseDetail {
  changed: boolean;
  /** The event id of the visit this editor showed, so a card that opened another
   * visit while this close was pending (a stale save or delete) can tell the two
   * apart. */
  eventId: string;
}

/** The detail of `siipet-busy`, which the editor fires when a save or a delete starts and ends. */
export interface BusyDetail {
  busy: boolean;
}

/** Why the editor shows a note in place of the recording. */
type VideoNote = "camera_only" | "cannot_play" | Failure;

export class SiiPetVisitEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    visit: { attribute: false },
    cats: { attribute: false },
    l10n: { attribute: false },
    _baseline: { state: true },
    _form: { state: true },
    _video: { state: true },
    _videoNote: { state: true },
    _error: { state: true },
    _busy: { state: true },
    _partialEdit: { state: true },
    _stoolDialogSrc: { state: true },
  };

  static styles = [
    cardStyles,
    css`
      :host {
        display: block;
      }
      .editor {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 0 12px 12px;
      }
      /* The box takes the full width, the same as the timeline poster, and its
         height comes from the aspect ratio and the max height. So it holds its
         size before the recording loads (preload="none" leaves no intrinsic size
         to lay out from). Where the max height wins, object-fit crops the top
         and bottom of the recording. */
      video {
        display: block;
        width: 100%;
        max-height: 70vh;
        aspect-ratio: 9 / 16;
        object-fit: cover;
        border-radius: var(--ha-border-radius-lg, 12px);
        background-color: black;
      }
      video:fullscreen {
        object-fit: contain;
      }
      .video-note,
      .hint,
      .reasons {
        color: var(--secondary-text-color);
      }
      .stool-row {
        display: flex;
        align-items: center;
        gap: 12px;
        --mdc-icon-size: 20px;
      }
      .stool-row[role="button"] {
        cursor: zoom-in;
      }
      .stool-row ha-icon {
        color: var(--secondary-text-color);
      }
      .stool-text {
        flex: 1;
        min-width: 0;
      }
      .stool-photo {
        display: block;
        height: 56px;
        width: auto;
        max-width: 40%;
        object-fit: contain;
        border-radius: var(--ha-border-radius-md, 8px);
      }
      .stool-label {
        color: var(--primary-text-color);
        font-size: var(--ha-font-size-m, 14px);
        font-weight: var(--ha-font-weight-medium, 500);
      }
      .stool-dialog {
        width: 100vw;
        height: 100vh;
        max-width: 100vw;
        max-height: 100vh;
        margin: 0;
        padding: 0;
        border: none;
        background: black;
      }
      .stool-dialog:not([open]) {
        display: none;
      }
      .stool-dialog[open] {
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .stool-dialog::backdrop {
        background: black;
      }
      .stool-dialog-photo {
        max-width: 100vw;
        max-height: 100vh;
        object-fit: contain;
      }
      .stool-dialog-close {
        position: fixed;
        top: 0;
        right: 0;
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        padding: 0;
        color: white;
        background: transparent;
        cursor: pointer;
      }
      ha-control-button.cat img {
        width: 20px;
        height: 20px;
        margin-right: 6px;
        border-radius: 50%;
        object-fit: cover;
      }
      ha-control-button.cat.on,
      ha-control-button.save {
        --control-button-background-color: var(--tile-color);
        --control-button-background-opacity: 1;
        --control-button-icon-color: white;
      }
      ha-control-button.delete {
        --control-button-icon-color: var(--error-color);
      }
      .memo-field {
        position: relative;
      }
      /* No tile feature has a text field, so the memo input copies the look of a feature. */
      .memo-input {
        box-sizing: border-box;
        width: 100%;
        height: 42px;
        padding: 0 64px 0 12px;
        border: none;
        border-radius: var(--ha-border-radius-lg, 12px);
        font: inherit;
        color: var(--primary-text-color);
        background-color: color-mix(in srgb, var(--disabled-color) 20%, transparent);
      }
      .counter {
        position: absolute;
        top: 50%;
        right: 12px;
        transform: translateY(-50%);
        font-size: var(--ha-font-size-s, 12px);
        color: var(--secondary-text-color);
      }
      .error {
        margin: 0;
      }
    `,
  ];

  declare hass?: HomeAssistant;
  declare visit?: Visit;
  declare cats: Cat[];
  declare l10n: Localization;
  /** The visit this editor opened with. Save compares the form with this, not
   * with a refreshed `visit`, so a field changed elsewhere between opens does
   * not look like a change the form itself made. */
  declare _baseline?: Visit;
  declare _form?: EditForm;
  declare _video?: string;
  declare _videoNote?: VideoNote;
  declare _error?: Failure;
  declare _busy: boolean;
  declare _partialEdit: boolean;
  /** The photo shown full screen in `.stool-dialog`, or unset while it is closed. */
  declare _stoolDialogSrc?: string;

  private _resolveSeq = 0;

  constructor() {
    super();
    this.cats = [];
    this.l10n = localization(undefined);
    this._busy = false;
    this._partialEdit = false;
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._stoolDialog()?.close();
  }

  private _stoolDialog(): HTMLDialogElement | null {
    return this.renderRoot.querySelector(".stool-dialog");
  }

  private _openStoolDialog(stool: string): void {
    this._stoolDialogSrc = stool;
    this._stoolDialog()?.showModal();
  }

  private _closeStoolDialog(): void {
    // The native `close` event, which also fires for Escape, clears the source.
    this._stoolDialog()?.close();
  }

  protected willUpdate(changed: PropertyValues<this>): void {
    if (!changed.has("visit") || !this.visit) {
      return;
    }
    const previous = changed.get("visit") as Visit | undefined;
    if (previous?.event_id === this.visit.event_id) {
      // A refreshed visit object for the same event: the Save baseline, the
      // form, the error, and the busy state stay as they are. The cover and
      // the stool photo render straight from `visit`, so they renew on their
      // own. The recording renews too, unless it is playing, so a refresh
      // does not interrupt it.
      if (this.visit.has_video && !this._isVideoPlaying()) {
        void this._resolveVideo(this.visit.event_id);
      }
      return;
    }
    this._baseline = this.visit;
    this._form = initialForm(this.visit);
    this._video = undefined;
    this._videoNote = this.visit.has_video ? undefined : "camera_only";
    this._error = undefined;
    this._partialEdit = false;
    this._stoolDialog()?.close();
    if (this.visit.has_video) {
      void this._resolveVideo(this.visit.event_id);
    }
  }

  private _isVideoPlaying(): boolean {
    const video = this.renderRoot.querySelector("video");
    return video !== null && !video.paused;
  }

  // A video the user started, even one they then paused, must not be reset by a
  // renewal answer that lands after they started it.
  private _isVideoActive(): boolean {
    const video = this.renderRoot.querySelector("video");
    return video !== null && (!video.paused || video.currentTime > 0);
  }

  private async _resolveVideo(eventId: string): Promise<void> {
    const seq = ++this._resolveSeq;
    // A resolve that finds a URL already in place is a background renewal: its
    // failure must keep the working player, not replace it with an error note.
    // Only the first resolve of a visit, which has no player to protect, does.
    const isRenewal = this._video !== undefined;
    try {
      const url = await resolveVideo(this.hass!, eventId);
      if (this.visit?.event_id !== eventId || seq !== this._resolveSeq) {
        return;
      }
      if (this._isVideoActive()) {
        return;
      }
      this._video = url;
      this._videoNote = undefined;
    } catch (err) {
      if (this.visit?.event_id === eventId && seq === this._resolveSeq && !isRenewal) {
        this._videoNote = { error: err };
      }
    }
  }

  private _close(changed: boolean): void {
    const detail: CloseDetail = { changed, eventId: this.visit!.event_id };
    this.dispatchEvent(new CustomEvent<CloseDetail>("siipet-close", { detail }));
  }

  // The card holds a link while a save or a delete runs, so its result stays in view.
  private _setBusy(busy: boolean): void {
    this._busy = busy;
    this.dispatchEvent(new CustomEvent<BusyDetail>("siipet-busy", { detail: { busy } }));
  }

  private _back(): void {
    if (this._busy) {
      return;
    }
    this._close(false);
  }

  private _toggleCat(deviceId: string): void {
    if (this._busy) {
      return;
    }
    const form = this._form!;
    const on = form.cats.includes(deviceId);
    if (on && form.cats.length === 1) {
      return;
    }
    const cats = on ? form.cats.filter((cat) => cat !== deviceId) : [...form.cats, deviceId];
    this._form = { ...form, cats };
  }

  private async _save(data: Record<string, unknown>): Promise<void> {
    this._setBusy(true);
    this._error = undefined;
    try {
      await updateVisit(this.hass!, data);
      this._partialEdit = false;
      this._close(true);
    } catch (err) {
      this._error = { error: err };
      // A later failure for another reason (for example a dropped connection)
      // must not clear a flag an earlier partial edit set: the server's type
      // is still out of step with the visit until a save succeeds.
      if (isPartialEdit(err)) {
        this._partialEdit = true;
      }
    } finally {
      this._setBusy(false);
    }
  }

  private async _confirmDelete(): Promise<boolean> {
    const text = this.l10n.text;
    const win = window as unknown as HelperWindow;
    const helpers = await win.loadCardHelpers?.();
    if (helpers?.showConfirmationDialog) {
      return helpers.showConfirmationDialog(this, {
        title: text.deleteTitle,
        text: text.deleteText,
        confirmText: text.delete,
        dismissText: text.cancel,
        destructive: true,
      });
    }
    return win.confirm(`${text.deleteTitle}\n${text.deleteText}`);
  }

  private async _delete(): Promise<void> {
    if (!(await this._confirmDelete())) {
      return;
    }
    this._setBusy(true);
    this._error = undefined;
    try {
      await deleteVisit(this.hass!, this.visit!.event_id);
      this._close(true);
    } catch (err) {
      this._error = { error: err };
    } finally {
      this._setBusy(false);
    }
  }

  protected render(): TemplateResult | typeof nothing {
    const baseline = this._baseline;
    const current = this.visit;
    const form = this._form;
    if (!baseline || !current || !form) {
      return nothing;
    }
    const check = changedFields(baseline, form, { sendType: this._partialEdit });
    const hint = check.reason === "type_required" ? this.l10n.text.pickType : undefined;
    return html`
      ${this._renderHeader(baseline)}
      <div class="editor">
        ${this._renderVideo(current.cover)} ${this._renderStool(baseline, current.stool)}
        ${this._renderCats(form)} ${this._renderType(form)} ${this._renderMemo(form)}
        ${hint ? html`<div class="hint">${hint}</div>` : nothing}
        ${
          this._error
            ? html`<div class="error">${errorText(this._error.error, this.l10n)}</div>`
            : nothing
        }
        ${this._renderActions(check.data)}
      </div>
      ${current.stool ? this._renderStoolDialog() : nothing}
    `;
  }

  private _renderHeader(visit: Visit): TemplateResult {
    const names = visit.cats.map((cat) => cat.name).join(", ") || this.l10n.text.unknown;
    const secondary = [
      dayLabel(visit.start.slice(0, 10), this.l10n.locale),
      this.l10n.text.types[visit.type],
      durationText(visit.duration),
      ...visit.abnormal_reasons.slice(0, 1),
      // Last, so a long camera name cuts off before the reason.
      ...(visit.camera ? [visit.camera] : []),
    ].join(" · ");
    return html`
      <ha-tile-container class="header" .interactive=${true} @action=${() => this._back()}>
        <ha-tile-icon slot="icon" .icon=${"mdi:arrow-left"}></ha-tile-icon>
        <ha-tile-info slot="info">
          <span slot="primary">${timeLabel(visit.start, this.l10n.locale)} · ${names}</span>
          <span slot="secondary">${secondary}</span>
        </ha-tile-info>
      </ha-tile-container>
    `;
  }

  private _renderType(form: EditForm): TemplateResult {
    const options = TYPES.map((type) => ({
      value: type,
      ariaLabel: this.l10n.text.types[type],
      icon: optionRow(
        html`<ha-icon icon=${TYPE_STYLE[type].icon}></ha-icon>`,
        this.l10n.text.types[type],
      ),
    }));
    return html`
      <ha-control-select
        class="type"
        .options=${options}
        .value=${form.type ?? undefined}
        .label=${this.l10n.text.type}
        .disabled=${this._busy}
        @value-changed=${(ev: CustomEvent<{ value: EditForm["type"] }>) => {
          // As in the tile features, the event does not leave the editor.
          ev.stopPropagation();
          if (this._busy) {
            return;
          }
          this._form = { ...form, type: ev.detail.value };
        }}
      ></ha-control-select>
    `;
  }

  private _renderMemo(form: EditForm): TemplateResult {
    return html`
      <div class="memo-field">
        <input
          class="memo-input"
          type="text"
          maxlength=${MEMO_LENGTH}
          placeholder=${this.l10n.text.memo}
          aria-label=${this.l10n.text.memo}
          .value=${form.note}
          .disabled=${this._busy}
          @input=${(ev: Event) => {
            if (this._busy) {
              return;
            }
            this._form = { ...form, note: (ev.target as HTMLInputElement).value };
          }}
        />
        <span class="counter">${form.note.length}/${MEMO_LENGTH}</span>
      </div>
    `;
  }

  private _renderActions(data: Record<string, unknown> | null): TemplateResult {
    const remove = this.hass?.user?.is_admin
      ? html`
          <ha-control-button
            class="delete"
            .label=${this.l10n.text.delete}
            .disabled=${this._busy}
            @click=${() => this._delete()}
          >
            <span>${this.l10n.text.delete}</span>
          </ha-control-button>
        `
      : nothing;
    return html`
      <ha-control-button-group class="actions">
        <ha-control-button
          class="save"
          .label=${this.l10n.text.save}
          .disabled=${data === null || this._busy}
          @click=${() => data && this._save(data)}
        >
          <span>${this.l10n.text.save}</span>
        </ha-control-button>
        ${remove}
      </ha-control-button-group>
    `;
  }

  private _videoNoteText(note: VideoNote): string {
    if (note === "camera_only") {
      return this.l10n.text.recordingOnCamera;
    }
    if (note === "cannot_play") {
      return this.l10n.text.cannotPlay;
    }
    return errorText(note.error, this.l10n);
  }

  private _renderVideo(cover: string | null): TemplateResult {
    if (this._videoNote !== undefined) {
      return html`<div class="video-note">${this._videoNoteText(this._videoNote)}</div>`;
    }
    // The recordings use H.265, which only some browsers play.
    return html`
      <video
        controls
        playsinline
        preload="none"
        poster=${cover ?? nothing}
        src=${this._video ?? nothing}
        @error=${() => {
          this._videoNote = "cannot_play";
        }}
      ></video>
    `;
  }

  private _renderStool(visit: Visit, stool: string | null): TemplateResult | typeof nothing {
    const reasons = html`<span class="reasons">${visit.abnormal_reasons.join(", ")}</span>`;
    if (!stool) {
      return visit.abnormal_reasons.length === 0
        ? nothing
        : html`<div class="stool-row">${reasons}</div>`;
    }
    return html`
      <div
        class="stool-row"
        role="button"
        tabindex="0"
        @click=${() => this._openStoolDialog(stool)}
        @keydown=${(ev: KeyboardEvent) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this._openStoolDialog(stool);
          }
        }}
      >
        <ha-icon icon="mdi:camera-outline"></ha-icon>
        <div class="stool-text">
          <div class="stool-label">${this.l10n.text.stoolPhoto}</div>
          ${reasons}
        </div>
        <img class="stool-photo" src=${stool} alt=${this.l10n.text.stoolPhoto} />
      </div>
    `;
  }

  private _renderStoolDialog(): TemplateResult {
    return html`
      <dialog
        class="stool-dialog"
        @click=${() => this._closeStoolDialog()}
        @close=${() => {
          this._stoolDialogSrc = undefined;
        }}
      >
        ${
          this._stoolDialogSrc
            ? html`<img
                class="stool-dialog-photo"
                src=${this._stoolDialogSrc}
                alt=${this.l10n.text.stoolPhoto}
              />`
            : nothing
        }
        <button class="stool-dialog-close" aria-label=${this.l10n.text.close}>
          <ha-icon icon="mdi:close"></ha-icon>
        </button>
      </dialog>
    `;
  }

  private _renderCats(form: EditForm): TemplateResult {
    return html`
      <ha-control-button-group class="cat-toggles">
        ${this.cats.map(
          (cat) => html`
            <ha-control-button
              class="cat ${form.cats.includes(cat.device_id) ? "on" : ""}"
              .label=${cat.name}
              .disabled=${this._busy}
              @click=${() => this._toggleCat(cat.device_id)}
            >
              ${cat.avatar ? html`<img src=${cat.avatar} alt="" />` : nothing}
              <span>${cat.name}</span>
            </ha-control-button>
          `,
        )}
      </ha-control-button-group>
    `;
  }
}

if (!customElements.get("siipet-visit-editor")) {
  customElements.define("siipet-visit-editor", SiiPetVisitEditor);
}
