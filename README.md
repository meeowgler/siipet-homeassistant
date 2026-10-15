# siipet-homeassistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/pszypowicz/siipet-homeassistant)](https://github.com/pszypowicz/siipet-homeassistant/releases)
[![Validate](https://github.com/pszypowicz/siipet-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/pszypowicz/siipet-homeassistant/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/pszypowicz/siipet-homeassistant)](LICENSE)

A Home Assistant custom integration for [SiiPet](https://siipet.com) LitterLens litter box cameras.

## Status

The integration is in early development. It signs in to your SiiPet account and polls the SiiPet cloud every 5 minutes.
It gives statistics and visit events for each cat, the battery and the device state of each camera, and it shows the cloud recordings in the media browser.
Its actions list, edit, and delete visits. A dashboard card shows the visits of each day.

## Requirements

- Home Assistant 2026.9.0 or later.
- A SiiPet account with at least one camera.

## Install

Option 1: Install with HACS. HACS then shows each new release as an update.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pszypowicz&repository=siipet-homeassistant&category=integration)

1. Select the button above. If HACS asks to add the repository, choose **Add**.
2. Choose **Download** and download the latest version.
3. Restart Home Assistant.

Without the button, open **HACS**, open the three-dot menu, and choose **Custom repositories**.
Add `https://github.com/pszypowicz/siipet-homeassistant` as an **Integration**, then find **SiiPet** in HACS.

Option 2: Copy the files by hand.

1. Copy `custom_components/siipet/` from this repo into your Home Assistant config, so that the path is `/config/custom_components/siipet/`.
2. Restart Home Assistant.

Then, for either option:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=siipet)

1. Select the button above, or go to **Settings > Devices & Services > Add Integration** and search for **SiiPet**.
2. Enter the email address of your SiiPet account.
3. If the account has a password, enter it too. Home Assistant signs in, and SiiPet sends no code.
4. Otherwise leave the password empty, and enter the code that SiiPet sends to that address.
   To set a password for the account, also enter a new password on this step.

The session renews automatically.

To sign in again at any other time, open the SiiPet entry in **Settings > Devices & Services** and choose **Reconfigure**.
Use the same SiiPet account. The devices, entities, and dashboards stay as they are.

SiiPet limits how many sign-in codes it sends per day. If it refuses, try again the next day.

### Sign in with a password

A sign-in to the same account somewhere else, such as the phone app, can end the session of Home Assistant.
After an email-code sign-in, Home Assistant then asks for a new code.
SiiPet sends only a few codes per day, so a few ended sessions on one day can leave Home Assistant signed out until the next day.

With a password, Home Assistant signs in again by itself when SiiPet ends the session.
It asks you only when SiiPet rejects the password.
After it signs in again, it waits 15 minutes before the next time,
so that it does not keep ending the session of another device that uses the same account.
For the same reason, use an account that only Home Assistant uses, such as an invited account.

The SiiPet app has no setting for a password.
To set one, leave the password empty, and enter a new password together with the code.
SiiPet does not send the password to you, so keep it somewhere safe.
Home Assistant stores the password in the SiiPet entry. The diagnostics do not include it.

## Devices and entities

### Cats

Each cat is a device. A virtual device named **Unknown cat** collects visits that the camera did not recognize.

| Entity                                   | Description                                                                                                |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Visits today                             | Pee and poop visits today.                                                                                 |
| Pee today, Poop today, Lingering today   | Visits of each type today.                                                                                 |
| Abnormal visits today                    | Pee and poop visits that SiiPet marks as abnormal.                                                         |
| Average visit duration today             | The mean duration of today's pee and poop visits.                                                          |
| Baseline visits, Baseline visit duration | The values that SiiPet expects for the cat from midnight until now, from what it learned.                  |
| Baseline progress                        | How much of the learning period is complete.                                                               |
| Last visit                               | The start of the newest visit. Its attributes show the type, duration, camera, and abnormal reasons.       |
| Visit                                    | An event entity. It fires once for each new visit, with the type `pee`, `poop`, `lingering`, or `unknown`. |
| Unassigned visits                        | Unknown cat only. The number of unrecognized visits in the last 7 days.                                    |

The Unknown cat has no baseline entities.

### Cameras

| Entity               | Description                                                   |
| -------------------- | ------------------------------------------------------------- |
| Subscription expires | Diagnostic. The end of the camera subscription.               |
| Battery              | The battery charge in percent, rounded like the SiiPet app.   |
| Charging             | On while the camera reports that it charges.                  |
| Privacy mode         | On while privacy mode is on.                                  |
| Online               | Diagnostic. On while the camera reports that it is online.    |
| Last report          | Diagnostic. The time of the newest value in the device state. |
| Wi-Fi signal         | Diagnostic, disabled by default. The Wi-Fi signal in dBm.     |
| Cloud storage        | Diagnostic. On while cloud storage is on for the camera.      |
| Fill light           | Diagnostic. Low, medium, or high.                             |
| Motion sensitivity   | Diagnostic. Medium or high.                                   |
| Firmware update mode | Diagnostic. Automatic or manual.                              |

The camera device shows the firmware version.

The integration keeps one connection to the SiiPet cloud open for the device state.
The values update when a camera reports a change, and at least every 5 minutes.
If the connection stays down for 15 minutes, the device state entities become unavailable.

- Charging off does not prove that the cable is unplugged. The camera reports only whether it charges.
- A camera can stop reporting while Online stays on. Last report shows how old the data is.
- The device state works for an invited account too.

### Removed cats and cameras

When a cat or a camera leaves your SiiPet account, its entities become unavailable.
To remove it, open its device page in Home Assistant and choose **Delete**.
Home Assistant does not let you delete a cat or a camera that is still in the account.
The delete works only while the SiiPet integration is loaded.

## Recordings

Open **Media** in the Home Assistant sidebar and choose **SiiPet**.
The list shows the last 30 days. Each day lists its visits, newest first, with the time, the cats, the type, and the duration.

The recordings use H.265 video. Safari and the Home Assistant app on macOS and iOS can play them.
Other browsers can fail. The integration does not convert video.

A visit marked **(on camera only)** has no cloud recording, so it cannot play.

Home Assistant serves the thumbnails for you.
A recording plays from the [local media copy](#local-media-copy) when the copy has it.
Otherwise it plays directly from the SiiPet cloud storage, through a link that expires after one hour.

## Local media copy

Home Assistant keeps a copy of the recordings and images of the last 7 days.
The card and the media browser play a recording from this copy.
A recording that is not in the copy plays from the SiiPet cloud.

To change the number of days, open the SiiPet entry in **Settings > Devices & Services** and choose **Configure**.
Set a number from 0 to 30. 0 turns the copy off and deletes it.

- SiiPet copies a new visit after the poll that finds it, so within about 5 minutes after the upload.
- The copy is in the folder `.siipet` of the Home Assistant media folder, for example `/media/.siipet`. The media browser does not list this folder.
- A recording takes about 30 MB on average. At 8 to 9 visits a day, 7 days take about 1.8 GB, and 30 days take about 7.7 GB.
- A backup includes the copy only if the backup includes the media folder.
- If less than 1 GB stays free on the disk, the copy pauses, and a repair shows in **Settings > Repairs**.
- A deleted visit loses its local files too. When you remove the integration, Home Assistant deletes the folder.

## Dashboard card

The integration adds the **SiiPet visits** card to your dashboards. You do not add a resource.

1. Edit a dashboard and choose **Add card**.
2. Search for **SiiPet visits** and add it.
3. Optional: pick a cat. Without a cat, the card starts with your first cat.

```yaml
type: custom:siipet-visits-card
cat: <device id of a cat> # optional
hide_cat_picker: true # optional, keeps the card on one cat
```

The card shows the visits of one cat on one day, newest first:

- The header shows the cat and the visit counts of the day.
- Tap the date to open the month calendar. A red dot marks a day with an abnormal visit or a warning.
  Only today and the 30 days before it open.
- The cat strip changes the cat. **Unknown** shows while visits of the last 7 days have no cat.
- If you have more than one camera, each visit names the area of its camera.
  If the camera device has no area, the visit shows the device name.
- Tap a visit to open it. You can play the recording, change the cats, the type, and the memo, and save.
- Administrators can also delete a visit. Tap **Delete** and confirm in the dialog that follows.

The card uses the tile parts of the Home Assistant frontend, so it looks like the tile cards around it.
If a Home Assistant update removes one of these parts, the card names the missing part.

The recordings use H.265 video, so the limits in [Recordings](#recordings) apply to the card too.

The integration also adds the icon `siipet:logo`, for example for a dashboard view.

### One card per cat

To show each cat in its own card, set `cat` and `hide_cat_picker: true` on each card.
The card then shows no cat picker and stays on its cat.

```yaml
type: custom:siipet-visits-card
cat: <device id of a cat>
hide_cat_picker: true
```

A card fixed on the Unknown cat shows the visits that have no cat, also when none are waiting.
If the account no longer has the cat of a fixed card, the card says so and shows no other cat.

### Open a visit from a notification

A dashboard link with `?siipet_visit=<event id>` opens that visit in the card.
A card fixed on a cat opens only the visits of its cat.
A card with the cat picker changes to the cat and the day of the visit.
The card finds the visits of the last 7 days.
While you save or delete a visit, the link waits, so you see the result.
If the save or the delete fails, the linked visit opens when you go back.

This automation sends a notification after each visit of one cat. A tap opens the visit.
Replace the entity, the notify action, and the dashboard path with your own.
The Home Assistant app on iOS reads `url`, and the app on Android reads `clickAction`.

```yaml
triggers:
  - trigger: state
    entity_id: event.luna_visit
    not_from: unavailable
    not_to: unavailable
actions:
  - action: notify.mobile_app_phone
    data:
      message: "Luna used the litter box: {{ trigger.to_state.attributes.event_type }}."
      data:
        url: "/dashboard-cats/cats?siipet_visit={{ trigger.to_state.attributes.event_id }}"
        clickAction: "/dashboard-cats/cats?siipet_visit={{ trigger.to_state.attributes.event_id }}"
```

## Languages

The integration and the card are in English and Polish.

- The sign-in, the options, the repairs, the actions, the entity states, and the card follow the language of each Home Assistant user.
- Entity names follow the server language in **Settings > System > General**. After you change it, restart Home Assistant. The entity IDs stay the same, and new entities on a Polish server get entity IDs from the Polish names.
- The card shows dates and times with the settings of your user profile, for example the 12-hour clock and the first day of the week.
- SiiPet sends the abnormal reasons in English. The media browser titles and the name of the Unknown cat device are also in English.

## Actions

Use the actions in scripts and automations, or in **Developer tools > Actions**.

### List visits

`siipet.list_visits` returns the visits of up to 7 days, newest first.

| Field  | Description                                                                         |
| ------ | ----------------------------------------------------------------------------------- |
| `date` | The last day in the list. The default is today. It must be one of the last 31 days. |
| `days` | The number of days, from 1 to 7. The default is 1.                                  |
| `cat`  | A cat device. The list then shows only the visits of that cat.                      |

The response has two lists.
`cats` gives the name and the device id of each cat, and of the Unknown cat.
`visits` gives the `event_id`, `start`, `duration` in seconds, `type`, `cats`, `camera`, `note`, `abnormal`, `abnormal_reasons`, `has_video`, and `has_stool_image` of each visit.

### Update visit

`siipet.update_visit` changes a visit in the SiiPet cloud. The SiiPet app shows the change too.

| Field      | Description                                                                               |
| ---------- | ----------------------------------------------------------------------------------------- |
| `event_id` | Required. The `event_id` from the list response, or from the attributes of a Visit event. |
| `cats`     | The cats that used the box, at least one. The Unknown cat is not valid here.              |
| `type`     | `pee`, `poop`, or `lingering`.                                                            |
| `note`     | The memo, up to 200 characters. An empty memo clears it.                                  |

Give at least one of `cats`, `type`, or `note`.
If the visit has the type `unknown`, give a `type` together with the cats.
A pee visit that you change to poop has no stool shape or color.

The integration reads the visit again after the change. If SiiPet did not apply the change, the action fails.
If an update fails partway, the error names the type to use. Check the visit, then call the action again with that type.
An edit does not fire a Visit event.

### Delete visit

`siipet.delete_visit` deletes the visit with the given `event_id`. Only an administrator can use it.

You cannot undo a delete.

## Example: notify on an unrecognized visit

A tap on the notification opens the visit in a card fixed on the Unknown cat, where you can pick the cat and the type.

```yaml
triggers:
  - trigger: state
    entity_id: event.unknown_cat_visit
    not_from: unavailable
    not_to: unavailable
actions:
  - action: notify.mobile_app_phone
    data:
      message: "A visit has no cat. Tap to assign it."
      data:
        url: "/dashboard-cats/unknown?siipet_visit={{ trigger.to_state.attributes.event_id }}"
        clickAction: "/dashboard-cats/unknown?siipet_visit={{ trigger.to_state.attributes.event_id }}"
```

## Example: assign unrecognized visits to your cat

If you have one cat, this automation gives it each visit that the camera did not recognize.
It skips visits of the type `unknown`, because those need a type too.
Replace `sensor.luna_visits_today` with a sensor of your cat.

```yaml
mode: queued
triggers:
  - trigger: state
    entity_id: event.unknown_cat_visit
    not_from: unavailable
    not_to: unavailable
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.event_type != 'unknown' }}"
actions:
  - action: siipet.update_visit
    data:
      event_id: "{{ trigger.to_state.attributes.event_id }}"
      cats:
        - "{{ device_id('sensor.luna_visits_today') }}"
```

## License

MIT.

## Disclaimer

This project is not affiliated with SiiPet, and SiiPet does not endorse or support it.
SiiPet, LitterLens, and the other product names in this README belong to their owners.

The integration uses the cloud API of the SiiPet app. SiiPet does not publish this API, and it can change the API at any time.
A change can stop the integration without warning.

I maintain this integration on a best-effort basis. I give no warranty and no promise of support or fixes.
You use it at your own risk. I am not responsible for lost or changed data, for problems with your SiiPet account, or for other damage.
The edit and delete actions change your data in the SiiPet cloud, and you cannot undo a delete.

The visit data and the abnormal marks come from SiiPet. They do not replace the advice of a veterinarian.
If you are concerned about the health of your cat, ask a veterinarian.

The [MIT license](LICENSE) gives the full terms.
