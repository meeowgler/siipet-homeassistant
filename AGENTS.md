# Instructions for coding agents

This file tells coding agents how to work in this repo. Humans can read it too.

## Project

This repo is a Home Assistant custom integration for SiiPet LitterLens litter box cameras.
It uses the SiiPet cloud API. HACS installs it from `custom_components/siipet/`.
The minimum Home Assistant version is 2026.9.0.

## Layout

```
custom_components/siipet/
  api/                 SiiPet cloud client. No Home Assistant imports.
    client.py          SiiPetClient: headers, envelope, one method per endpoint
    auth.py            challenge encryption, token payload, renewal rule
    challenge_key.py   AES key for the sign-in challenge
    models.py          Cat, Camera, CameraShadows, Visit, VisitType, DayVisits, DaySummary, CalendarDay, AbnormalLabels, MediaCredentials, IotCredentials, DeviceState
    edits.py           plan_edit: the annotate and memo calls for one visit edit
    errors.py          SiiPetError and its subclasses
    s3.py              SigV4 presigned GET URLs, credential cache
    sigv4.py           SigV4 presigned URLs for S3 and the AWS IoT WebSocket
    mqtt.py            MQTT 3.1.1 packets and MqttSession on an aiohttp WebSocket
    lrtm.py            Centrifugo JSON protocol and LrtmControl on an aiohttp WebSocket, the control lane
    shadow_link.py     ShadowLink: one AWS IoT connection for the device shadows
  __init__.py          setup of the image and recording views, the actions, the card commands, and the card, entry setup that starts the device state and the local media copy, unload, entry removal that deletes the copy, device removal
  config_flow.py       email and code steps, reauth and reconfigure, options step for the days of local media
  const.py             constants: config keys, Unknown cat id, intervals
  coordinator.py       SiiPetCoordinator, SiiPetData, SiiPetRuntime
  device_state.py      SiiPetDeviceCoordinator: the device state that the shadow link pushes
  entity.py            cat and camera entity bases
  sensor.py  binary_sensor.py  event.py  select.py  switch.py  diagnostics.py
  commands.py          device command payloads (the fillLight payload)
  services.py          actions: list_visits, update_visit, delete_visit
  services.yaml        action fields and selectors
  visit_data.py        visit, cat, and camera label helpers, the date check, and the day read for the actions and the card commands
  calendar_data.py     SiiPetCalendar: calendar months per cat, kept for 5 minutes
  websocket_api.py     websocket commands for the dashboard card: cats, calendar, day, queue, visit
  media.py             SiiPetMedia: media keys, recording URLs, image fetch, local files first
  media_store.py       MediaStore: the local media copy on disk, its index, and verified writes
  media_mirror.py      SiiPetMirror: downloads, backfill, and cleanup of the local media copy
  media_source.py      media browser: the last 30 days and their visits
  views.py             authenticated views: images, and recordings from the local media copy
  card.py              serving of the card file, with a content version in its URL
  frontend/            siipet-visits-card.js, the card bundle built from frontend/ at the repo root
  translations/        en.json and pl.json, with the same keys and placeholders
  icons.json           icons of the device state entities
  brand/               icon.png and icon@2x.png, loaded by Home Assistant 2026.3 and later
tests/
  api/                 client, MQTT, and shadow link tests, with the HTTP mocker and a fake broker
  fixtures/            JSON responses with fake values only
docs/api.md            SiiPet cloud API reference
frontend/              source of the dashboard card: TypeScript, Lit, esbuild, vitest
  src/                 card element, day view, edit view, API calls, date helpers, card texts in localize.ts
  test/                card tests with happy-dom and stub tile parts
```

## Boundaries

- `api/` imports only `aiohttp`, `cryptography`, and the standard library.
  Home Assistant ships both packages, so `manifest.json` has no requirements.
- Entities read only `coordinator.data`. They never call the client.
- `SiiPetData.cat_ids(visit)` decides which cats own a visit.
  A visit with no known cat belongs to the virtual Unknown cat (`UNKNOWN_CAT_ID`).
- `api/edits.py` has no I/O. `plan_edit` returns the calls, and `services.py` sends them.
- After a delete, `services.py` awaits `mirror.async_forget`, which deletes the local files of the visit.
- After an edit or a delete, `services.py` drops the day from the older-day cache of `SiiPetMedia`
  and its month from the calendar cache, then calls `async_refresh_day`.
- S3 credentials stay inside `api/`. Other modules get signed URLs from `S3Signer`.
- Only `media_store.py` writes to the media folder. It keeps the local copy in `.siipet`,
  and a file name holds an id only if the id matches `[A-Za-z0-9_-]+`.
  The views never build a path from a request. They look up the store index.
- Only `media_source.py` returns a signed S3 URL, and only for a recording that the local copy does not hold.
  Images go through the image view in `views.py`, so their signed URLs stay inside Home Assistant.
- The card commands in `websocket_api.py` sign image view paths for the logged-in user. They return no S3 URL.
- The card reads only through the `siipet/*` websocket commands and `media_source/resolve_media`.
  It writes only through `siipet.update_visit` and `siipet.delete_visit`.
- The card reuses internal tile parts of the Home Assistant frontend. `frontend/src/tile-parts.ts` lists them.
  If a part is missing, the card names it and shows nothing else.
- The card defines its elements with `defineElement` in `frontend/src/define.ts`, after the app defines `home-assistant`.
  The card loads in parallel with the app bundle, and the app does not see an element defined before its registry polyfill.
  On a page without a `home-assistant` element, such as the Cast receiver or a card test, it defines them at once.
