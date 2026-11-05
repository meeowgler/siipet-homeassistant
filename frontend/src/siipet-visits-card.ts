// The SiiPet visits card: the visits of one cat on one day, or the Unknown queue.

import { html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { keyed } from "lit/directives/keyed.js";

import {
  errorText,
  fetchCalendar,
  fetchCats,
  fetchDay,
  fetchQueue,
  fetchVisit,
  type Failure,
  isOutsideWindow,
  isPermanentFailure,
} from "./api";
import {
  daySummaryText,
  queueSummaryText,
  renderCalendar,
  renderCatStrip,
  renderDateBar,
  renderHeader,
  renderTimeline,
} from "./day-view";
import "./edit-view";
import type { BusyDetail, CloseDetail } from "./edit-view";
import { dayLabel, monthOf, shiftDay, shiftMonth, timeLabel } from "./format";
import "./icons";
import {
  cardText,
  localization,
  localizationKey,
  type Localization,
  pageLanguage,
} from "./localize";
import { cardStyles } from "./styles";
import { loadTileParts } from "./tile-parts";
import type {
  CalendarResult,
  CardConfig,
  CatsResult,
  DayResult,
  HassConnection,
  HomeAssistant,
  QueueResult,
  Visit,
  VisitResult,
} from "./types";

// The time since the last successful read after which a visible page reads again.
// Signed image paths last 1 hour, so this margin also covers a card that a
// dashboard view switch detaches and reattaches while it is stale.
const STALE_MS = 30 * 60 * 1000;
// A successful day or queue read schedules another one this long after the last
// read, so a card left open on screen renews its image paths before they expire.
const RENEW_MS = 50 * 60 * 1000;
// A failed cats, day, or queue read tries again after this long. Past days
// ignore visit events, so without it a failed renewal would leave the card stale.
const RETRY_MS = 5 * 60 * 1000;
// The calendar command accepts the current month and the 12 months before it.
const CALENDAR_MONTHS = 12;
// A link such as a notification tap opens one visit with `?siipet_visit=<event_id>`.
const LINK_PARAM = "siipet_visit";
// A save or a delete in one card fires this on `window`, so the other cards read again.
const CHANGED_EVENT = "siipet-visits-changed";

interface ChangedDetail {
  source: SiiPetVisitsCard;
}

// The number of saves and deletes on this page. A card that was detached when
// one happened reads again when it is attached.
let changeCount = 0;

function linkedEventId(): string | undefined {
  return new URLSearchParams(window.location.search).get(LINK_PARAM) || undefined;
}

/** Remove the link from the address and keep the rest, so a reload does not open the visit again. */
function removeLink(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete(LINK_PARAM);
  history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

// The SiiPet event entity ids per entity registry object. Home Assistant
// replaces `hass.entities` when the registry changes, not on a state change,
// so the state updates in between reuse the list.
const eventIdsByRegistry = new WeakMap<HomeAssistant["entities"], string[]>();
const NO_ENTITIES: HomeAssistant["entities"] = {};

function siipetEventIds(entities: HomeAssistant["entities"]): string[] {
  let ids = eventIdsByRegistry.get(entities);
  if (ids === undefined) {
    ids = Object.values(entities)
      .filter((entry) => entry.platform === "siipet" && entry.entity_id.startsWith("event."))
      .map((entry) => entry.entity_id);
    eventIdsByRegistry.set(entities, ids);
  }
  return ids;
}

/** The states of the SiiPet event entities. A new visit changes one of them. */
function eventSignature(hass: HomeAssistant): string {
  return siipetEventIds(hass.entities ?? NO_ENTITIES)
    .map((entityId) => `${entityId}=${hass.states[entityId]?.state ?? ""}`)
    .join("|");
}

export class SiiPetVisitsCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _missing: { state: true },
    _cats: { state: true },
    _cat: { state: true },
    _date: { state: true },
    _month: { state: true },
    _calendars: { state: true },
    _first: { state: true },
    _calendarOpen: { state: true },
    _day: { state: true },
    _queue: { state: true },
    _error: { state: true },
    _editing: { state: true },
    _l10n: { state: true },
  };

  static styles = cardStyles;

  declare hass?: HomeAssistant;
  declare _config?: CardConfig;
  declare _missing?: string[];
  declare _cats?: CatsResult;
  declare _cat?: string;
  declare _date?: string;
  declare _month?: string;
  declare _calendars: Record<string, CalendarResult>;
  declare _first?: string;
  declare _calendarOpen: boolean;
  declare _day?: DayResult;
  declare _queue?: QueueResult;
  declare _error?: Failure;
  declare _editing?: Visit;
  declare _l10n: Localization;

  private _started = false;
  private _partsLoaded = false;
  private _signature?: string;
  // The times of the last successful cats read and day or queue read. The
  // avatar paths come from the first and the other image paths from the second.
  private _catsRead?: number;
  private _dataRead?: number;
  // When the next renewal or retry is due. It outlives a detach and a hidden
  // page, so the card can catch up when it shows again.
  private _dueAt?: number;
  private _timer?: ReturnType<typeof setTimeout>;
  // The value of `changeCount` when the last cats read started.
  private _changesSeen?: number;
  private _connection?: HassConnection;
  // Each day, queue, and calendar read takes the next number of its kind (for the
  // calendar, of its month). A move away and back passes the cat and date checks,
  // so only the answer of the latest number applies.
  private _daySeq = 0;
  private _queueSeq = 0;
  private _calendarSeq = new Map<string, number>();
  private _active?: Promise<void>;
  private _trailing = false;
  // The linked event id this card has read while the address still holds it.
  // A card that does not own the visit leaves the link in the address, so
  // without this it would read the link again on every refresh.
  private _linkEvent?: string;
  // The editor element whose save or delete runs, from its `siipet-busy` events.
  private _busyEditor?: EventTarget;
  // The editor that was busy when a link came. The link waits while that
  // editor stays open, so a failed save keeps its error and its inputs in view.
  private _holdingEditor?: EventTarget;
  // The localization key of the last `hass`. A profile change replaces `hass`
  // and changes this key, so the card renders again with the new locale.
  private _l10nKey?: string;
  // The language whose exception texts the card asked Home Assistant for.
  // Home Assistant forgets integration loads on a language change, so the
  // card asks again for each language.
  private _exceptionsRequested?: string;

  constructor() {
    super();
    this._calendars = {};
    this._calendarOpen = false;
    this._l10n = localization(undefined);
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "cat", selector: { device: { filter: { integration: "siipet", model: "Cat" } } } },
        { name: "hide_cat_picker", selector: { boolean: {} } },
      ],
      // The form passes no language, so the labels follow the language of the page.
      computeLabel: (schema: { name: string }) => {
        const text = cardText(pageLanguage());
        return schema.name === "cat"
          ? text.configCat
          : schema.name === "hide_cat_picker"
            ? text.configHideCatPicker
            : undefined;
      },
      computeHelper: (schema: { name: string }) => {
        const text = cardText(pageLanguage());
        return schema.name === "cat"
          ? text.configCatHelper
          : schema.name === "hide_cat_picker"
            ? text.configHideCatPickerHelper
            : undefined;
      },
    };
  }

  setConfig(config: CardConfig): void {
    const text = cardText(pageLanguage());
    if (config.cat !== undefined && (typeof config.cat !== "string" || config.cat === "")) {
      throw new Error(text.configCatInvalid);
    }
    if (config.hide_cat_picker !== undefined && typeof config.hide_cat_picker !== "boolean") {
      throw new Error(text.configHideCatPickerInvalid);
    }
    const restart =
      this._started &&
      (config.cat !== this._config?.cat ||
        Boolean(config.hide_cat_picker) !== Boolean(this._config?.hide_cat_picker));
    this._config = config;
    if (restart) {
      this._started = false;
      this._cats = undefined;
      this._cat = undefined;
      this._calendars = {};
      this._first = undefined;
      this._calendarOpen = false;
      this._day = undefined;
      this._queue = undefined;
      this._error = undefined;
      this._editing = undefined;
      this._linkEvent = undefined;
      this._holdingEditor = undefined;
    }
  }

  getCardSize(): number {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" as const };
  }

  connectedCallback(): void {
    super.connectedCallback();
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    window.addEventListener("location-changed", this._onNavigate);
    window.addEventListener("popstate", this._onLocationChange);
    window.addEventListener(CHANGED_EVENT, this._onVisitsChanged);
    this._listen();
    // A view switch attaches the card after the navigation event, so a link
    // that came with the switch is read here.
    this._onLocationChange();
    // A dashboard view switch detaches and reattaches the card, which can leave it
    // stale for longer than a visibility change would ever let it go unnoticed,
    // or miss a save in a card of another view.
    const missedChange = this._changesSeen !== undefined && this._changesSeen !== changeCount;
    if (this._due() || missedChange) {
      void this._run(() => this._refresh());
    } else {
      // Pick up the renewal or retry where it left off, instead of reading
      // early or not at all for the rest of the original wait.
      this._armTimer();
    }
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    window.removeEventListener("location-changed", this._onNavigate);
    window.removeEventListener("popstate", this._onLocationChange);
    window.removeEventListener(CHANGED_EVENT, this._onVisitsChanged);
    this._connection?.removeEventListener("ready", this._onReady);
    this._connection = undefined;
    this._clearTimer();
  }

  // Home Assistant sets `hass` on every state change in the house, and the card
  // renders only the locale settings of the user and the translator of Home
  // Assistant from it. An update that changes only `hass` does the hass work
  // here and skips the render unless the locale settings or the translator
  // changed. Home Assistant replaces `hass.localize` only when translations
  // load. The editor keeps the `hass` of its last render, which is enough for
  // its calls.
  protected shouldUpdate(changed: PropertyValues<this>): boolean {
    let relocalized = false;
    if (changed.has("hass")) {
      const key = localizationKey(this.hass);
      if (key !== this._l10nKey || this.hass?.localize !== this._l10n.localize) {
        this._l10nKey = key;
        this._l10n = localization(this.hass);
        relocalized = true;
      }
      this._requestExceptions();
    }
    // A run can change state before its first await. Lit drops a change made
    // here when this returns false, so an update that starts a run renders.
    let ran = false;
    if (this.hass && this._config) {
      if (!this._started) {
        this._started = true;
        ran = true;
        void this._run(() => this._start());
      }
      if (changed.has("hass")) {
        this._listen();
        const signature = eventSignature(this.hass);
        if (this._signature !== undefined && signature !== this._signature && this._showsLatest()) {
          ran = true;
          void this._run(() => this._refresh());
        }
        this._signature = signature;
      }
    }
    const onlyHass = changed.size === 1 && changed.has("hass");
    return ran || relocalized || !this.hasUpdated || !onlyHass;
  }

  /** Ask Home Assistant to load the exception texts of the integration for the
   * language of the user. Home Assistant then replaces `hass.localize`, and the
   * card translates its errors through that. */
  private _requestExceptions(): void {
    const hass = this.hass;
    const language = this._l10n.locale.language;
    if (!hass?.loadBackendTranslation || this._exceptionsRequested === language) {
      return;
    }
    this._exceptionsRequested = language;
    hass.loadBackendTranslation("exceptions", "siipet").catch(() => {
      // The errors keep their messages, and a later update asks again.
      if (this._exceptionsRequested === language) {
        this._exceptionsRequested = undefined;
      }
    });
  }

  private _onVisibilityChange = (): void => {
    if (document.visibilityState === "visible" && this._due()) {
      void this._run(() => this._refresh());
    }
  };

  // A Home Assistant restart makes every signed path invalid, so a new connection reads again.
  private _onReady = (): void => {
    void this._run(() => this._refresh());
  };

  // The card that saved reads again from `_closeEditor`, so it skips its own event.
  private _onVisitsChanged = (ev: Event): void => {
    if (this._started && (ev as CustomEvent<ChangedDetail>).detail?.source !== this) {
      void this._run(() => this._refresh());
    }
  };

  // Home Assistant fires `location-changed` on `window` for each navigation,
  // also for a new tap of the same notification. A navigation reads the link
  // again, so a link that failed, that another card owned, or that a failed
  // save held gets a fresh read. Back and forward (`popstate`) keep the link as read.
  private _onNavigate = (): void => {
    this._linkEvent = undefined;
    this._holdingEditor = undefined;
    this._onLocationChange();
  };

  // Before the first cats, the start reads the link. During a run, `_run`
  // queues a refresh, and a refresh reads the link at its end.
  private _onLocationChange = (): void => {
    if (this._newLink() !== undefined && this._cats) {
      void this._run(() => this._followLink());
    }
  };

  /** Run one start or refresh at a time, and queue at most one more behind it.
   * A trigger that arrives while a run is active marks the queued run instead of
   * starting a second one next to it. The queued run is always a refresh, so a
   * visit that arrived mid-run is read after the active run ends. A config change
   * clears the cat, and the first cats answer after it, in the active run or the
   * queued one, selects the configured cat. */
  private _run(action: () => Promise<void>): Promise<void> {
    if (this._active) {
      this._trailing = true;
      return this._active;
    }
    this._active = this._execute(action);
    return this._active;
  }

  // The callers drop the promise of a run, so a failure shows in the error line
  // instead of leaving the card as an unhandled rejection.
  private async _execute(action: () => Promise<void>): Promise<void> {
    try {
      await action();
    } catch (err) {
      this._error = { error: err };
    } finally {
      this._active = undefined;
      if (this._trailing) {
        this._trailing = false;
        void this._run(() => this._refresh());
      }
    }
  }

  /** The older of the last cats read and the last day or queue read. */
  private _lastRead(): number | undefined {
    const times = [this._catsRead, this._dataRead].filter((time) => time !== undefined);
    return times.length > 0 ? Math.min(...times) : undefined;
  }

  /** Whether the card is stale, or a renewal or retry is due. */
  private _due(): boolean {
    const now = Date.now();
    const lastRead = this._lastRead();
    return (
      (lastRead !== undefined && now - lastRead > STALE_MS) ||
      (this._dueAt !== undefined && now >= this._dueAt)
    );
  }

  /** Arm the renewal after a successful day or queue read. */
  private _scheduleRenew(): void {
    this._dueAt = this._lastRead()! + RENEW_MS;
    this._armTimer();
  }

  /** Arm a retry after a failed read, unless the failure is permanent. The last
   * read times stay as they were. */
  private _scheduleRetry(err: unknown): void {
    if (isPermanentFailure(err)) {
      return;
    }
    this._dueAt = Date.now() + RETRY_MS;
    this._armTimer();
  }

  private _clearTimer(): void {
    if (this._timer !== undefined) {
      clearTimeout(this._timer);
      this._timer = undefined;
    }
  }

  private _armTimer(): void {
    this._clearTimer();
    // A read that lands after the card is removed must not arm a timer that no
    // disconnectedCallback will ever clear. `connectedCallback` arms it again.
    if (!this.isConnected || this._dueAt === undefined) {
      return;
    }
    this._timer = setTimeout(
      () => {
        this._timer = undefined;
        // On a hidden page, `_dueAt` stays in the past, so the visibility change reads.
        if (this.isConnected && document.visibilityState === "visible") {
          void this._run(() => this._refresh());
        }
      },
      Math.max(this._dueAt - Date.now(), 0),
    );
  }

  private _listen(): void {
    const connection = this.hass?.connection;
    if (!this.isConnected || !connection || connection === this._connection) {
      return;
    }
    this._connection?.removeEventListener("ready", this._onReady);
    connection.addEventListener("ready", this._onReady);
    this._connection = connection;
  }

  // A renewal or a reconnect can replace `_day` or `_queue` while the editor is
  // open, so the open visit's image paths and recording renew with it instead
  // of staying on paths that are about to expire.
  private _refreshEditing(visits: Visit[]): void {
    if (!this._editing) {
      return;
    }
    const updated = visits.find((visit) => visit.event_id === this._editing!.event_id);
    if (updated) {
      this._editing = updated;
    }
  }

  private _isQueue(): boolean {
    return this._cat !== undefined && this._cat === this._cats?.unknown.device_id;
  }

  private _fixed(): boolean {
    return this._config?.hide_cat_picker === true;
  }

  // A card without cats has not started yet, for example while the entry waits
  // to set up. The state change of a SiiPet entity when the entry loads starts it.
  private _showsLatest(): boolean {
    if (!this._cats) {
      return true;
    }
    return this._isQueue() || (this._date !== undefined && this._date === this._cats.today);
  }

  private _firstCat(cats: CatsResult): string | undefined {
    return cats.cats[0]?.device_id;
  }

  // The Unknown cat owns every visit without a known cat, so it is the fallback
  // when the account has no named cat yet, not just when it is asked for by name.
  private _fallbackCat(cats: CatsResult): string | undefined {
    return this._firstCat(cats) ?? (cats.unknown.waiting > 0 ? cats.unknown.device_id : undefined);
  }

  /** Whether the card is fixed on a cat that the account does not have. */
  private _catGone(cats: CatsResult): boolean {
    const wanted = this._config?.cat;
    return (
      this._fixed() &&
      wanted !== undefined &&
      wanted !== cats.unknown.device_id &&
      !cats.cats.some((cat) => cat.device_id === wanted)
    );
  }

  private _startCat(cats: CatsResult): string | undefined {
    const wanted = this._config?.cat;
    if (wanted === cats.unknown.device_id && (this._fixed() || cats.unknown.waiting > 0)) {
      return wanted;
    }
    // A fixed card stays on its cat, so it shows no other cat in its place.
    if (this._catGone(cats)) {
      return undefined;
    }
    return cats.cats.find((cat) => cat.device_id === wanted)?.device_id ?? this._fallbackCat(cats);
  }

  private async _start(): Promise<void> {
    if (!(await this._loadParts())) {
      return;
    }
    await this._readCatsAndInit();
    await this._followLink();
  }

  /** Load the tile parts, and return whether they are all there. A failed
   * helper load shows its message, and the next refresh tries again. */
  private async _loadParts(): Promise<boolean> {
    if (this._partsLoaded) {
      return true;
    }
    let missing: string[];
    try {
      missing = await loadTileParts();
    } catch (err) {
      this._error = { error: err };
      return false;
    }
    if (missing.length > 0) {
      this._missing = missing;
      return false;
    }
    this._partsLoaded = true;
    return true;
  }

  /** Read the cats and pick the initial cat and day, as a fresh start does. */
  private async _readCatsAndInit(): Promise<void> {
    const cats = await this._readCats();
    if (cats) {
      await this._init(cats);
    }
  }

  /** Select the configured cat, or the fallback, on the server's day and read it. */
  private async _init(cats: CatsResult): Promise<void> {
    this._date = cats.today;
    this._month = monthOf(cats.today);
    this._cat = this._startCat(cats);
    await this._loadSelection();
  }

  private async _readCats(): Promise<CatsResult | undefined> {
    this._changesSeen = changeCount;
    try {
      this._cats = await fetchCats(this.hass!);
      this._catsRead = Date.now();
      return this._cats;
    } catch (err) {
      this._error = { error: err };
      this._scheduleRetry(err);
      return undefined;
    }
  }

  /** Read the day or the queue, and the calendar month of the day. */
  private async _loadSelection(): Promise<void> {
    if (this._cat === undefined || this._date === undefined) {
      return;
    }
    if (this._isQueue()) {
      await this._loadQueue();
      return;
    }
    await Promise.all([this._loadDay(), this._loadCalendar(monthOf(this._date))]);
  }

  // Each read checks that the card still shows what it asked for, and that no
  // newer read of its kind started, so a slow answer does not replace a newer one.
  private async _loadDay(): Promise<void> {
    const cat = this._cat!;
    const date = this._date!;
    const seq = ++this._daySeq;
    const current = () => seq === this._daySeq && cat === this._cat && date === this._date;
    try {
      const day = await fetchDay(this.hass!, date, cat);
      if (current()) {
        this._day = day;
        this._dataRead = Date.now();
        this._scheduleRenew();
        this._refreshEditing(day.visits);
      }
    } catch (err) {
      if (current()) {
        this._error = { error: err };
        this._scheduleRetry(err);
      }
    }
  }

  private async _loadQueue(): Promise<void> {
    const cat = this._cat;
    const seq = ++this._queueSeq;
    const current = () => seq === this._queueSeq && cat === this._cat;
    try {
      const queue = await fetchQueue(this.hass!);
      if (!current()) {
        return;
      }
      this._dataRead = Date.now();
      this._scheduleRenew();
      // The queue and the waiting count on the cat strip name the same visits,
      // so a read that finds fewer or more of them updates the strip too.
      if (this._cats) {
        this._cats = {
          ...this._cats,
          unknown: { ...this._cats.unknown, waiting: queue.visits.length },
        };
      }
      if (queue.visits.length === 0 && !this._fixed()) {
        const first = this._cats && this._firstCat(this._cats);
        if (first !== undefined) {
          this._selectCat(first);
          return;
        }
      }
      this._queue = queue;
      this._refreshEditing(queue.visits);
    } catch (err) {
      if (current()) {
        this._error = { error: err };
        this._scheduleRetry(err);
      }
    }
  }

  private async _loadCalendar(month: string): Promise<void> {
    const cat = this._cat!;
    const seq = (this._calendarSeq.get(month) ?? 0) + 1;
    this._calendarSeq.set(month, seq);
    const current = () => seq === this._calendarSeq.get(month) && cat === this._cat;
    try {
      const calendar = await fetchCalendar(this.hass!, month, cat);
      if (current()) {
        this._calendars = { ...this._calendars, [month]: calendar };
        this._first = calendar.first;
      }
    } catch (err) {
      if (current()) {
        this._error = { error: err };
      }
    }
  }

  /** Read the cats and the shown data again, then follow a new link. */
  private async _refresh(): Promise<void> {
    await this._readAgain();
    await this._followLink();
  }

  /** Read the cats and the shown data again. A card on today moves on to a new day. */
  private async _readAgain(): Promise<void> {
    this._error = undefined;
    // The reads below arm the next renewal or retry. A read that shows nothing,
    // such as the cats of an account without cats, leaves none due.
    this._dueAt = undefined;
    this._clearTimer();
    if (this._missing?.length) {
      return;
    }
    if (!this._cats) {
      // The first read never finished (for example Home Assistant was still starting),
      // so pick up where a fresh start would: the tile parts, the cats, then the
      // initial selection.
      if (await this._loadParts()) {
        await this._readCatsAndInit();
      }
      return;
    }
    // Keep the date shown before the read, so a day the user picks while this read
    // is in flight is not undone by a stale comparison once the read comes back.
    const shownDate = this._date;
    const followToday = shownDate === this._cats.today;
    const cats = await this._readCats();
    if (!cats) {
      return;
    }
    if (followToday && this._date === shownDate && shownDate !== cats.today) {
      this._date = cats.today;
      this._month = monthOf(cats.today);
    }
    if (this._cat === undefined) {
      // A config change during the cats read cleared the cat, or the account had
      // no cat before. The config decides the cat here as it does on a start.
      await this._init(cats);
      return;
    }
    if (this._isQueue() && cats.unknown.waiting === 0 && !this._fixed()) {
      const next = this._firstCat(cats);
      if (next !== undefined) {
        this._selectCat(next);
        return;
      }
    }
    await this._loadSelection();
  }

  /** Return the linked event id, unless this card read it and the address still holds it. */
  private _newLink(): string | undefined {
    const eventId = linkedEventId();
    if (eventId === undefined) {
      // The link left the address, so the same link after this is a new one.
      this._linkEvent = undefined;
    }
    return eventId !== this._linkEvent ? eventId : undefined;
  }

  private _editorElement(): Element | null {
    return this.renderRoot.querySelector("siipet-visit-editor");
  }

  private _onEditorBusy(ev: CustomEvent<BusyDetail>): void {
    if (ev.detail.busy) {
      this._busyEditor = ev.target ?? undefined;
    } else if (this._busyEditor === ev.target) {
      this._busyEditor = undefined;
    }
  }

  /** Whether a link waits for the open editor: it is busy, or it was busy when a
   * link came and is still open. A link that waits stays in the address, unread. */
  private _linkWaits(): boolean {
    const editor = this._editing ? this._editorElement() : null;
    if (editor === null) {
      return false;
    }
    if (editor === this._busyEditor) {
      this._holdingEditor = editor;
      return true;
    }
    return editor === this._holdingEditor;
  }

  /** Read the linked visit, and open it when this card owns it. Runs inside `_run`. */
  private async _followLink(): Promise<void> {
    const eventId = this._newLink();
    if (eventId === undefined || !this._cats || this._linkWaits()) {
      return;
    }
    // A fixed card without its cat opens no visit, so it leaves the link unread.
    if (this._fixed() && this._cat === undefined) {
      return;
    }
    this._linkEvent = eventId;
    let result: VisitResult;
    try {
      result = await fetchVisit(this.hass!, eventId);
    } catch (err) {
      this._linkFailed(eventId, err);
      return;
    }
    // Home Assistant fires `location-changed` before it swaps the view, so the
    // card of the view that the user leaves can get the answer after it is
    // detached. The link then stays for the card of the new view, and a
    // re-attach reads it again.
    if (!this.isConnected) {
      this._linkEvent = undefined;
      return;
    }
    // A config change clears the cats, and a navigation can replace the link,
    // while the read runs.
    if (!this._cats || linkedEventId() !== eventId) {
      return;
    }
    // A save or a delete that started during the read keeps its editor.
    if (this._linkWaits()) {
      this._linkEvent = undefined;
      return;
    }
    const cat = this._linkedCat(this._cats, result.visit);
    if (cat === undefined) {
      return;
    }
    removeLink();
    this._linkEvent = undefined;
    this._openLinked(cat, result);
  }

  /** Show the error of a failed link read, and decide whether the next run reads the link again. */
  private _linkFailed(eventId: string, err: unknown): void {
    // Another read of a visit outside the window gives the same error, so that
    // link stays read and its error shows once. Other failures can pass, for
    // example while Home Assistant starts. A detached card leaves the link for
    // the card of the shown view.
    if (!this.isConnected || !isOutsideWindow(err)) {
      this._linkEvent = undefined;
    }
    if (linkedEventId() === eventId) {
      this._error = { error: err };
    }
  }

  /** Return the cat that shows a linked visit in this card: the shown cat when it
   * owns the visit, else the first owner. A fixed card owns only visits of its cat. */
  private _linkedCat(cats: CatsResult, visit: Visit): string | undefined {
    const owners =
      visit.cats.length > 0
        ? visit.cats.flatMap((cat) => (cat.device_id !== null ? [cat.device_id] : []))
        : [cats.unknown.device_id];
    if (this._cat !== undefined && owners.includes(this._cat)) {
      return this._cat;
    }
    return this._fixed() ? undefined : owners[0];
  }

  /** Select the cat and the day of a linked visit, then open it in the editor. */
  private _openLinked(cat: string, { date, visit }: VisitResult): void {
    const queue = cat === this._cats?.unknown.device_id;
    if (cat !== this._cat) {
      if (!queue) {
        this._date = date;
        this._month = monthOf(date);
      }
      this._selectCat(cat);
    } else if (!queue && date !== this._date) {
      this._goToDay(date);
    }
    this._editing = visit;
  }

  private _selectCat(cat: string): void {
    if (cat === this._cat) {
      return;
    }
    this._cat = cat;
    this._calendars = {};
    this._first = undefined;
    this._calendarOpen = false;
    this._day = undefined;
    this._queue = undefined;
    this._error = undefined;
    void this._loadSelection();
  }

  private _goToDay(date: string): void {
    this._date = date;
    this._month = monthOf(date);
    this._calendarOpen = false;
    this._day = undefined;
    this._error = undefined;
    void this._loadDay();
    if (!(this._month in this._calendars)) {
      void this._loadCalendar(this._month);
    }
  }

  private _shiftMonth(delta: number): void {
    this._month = shiftMonth(this._month!, delta);
    this._error = undefined;
    void this._loadCalendar(this._month);
  }

  /** Return to the day view for the visit this close is about. After an edit, read
   * again either way: a save or a delete from an editor that is no longer the one
   * shown still changed the server's data. The other cards on the page read again
   * too. Close and scroll only for the editor on screen and its visit, so an old
   * editor, also one of the same visit, does not drop the view the card has moved on to. */
  private async _closeEditor(ev: CustomEvent<CloseDetail>): Promise<void> {
    const { changed, eventId } = ev.detail;
    const closes = ev.target === this._editorElement() && this._editing?.event_id === eventId;
    if (closes) {
      this._editing = undefined;
      this._holdingEditor = undefined;
    }
    if (changed) {
      changeCount += 1;
      const detail: ChangedDetail = { source: this };
      window.dispatchEvent(new CustomEvent<ChangedDetail>(CHANGED_EVENT, { detail }));
      // The refresh reads a link that waited for this editor at its end.
      await this._run(() => this._refresh());
    } else if (closes) {
      this._onLocationChange();
    }
    if (!closes) {
      return;
    }
    await this.updateComplete;
    const rows = this.shadowRoot?.querySelectorAll<HTMLElement>(".visit") ?? [];
    [...rows].find((row) => row.dataset.event === eventId)?.scrollIntoView({ block: "nearest" });
  }

  private _toggleCalendar(): void {
    this._month = monthOf(this._date!);
    this._calendarOpen = !this._calendarOpen;
  }

  protected render(): TemplateResult {
    if (this._missing?.length) {
      return html`
        <ha-card>
          <div class="message alone missing">
            ${this._l10n.text.missingParts(this._missing.join(", "))}
          </div>
        </ha-card>
      `;
    }
    const cats = this._cats;
    const selected = this._cat;
    const mainShown = cats !== undefined && selected !== undefined;
    return html`
      <ha-card style="--tile-color: var(--state-icon-color)">
        ${cats && !cats.available ? this._renderNotice(cats) : nothing}
        ${cats && selected === undefined ? this._renderNoCat(cats) : nothing}
        ${cats && selected !== undefined ? this._renderMain(cats, selected) : nothing}
        ${
          !mainShown && this._error
            ? html`<div class="error">${errorText(this._error.error, this._l10n)}</div>`
            : nothing
        }
      </ha-card>
    `;
  }

  private _renderNoCat(cats: CatsResult): TemplateResult {
    const message = this._catGone(cats) ? this._l10n.text.catGone : this._l10n.text.noCats;
    return html`<div class="message alone">${message}</div>`;
  }

  private _renderNotice(cats: CatsResult): TemplateResult {
    const day = dayLabel(cats.updated_at.slice(0, 10), this._l10n.locale);
    return html`
      <div class="notice">
        ${this._l10n.text.notUpdating(`${day} ${timeLabel(cats.updated_at, this._l10n.locale)}`)}
      </div>
    `;
  }

  private _renderMain(cats: CatsResult, selected: string): TemplateResult {
    if (this._editing) {
      // Another visit gets a new editor, so a pending save or delete of the
      // last visit does not act on the new one. The old editor still sends
      // its close, which `_closeEditor` tells apart by its element.
      return html`${keyed(
        this._editing.event_id,
        html`
          <siipet-visit-editor
            .hass=${this.hass}
            .visit=${this._editing}
            .cats=${cats.cats}
            .l10n=${this._l10n}
            @siipet-busy=${(ev: CustomEvent<BusyDetail>) => this._onEditorBusy(ev)}
            @siipet-close=${(ev: CustomEvent<CloseDetail>) => this._closeEditor(ev)}
          ></siipet-visit-editor>
        `,
      )}`;
    }
    return html`
      ${this._renderView(cats, selected)}
      ${
        this._error
          ? html`<div class="error">${errorText(this._error.error, this._l10n)}</div>`
          : nothing
      }
      ${this._renderVisits()}
    `;
  }

  private _renderView(cats: CatsResult, selected: string): TemplateResult {
    const strip = renderCatStrip(
      cats,
      selected,
      this._fixed(),
      (cat) => this._selectCat(cat),
      this._l10n,
    );
    if (this._isQueue()) {
      return renderHeader({
        icon: "mdi:help",
        primary: this._l10n.text.unknown,
        secondary: queueSummaryText(this._queue?.visits.length ?? cats.unknown.waiting, this._l10n),
        features: html`${strip}`,
      });
    }
    const cat = cats.cats.find((entry) => entry.device_id === selected);
    const date = this._date!;
    const month = this._month ?? monthOf(date);
    const first = this._first;
    const lastMonth = monthOf(cats.today);
    const dateBar = renderDateBar({
      date,
      canGoBack: first === undefined || shiftDay(date, -1) >= first,
      canGoForward: date < cats.today,
      marked: this._calendars[monthOf(date)]?.days[date]?.marked ?? false,
      l10n: this._l10n,
      onShift: (delta) => this._goToDay(shiftDay(date, delta)),
      onToggle: () => this._toggleCalendar(),
    });
    const calendar = this._calendarOpen
      ? renderCalendar({
          month,
          calendar: this._calendars[month],
          selected: date,
          canGoBack: month > shiftMonth(lastMonth, -CALENDAR_MONTHS),
          canGoForward: month < lastMonth,
          l10n: this._l10n,
          onShiftMonth: (delta) => this._shiftMonth(delta),
          onOpenDay: (day) => this._goToDay(day),
        })
      : nothing;
    return renderHeader({
      imageUrl: cat?.avatar ?? undefined,
      icon: cat?.avatar ? undefined : "mdi:cat",
      primary: cat?.name ?? "",
      secondary: this._day
        ? daySummaryText(date, this._day.summary, this._l10n)
        : dayLabel(date, this._l10n.locale),
      features: html`${dateBar} ${calendar} ${strip}`,
    });
  }

  private _renderVisits() {
    const open = (visit: Visit) => {
      this._editing = visit;
    };
    return this._isQueue()
      ? renderTimeline(this._queue?.visits, true, open, this._l10n)
      : renderTimeline(this._day?.visits, false, open, this._l10n);
  }
}

if (!customElements.get("siipet-visits-card")) {
  customElements.define("siipet-visits-card", SiiPetVisitsCard);
}

interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview: boolean;
}

const cardWindow = window as { customCards?: CustomCardEntry[] };
cardWindow.customCards = cardWindow.customCards ?? [];
if (!cardWindow.customCards.some((entry) => entry.type === "siipet-visits-card")) {
  // Getters, so the picker shows the language of the page each time it opens.
  cardWindow.customCards.push({
    type: "siipet-visits-card",
    get name() {
      return cardText(pageLanguage()).pickerName;
    },
    get description() {
      return cardText(pageLanguage()).pickerDescription;
    },
    preview: true,
  });
}