- Only `api/shadow_link.py` talks to AWS IoT. It reads the shadows and never writes them.
- The device state entities read `SiiPetDeviceCoordinator.data`, and the camera list of the main coordinator for availability. The shadow link runs as a background task, so setup never waits for it.

## API facts that are easy to get wrong

Read `docs/api.md` before you change `api/`. These points cause most mistakes:

- Every call is a `POST` with a JSON body, also for reads.
- A response is `{"Code", "Msg", "Data"}`. `Code` 0 means success.
- Timestamps and durations are in milliseconds.
- Visit `Type`: 0 unknown, 1 lingering, 2 poop, 3 pee.
- The calendar counts only pee and poop. The visit counts in this integration use the same rule.
- A visit is abnormal when its type is pee or poop, and `FecesAbnormal` has a positive code or `EventAbnormal > 0`.
- `x-timezone` changes how the server groups visits into days.
- In the annotate call, `Result` is a JSON string, and the outer `Type` is the operation, not the visit type.
- Operation 2 of annotate with `GonePotty` true makes the app assume poop. A pee visit needs operation 3 after it.
- The recordings use H.265 video.
- The server checks `x-device-model`. Values that start with `iPhone` or `android-phone` work. With a rejected value, every authenticated call fails with `Code` -2. The `Msg` then says that another device logged in, but that is not the cause.
- Sign-in succeeds even with a rejected model, so the config flow reads the cats once before it creates the entry.
- Email code requests are limited per day (`Code` 10010).
- A setting is changed over Centrifugo at `wss://wss-siipet.linkric.com/connection/websocket`,
  not the REST API. Connect `data` carries the API token and user id. The app publishes
  `{"request": {"header": {"name", "sessionId", "deviceId"}, "payload"}}` to
  `device:joy1:<SN>:app:dev:request`. `config.fillLight` takes the whole fillLight object.
- The command alone applies; the app also writes the shadow `desired` to clear the delta.
  The integration sends the command and does not write the shadow (read-only shadow link).
- `Data.IotCore.Endpoint` of `config/aws/auth` is an `https://` URL. The WebSocket host is its host part.
- AWS IoT signs the WebSocket URL without the session token. The token goes after the signature.

## Translations

- `translations/en.json` and `translations/pl.json` have the same keys and the same `{placeholders}`.
  Change both files together. `tests/test_translations.py` checks it.
- Write every string in full. Home Assistant does not resolve `[%key:...%]` references in a custom integration,
  and hassfest does not catch them.
- An entity whose name is the name of its device class has no `name` in the translations.
  Home Assistant then gives the name in every language.
- Entity names follow the server language. Entity states, the config flow, the options, the actions, the repairs,
  and the errors follow the language of each user.
- The card texts are in `frontend/src/localize.ts`. The Polish table has the type `CardText`,
  so a missing text fails the type check.
- The card formats dates and times with `Intl` and `hass.locale`, with the options of the Home Assistant date formats.
- The card shows an integration error through the `exceptions` translations. It keeps no copy of an error text.

## Privacy

This repo is public. Keep these values out of commits, tests, logs, and entity attributes:

- Tokens, emails, and passwords.
- Camera serial numbers, `UserId`, `GroupId`, `PetId`, and messaging topics.
- S3 credentials, the bucket name, media keys, and signed URLs.
- Shadow names, MQTT topics, the AWS IoT endpoint, `IdentityId`, and the MQTT client identifier.
- The Wi-Fi name and the IP and MAC addresses of a camera. The shadow parser does not read them.
- Raw API captures. Build test fixtures from the documented shapes with fake values.

Entity attributes can contain cat names, camera names, event IDs, types, durations, and abnormal data.
When you add a field that holds a private value, add its key to `TO_REDACT` in `diagnostics.py`.

## Commands

Set up a Python 3.14 environment and install the test requirements:

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
```

Run the tests and the linters:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The card build needs Node.js 24 or later. Run the card checks in `frontend/`:

```bash
cd frontend
npm ci
npm run check
```

`npm run check` runs prettier, the type check, the tests, and the build.
The build writes `custom_components/siipet/frontend/siipet-visits-card.js`.
Commit that file together with the source change, because HACS installs only `custom_components/siipet/`.
CI fails when the committed file differs from a new build.

## Tests

- Write the test first, then the code.
- Integration tests mock `SiiPetClient` with the fixtures in `tests/conftest.py`.
- Client tests mock HTTP with the `aioclient_mock` fixture.
- Card tests define stub tile parts, because the Home Assistant frontend is not available in tests.
- Tests run in UTC with the time frozen at 2026-09-26 12:00.
- The entry fixtures turn the local media copy off. Tests of the copy use `setup_mirror` in `tests/common.py`.
- Integration tests replace `ShadowLink` with `FakeShadowLink` from `tests/common.py`. A test calls its callbacks to push a state or a connection change.
- The MQTT and shadow link tests run a fake broker on localhost. They use `socket_enabled` and replace the frozen clock, because a frozen clock stops asyncio timers.
- Card tests run with an English profile, 24-hour times, and Monday first. A test that needs another locale uses `withLocale` from `frontend/test/helpers.ts`.

## Style

- Use American English.
- Do not use em dashes. Use a single `-`.
- Write docs and UI strings in short, plain sentences.
- Comments explain why. Do not restate the code.

## Live checks

Some API behavior is known only from the vendor app code. `docs/api.md` lists the open points.

- Read calls against a real account are safe.
- Edits and deletes change real data. Use only a visit that the account owner picks for tests.
- Record each result in `docs/api.md`.
