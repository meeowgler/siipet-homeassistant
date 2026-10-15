# SiiPet LitterLens cloud API

Observed from iOS app sessions with app version 2.1.5.
These notes also use static inspection of Android app version 2.1.1.
Static inspection reads program code without running the app.

Examples use placeholders and sample values. Replace them with real values at runtime.

## Transport

- Base URL: `https://api-siipet.linkric.com`
- Every call is a `POST`, even a pure read.
- Request and response bodies are JSON.
- The app does not pin its certificate. A normal HTTPS client works.
- No request signature header is present.

## Response envelope

Every response uses the same shape.

```json
{ "Code": 0, "Msg": "success", "Data": {} }
```

`Code` is 0 on success. Treat any other value as an error and read `Msg`.

## Request headers

```
authorization: Bearer <token>
content-type: application/json
x-app-version: 2.1.5
x-device-identifier: <client UUID, stable per install>
x-device-language: en
x-device-model: <device name>
x-device-os: iOS 27.0
x-timestamp: <milliseconds since epoch>
x-timezone: <IANA timezone>
user-agent: lc01-app/2.1.5
```

The server checks `x-device-model`. Live tests show that it accepts values that
start with `iPhone` or `android-phone`, and rejects the other values that were
tested. The iOS app sends the device name, for example `iPhone 16 Pro`. The
Android app sends `android-phone <model>`. With a rejected value, sign-in still
succeeds, but every authenticated call fails with envelope `Code` -2. The
integration sends `android-phone Home Assistant`.

A bearer token grants access to whoever holds it. The app sends the bearer token
from `Data.Token` in the login response. That response reports `ExpireAt` about
15 days after sign-in. The token itself contains an expiration about 30 days
after sign-in. Android uses `ExpireAt` to schedule renewal before the encoded
token expiration.

`x-timezone` matters. The visit list groups by day, and the server honors the
registered timezone.

## Endpoints

| Endpoint                              | Purpose                                           |
| ------------------------------------- | ------------------------------------------------- |
| `/api/v1/user/account/logout`         | Sign out of the account.                          |
| `/api/v1/user/client/verify`          | Request a client challenge.                       |
| `/api/v1/user/email/send/trustworthy` | Request an email code.                            |
| `/api/v1/user/email/register/login`   | Sign in with an email code.                       |
| `/api/v1/user/token/refresh`          | Renew the session with its existing token.        |
| `/api/v1/user/app/init`               | Session bootstrap.                                |
| `/api/v1/user/account/detail`         | Account profile.                                  |
| `/api/v1/user/account/edit`           | Update the account profile.                       |
| `/api/v1/user/pet/sync`               | List the cats.                                    |
| `/api/v1/user/device/sync`            | List the cameras.                                 |
| `/api/v1/pet/toilet/event`            | List visits for one day, with a per-cat summary.  |
| `/api/v1/device/toilet/event/detail`  | Read one recording and its metadata.              |
| `/api/v1/pet/toilet/event/annotate`   | Edit cat assignment or event classification.      |
| `/api/v1/pet/toilet/data/calendar`    | Per-day history for charts.                       |
| `/api/v1/config/system/config`        | Client configuration. Called often.               |
| `/api/v1/config/aws/auth`             | Temporary credentials for media and device state. |
| `/api/v1/user/firebase/token/bind`    | Push notification registration.                   |

### Email sign-in

The captured sign-in uses an email address and a code from an email.
The app makes three requests in this order. All three responses return HTTP 200
and `Code: 0`.

1. Send `{}` to `POST /api/v1/user/client/verify`.
2. Send the email request below to `POST /api/v1/user/email/send/trustworthy`.
3. Send the email address and received code to `POST /api/v1/user/email/register/login`.

The first response contains `Data.ClientId` and `Data.VerifyCode`.
A challenge is server data that the client must process.
The next request copies `ClientId` and supplies the encrypted `VerifyCode` as
`VerifyCiphertext`. Android constructs this value in
`LoginVerificationViewMode.sendCodeVerify` with `AESUtil.encryptAES`.
The same transformation reproduces the ciphertext in the captured iPhone request.

```json
{
  "Scene": 0,
  "ClientId": "<client id from the challenge response>",
  "VerifyCiphertext": "<processed challenge>",
  "Email": "<email address>"
}
```

AES-GCM encrypts data and detects changes to it. The app uses AES-GCM with a
32-byte key and a 16-byte authentication tag. The key is the SHA-256 digest of
the UTF-8 bytes of a bundled application constant.

A nonce is a random value used once. The app generates a 12-byte nonce for each
encryption. It encrypts the UTF-8 bytes of `VerifyCode` with no additional
authenticated data. It concatenates the nonce, ciphertext, and authentication tag,
then encodes the result with standard base64. Base64 represents bytes as text.

The observed `VerifyCode` contains 32 hexadecimal characters. The app encrypts
those characters directly, without decoding them as hexadecimal bytes.
The observed `VerifyCiphertext` contains 80 base64 characters that decode to
60 bytes. Decryption of the captured iPhone value produces its original challenge.
Encryption with the captured nonce reproduces the complete ciphertext and tag.

The final request has this body. `Code` is a string, so leading zeros remain
intact. The response contains `Data.Token` and `Data.ExpireAt`.

```json
{
  "Code": "<code from the email>",
  "Email": "<email address>"
}
```

The Unix epoch starts at 1970-01-01 00:00:00 UTC.
`ExpireAt` is a timestamp in milliseconds since the Unix epoch.
The captured value is about 15 days after the login response. Subsequent app
requests use the new token successfully.

All three captured iPhone login requests retain the previous token in their
`Authorization` header. A separate test uses a new client identifier and omits
both `Authorization` and `Cookie` for all three sign-in requests. The challenge,
email request, and final login each return HTTP 200 and `Code: 0`.
The final login uses a fresh code from the email and returns a token for the
expected account.

A subsequent `POST /api/v1/user/pet/sync` request uses the new token and returns
HTTP 200 and `Code: 0`. The new session reports an `ExpireAt` about 15 days after
login and an encoded token expiration about 30 days after login. This test
establishes a complete email-code sign-in without a prior session.

The captured login response has no refresh token field.
A refresh token is a credential for obtaining another access token.
Android supports automatic renewal with the existing access token, as described
below.

### Password sign-in

The Android app declares `POST /api/v1/user/email/login` in `AppApi.login`
with a `LoginEmailRequest` of `Email` and `Password`. No screen of app 2.1.1 calls it.

The password is the lowercase SHA-256 hex digest of its UTF-8 bytes,
the same value that the app sends when it sets a password (see below).
The request needs no challenge and no code, so the daily code limit does not apply.

```json
{
  "Email": "<email address>",
  "Password": "<SHA-256 hex digest of the password>"
}
```

The response has the shape of the email-code login: `Data.Token` and `Data.ExpireAt`.
An account without a password and an unknown address both answer `Code` 10003
with `Msg` "not register".

### Set a password

`AccountSetViewModel` in the Android app sets the account password with
`AccountRepository.resetPswEmail`. It sends `POST /api/v1/user/email/reset`
with the emailed code, the address, and the password digest from `SHAUtil.shaEncrypt`,
which is SHA-256 in lowercase hex.

```json
{
  "Code": "<code from the email>",
  "Email": "<email address>",
  "Password": "<SHA-256 hex digest of the password>"
}
```

The code comes from the same email request as the sign-in, with `Scene` 0.
The call returns `Code` 0 and no token. It does not sign in.

### Session renewal

A JWT is a token with signed data. The access token uses this format and contains
`UserId` and `exp` in its decoded payload. The `exp` value uses seconds since the
Unix epoch. This inspection reads the payload without authenticating its signature.

For the captured email login, `exp` is about 30 days after sign-in. It is exactly
15 days later than `Data.ExpireAt` in the same response. These timestamps alone
do not establish the lifetime that the server enforces.

The Android package `com.linkric.siipetapp` contains `UserRepository.checkUserLoginToken`.
The inspected version is 2.1.1.
That method requests renewal when `now_ms + 86_400_000 > ExpireAt`.
It skips renewal while another renewal request is in progress. With the observed
15-day `ExpireAt`, this condition becomes true about 14 days after sign-in.

`AppApi.refreshLoginToken` declares `POST /api/v1/user/token/refresh`.
`UserRepository.refreshToken` sends an empty `BaseRequest`, which corresponds to
the JSON body `{}`. `TokenInterceptor` supplies `Authorization: Bearer <existing token>`.
This Android flow sends no separate refresh token or email code.

`RefreshTokenResponse` contains `Token` and `ExpireAt`. On success, the app
replaces both values in its stored account data and updates the token in memory.
`MainViewModel.checkUserLoginToken` calls the renewal scheduler.

The endpoint, body, and Android scheduling condition come from app code.
A direct API test also succeeds with the captured iPhone access token.
The iPhone renewal timing remains unobserved.

The test sends `{}` to `POST /api/v1/user/token/refresh` with the existing bearer
token and the captured app headers. The response returns HTTP 200 and `Code: 0`.
`Data` contains a different `Token` and a new `ExpireAt`. The new `ExpireAt` is
about 15 days after renewal, and the new token contains an expiration about
30 days after renewal.

Subsequent `POST /api/v1/user/pet/sync` requests succeed with both the renewed
token and the previous token. Both responses return HTTP 200 and `Code: 0`.
The renewal requires no email code in this test. Continued validity of the
previous token beyond these immediate reads remains untested.

The token used before logout has about 28.8 days until its encoded expiration.
It has no issuance timestamp, so the capture cannot establish when the app
obtained it.

The captured iPhone activity contains no automatic renewal exchange. The direct
API renewal test appears separately in the same capture. The captured
`/api/v1/user/app/init` responses contain an empty `Data` object. The inspected
responses do not supply replacement access tokens through headers or cookies.

The `/api/v1/config/aws/auth` response includes a different `Data.Token`.
That token has about 10 hours until its encoded expiration. Its expiration
matches the other credentials in the response. The app does not use this token
as the main API authorization token in either capture.

### List the cats

`POST /api/v1/user/pet/sync` with an empty body `{}`.

```json
{
  "UserId": "<user id>",
  "Bucket": "<media bucket name>",
  "More": false,
  "Track": "",
  "List": [
    {
      "Id": 1,
      "PetId": "<pet id>",
      "GroupId": "<group id>",
      "Name": "<cat name>",
      "PetType": 0,
      "Type": 1,
      "Gender": 0,
      "Birth": 0,
      "avatar": { "Url": "resources/<hash>.jpg", "Width": 402, "Height": 402 },
      "CreateTime": 946684800000,
      "UpdateTime": 946771200000,
      "Role": 1,
      "Joy1AnnotationStatus": true
    }
  ]
}
```

`PetId` is the identifier the reassignment call takes. `Track` and `More` look
like a cursor for paging.

### List cameras

`POST /api/v1/user/device/sync` with `{}`.

The captured requests and a direct test return HTTP 200 and `Code: 0`.
The direct test uses the signed-in account token and the headers described above.
`Data` contains these fields.

| Field                   | Type    | Meaning                                                     |
| ----------------------- | ------- | ----------------------------------------------------------- |
| `List`                  | Array   | Cameras accessible to the account.                          |
| `More`                  | Boolean | Paging indicator. The tested response contains `false`.     |
| `Track`                 | String  | Paging state. The tested response contains an empty string. |
| `UserId`                | String  | Account identifier field. Empty in the tested response.     |
| `UserGroupList`         | Array   | Household membership and access information.                |
| `UserPurchaseSubscribe` | Object  | Account subscriptions indexed by product code.              |

Each entry in `List` contains these fields.

| Field                 | Type            | Meaning                                                       |
| --------------------- | --------------- | ------------------------------------------------------------- |
| `Id`                  | Integer         | Internal record identifier.                                   |
| `SN`                  | String          | Camera serial number. Recording events reference this value.  |
| `DeviceName`          | String          | Camera display name.                                          |
| `ProductId`           | String          | Model code. The tested records use `JOY1`.                    |
| `ProductType`         | String          | Product family. The tested records use `joy`.                 |
| `Role`                | Integer         | Account role for this camera. See the codes below.            |
| `BindTime`            | Integer         | Binding time in milliseconds since the Unix epoch.            |
| `UpdateTime`          | Integer         | Update time in milliseconds since the Unix epoch.             |
| `Connected.Status`    | Boolean         | Unknown. It stayed false in every sample. See Live checks.    |
| `Connected.Timestamp` | Integer         | Connection timestamp field. The tested values are zero.       |
| `Pet`                 | Array           | Cat records associated with this camera.                      |
| `Setting`             | Object          | Camera configuration returned by this endpoint.               |
| `PurchaseSubscribe`   | Object          | Camera subscription information.                              |
| `Subscribe`           | Null in samples | Additional subscription field with an unknown non-null shape. |
| `Topic`               | Object          | Messaging topics for this camera.                             |
| `AgoraAuth`           | Object          | Credentials for live video and device replay.                 |

Use `SN` to connect a recording to its camera.
All events in the comparison test resolve to a camera through this field.
Android defines model codes `LC01`, `LC02`, and `JOY1` in `DeviceProductType`.
These codes match `ProductId`. Preserve the separate `ProductType` family value.

Android `RoleType` defines `1` as owner, `2` as invitee, and `999` as other.
An invited account reads `Role` 2 on each camera and each cat of the owner.
Its `UserGroupList` has its own group with `Role` 1 and the owner's group with `Role` 2.
The server accepts a type edit of the owner's visit from an invited account. See "Invited accounts".
The zero `Connected.Timestamp` samples do not establish its timestamp unit or update behavior.

Embedded `Pet` records include `PetId`, `Name`, `PetType`, `Type`, `Gender`, `Birth`, and `Breed`.
They also include `Id`, `GroupId`, `SN`, `Role`, `CreateTime`, and `UpdateTime`.
Their Boolean fields are `DetectSuccess`, `SNBind`, and `Joy1AnnotationStatus`.
Their lowercase `avatar` object contains `Url`, `Width`, `Height`, and `Size`.
Resolve these records against `/api/v1/user/pet/sync` through `PetId`.

The observed `Setting.Notification` object contains Boolean fields `AbnormalAlert` and `Highlight`.
This read does not establish how to change those values.
It also does not supply a complete device configuration or firmware status.

#### Subscription and household fields

Both `PurchaseSubscribe` and entries under `UserPurchaseSubscribe` contain the fields below.
The observed account-level entry uses the key `JOY1`.
Subscription codes remain unmapped.

| Fields                                                    | Type    | Meaning                                                       |
| --------------------------------------------------------- | ------- | ------------------------------------------------------------- |
| `GoodsId`, `NextGoodsId`, `SubscribeId`                   | String  | Product and subscription identifiers.                         |
| `ExpireTime`, `FirstSubscribeTime`, `RetentionExpireTime` | Integer | Subscription timestamps in milliseconds since the Unix epoch. |
| `PurchaseMode`, `SubscribeStatus`, `SubscribeType`        | Integer | Service codes with unconfirmed meanings.                      |

Each `UserGroupList` entry contains `GroupId`, `Role`, `Owner`, and `Member`.
`Owner` is an object, and `Member` is an array of account objects.
These objects include `UserId`, `Name`, `Avatar`, `Email`, `EmailBind`, `Phone`, and `DialCode`.
They also contain integer fields `LoginType`, `Status`, and `LastActiveTimestamp`.
Nonzero activity timestamps use milliseconds since the Unix epoch.
The observed `Avatar` values are null.

#### Messaging and video credentials

`Topic.Publish` and `Topic.Receive` contain arrays of topic strings.
`Topic.Shadow` contains strings named `configInfo` and `systemInfo`.
A shadow stores device state in the cloud.
The camera list supplies topic names and shadow names without their state documents.

`AgoraAuth` contains `AppId`, `RoomId`, `Token`, `Uid`, `RemoteUid`, and `ExpireTime`.
Its `Live` and `Replay` objects contain the same fields plus `IotAuth`.
Each `IotAuth` object contains `Token` and `ExpireTime`.
The identifiers `Uid` and `RemoteUid` are integers. Other identifiers and tokens are strings.
Nonzero expiration values use milliseconds since the Unix epoch.

Some nested fields contain empty strings or zero expiration values.
The presence of these credentials does not establish a working live stream or device replay session.
Those media paths remain untested.
Keep tokens, account details, and private topic names out of logs and entity attributes.

Camera paging remains untested because the inspected responses contain `More: false` and an empty `Track`.
The tested request body is `{}`. A request schema for continuation remains unknown.

### Battery and charging status

Battery readings come from an AWS IoT shadow, a stored device state document.
Use the shadow name in `Topic.Shadow.configInfo` from the camera list.
Android `BindDevice.getBattery` reads `configInfo.state.reported.battery`.
The camera list itself contains no battery reading.

The shadow response contains these fields.

| Field                                          | Type    | Meaning                                                        |
| ---------------------------------------------- | ------- | -------------------------------------------------------------- |
| `state.reported.battery.SOC`                   | Number  | Battery state of charge as a percentage.                       |
| `state.reported.battery.charging`              | Boolean | Charging state used by the app.                                |
| `metadata.reported.battery.SOC.timestamp`      | Integer | Time of the last reported battery percentage, in Unix seconds. |
| `metadata.reported.battery.charging.timestamp` | Integer | Time of the last reported charging state, in Unix seconds.     |

`SOC` means state of charge, the remaining battery percentage.
Live reads return both integer and fractional values.
Android `BatteryEntity.getBatteryLevel` rounds the number to the nearest integer for display.
It does not multiply the value by 100.
`Joy1BoardLoader.display` uses `charging` to show the charging indicator.

This example contains sample values and omits other shadow fields.
The shadow response has no SiiPet `Code`, `Msg`, or `Data` envelope.

```json
{
  "state": {
    "reported": {
      "battery": {
        "SOC": 72.4,
        "charging": false
      }
    }
  },
  "metadata": {
    "reported": {
      "battery": {
        "SOC": { "timestamp": 946684800 },
        "charging": { "timestamp": 946684800 }
      }
    }
  },
  "timestamp": 946685400,
  "version": 12
}
```

#### Read the battery shadow

MQTT is a protocol for exchanging messages through named topics.
The tested read uses MQTT over secure WebSockets on port 443.
Android `AWSShadowManager.getShadowData` requests the shadow through the same MQTT topics.

1. Send `{}` to `POST /api/v1/user/device/sync` with the main API bearer token.
2. Read the camera `SN` and its `Topic.Shadow.configInfo` value from `Data.List`.
3. Send `{}` to `POST /api/v1/config/aws/auth` with the same bearer token.
4. Connect to `wss://<IotCore.Endpoint>/mqtt` with the credentials and client identifier described below.
5. Subscribe to `$aws/things/<SN>/shadow/name/<shadow name>/get/accepted` and the corresponding `/get/rejected` topic.
6. Publish an empty payload to `$aws/things/<SN>/shadow/name/<shadow name>/get`.
7. Read `state.reported.battery` from the `/get/accepted` response.

Use the returned shadow name for `<shadow name>`.
The `configInfo` field holds a shadow name rather than a complete MQTT topic.
The tested subscriptions and requests use QoS 1, which requests delivery at least once.
A later check also granted QoS 0 for subscriptions and reads.
The integration uses QoS 0.
Publishing to `/get` reads stored state without changing the camera configuration.
See the [AWS shadow read procedure](https://docs.aws.amazon.com/iot/latest/developerguide/device-shadow-data-flow.html).

Take the server hostname from `Data.IotCore.Endpoint`.
That field holds an `https://` URL, so use its host part.
`Data.IotCore` also holds `AccessKeyId`, `SecretAccessKey`, `SessionToken`, and `ExpireTime` in milliseconds.
Android `AWSManager.getS3Client` creates shared credentials from `Data.S3.AccessKeyId`, `SecretAccessKey`, and `SessionToken`.
Its MQTT connection uses those credentials too, and the direct MQTT test follows that path.
The tested response supplies identical credential values under `Data.IotCore`.
The connection uses AWS Signature Version 4 with signing service `iotdevicegateway` and the region from the endpoint hostname.
The tested region is `us-east-1`.

The app gets its MQTT client identifier from `Data.MqttClientId` in the login response.
Its observed format is `<IdentityId>:<suffix>`.
Use `Data.IdentityId` from the AWS authorization response for `<IdentityId>`.
A separate client using `<IdentityId>:<random UUID suffix>` connects and reads the battery shadows successfully.
The tested suffix is a random UUID encoded as 32 hexadecimal characters.
A generic identifier without that account prefix fails with `AWS_ERROR_MQTT_UNEXPECTED_HANGUP`.
This comparison establishes a working identifier format, but does not establish the complete server policy.

Use a unique suffix for each simultaneous connection.
If two connections use the same identifier, AWS disconnects the existing connection.
See the [AWS MQTT connection builder](https://github.com/aws/aws-iot-device-sdk-python-v2/blob/main/awsiot/mqtt_connection_builder.py).
Keep credentials, identity values, serial numbers, and complete topics out of logs.

The direct HTTPS `GetThingShadow` test returns HTTP 403 with `ForbiddenException` using the returned IoT credentials and AWS SDK signing.
Use the tested MQTT path for reads.
Direct battery reads return `/get/accepted` responses.
Android also subscribes to `/update/documents` and reads `current.state.reported.battery` from those messages.
The observed subscription window contains no battery change messages.

#### Power state and freshness

Live samples from unplugged cameras report `charging: false`.
The inspected battery object contains `SOC` and `charging` without a separate external power field.
The inspected Android battery model also contains only those two values.
The app treats `charging: true` as charging.
A live sample from a camera on external power reported `charging: true` at 99% battery.

Do not interpret `charging: false` as proof that the power cable is disconnected.
Behavior with a full battery on external power remains untested.
Expose the value as charging status. It does not establish whether the camera is on external power.
If a battery field is missing or null, treat that value as unknown.

Shadow values describe the last reported state.
The observed battery timestamps predate retrieval by several minutes.
Use the individual field timestamps to determine the age of each reading.
The top-level `timestamp` describes the AWS response, so it does not establish when the camera measured the battery.
These timestamps use seconds, unlike the milliseconds in the SiiPet HTTP API.
See the [AWS shadow document fields](https://docs.aws.amazon.com/iot/latest/developerguide/device-shadow-document.html).

`POST /api/v1/user/account/detail` also returns `Data.Setting.Notification.LowBattery`.
That Boolean controls low battery notifications.
It is an account preference rather than a battery reading.

### Other device state

The MQTT read procedure above also returns connection, firmware, network, and camera configuration fields.
Read the shadow named by `Topic.Shadow.systemInfo` for system information.
Read the shadow named by `Topic.Shadow.configInfo` for camera configuration.
Direct reads succeed for both shadows on JOY1 devices.
The field meanings below also use Android app version 2.1.1.

Read actual device values from `state.reported`.
`state.desired` holds requested values, and `state.delta` contains differences between requested and reported state.
Live battery replies contain different percentages in `desired` and `reported`.
Do not use `desired.battery` or `delta.battery` as a battery measurement.
See the [AWS shadow state definitions](https://docs.aws.amazon.com/iot/latest/developerguide/device-shadow-document.html).

#### Connection, firmware, and Wi-Fi

These paths are relative to `state.reported` in the `systemInfo` shadow.
RSSI is a received signal strength measurement.
Firmware is the software that runs on the device.

| Field                       | Type    | Meaning                                                                        |
| --------------------------- | ------- | ------------------------------------------------------------------------------ |
| `esp32.connected.status`    | Boolean | Connection flag that the Android app uses for JOY1 online status.              |
| `esp32.connected.timestamp` | Integer | Device-provided connection time. Its unit and update rules remain unconfirmed. |
| `main.connected.status`     | Boolean | Separate connection flag that can differ from the JOY1 online flag.            |
| `main.connected.timestamp`  | Integer | Device-provided connection time with unconfirmed units.                        |
| `main.sysVersion`           | String  | Reported main firmware version.                                                |
| `esp32.sysVersion`          | String  | Reported firmware version for the `esp32` component.                           |
| `esp32.bootVersion`         | String  | Reported boot software version for the `esp32` component.                      |
| `main.rssi`                 | Integer | Wi-Fi signal reading. Live samples contain negative values.                    |
| `main.ssid`                 | String  | Wi-Fi network name shown by the app.                                           |
| `main.ip`, `main.mac`       | String  | Network addresses reported by the device.                                      |

Android `StateReported` maps its `joyGimbal` property to the JSON key `esp32`.
`BindDevice.isJoyOnline` reads `systemInfo.state.reported.esp32.connected.status` through that property.
Live replies contain `esp32.connected.status: true` while `main.connected.status` and the camera list `Connected.Status` are false.
This identifies the online field used by the JOY1 app.
Offline transitions and reporting delays remain untested.

Android `BindDevice.getDevSysVersion` reads `state.reported.main.sysVersion`.
Its `getDevCurSysVersion` method reads `state.desired.main.sysVersion`, which is the requested version.
Use the reported version when showing installed firmware.

`DeviceWifiSetupVM.updateBindDevice` reads `main.ssid` and `main.rssi` for the Wi-Fi screen.
The app accepts negative RSSI values in that read path.
That code does not establish a unit or a conversion to a signal percentage.
The observed `main.bind` Boolean and `main.runOn` string have unconfirmed meanings.

Network names and addresses reveal private network details.
Keep `ssid`, `ip`, and `mac` values out of logs and public examples.
Redact them from diagnostics if an integration stores these fields.

#### Camera configuration

These paths are relative to `state.reported` in the `configInfo` shadow.
The direct reads establish their presence and types.
The tests do not change device configuration or establish every transition.

| Field                                      | Type             | Meaning                                                                      |
| ------------------------------------------ | ---------------- | ---------------------------------------------------------------------------- |
| `privacyMode.active`                       | Boolean          | Privacy mode flag used by the JOY1 app.                                      |
| `privacyStatus`                            | Boolean          | Separate privacy flag with unconfirmed behavior.                             |
| `recordInfo.recording`                     | Boolean          | Reported recording flag. Live samples contain `false`.                       |
| `autoTrack`                                | Boolean          | Reported automatic tracking flag.                                            |
| `lightStatus`                              | Boolean          | Separate light flag with unconfirmed behavior.                               |
| `fillLight.autoLight`                      | Boolean          | Automatic illumination configuration shown by the app.                       |
| `fillLight.lowLight`                       | Boolean          | Low-light configuration shown by the app.                                    |
| `fillLight.level`                          | Integer          | Illumination level selected in the app.                                      |
| `fillLight.brightness2`                    | Integer          | Numeric illumination parameter associated with the selected level.           |
| `fillLight.active`, `fillLight.brightness` | Integer          | Additional illumination fields with unconfirmed units and code meanings.     |
| `pir.level`, `pir.sense`                   | Integer          | Motion sensitivity level and its numeric parameter.                          |
| `otaMode.mode`                             | Integer          | Firmware update mode. See the Android codes below.                           |
| `otaMode.start`, `otaMode.end`             | Integer          | Update window fields with unconfirmed units and scheduling rules.            |
| `cloudMode.enableCloud`                    | Boolean          | Reported cloud storage flag.                                                 |
| `cloudMode.leftCloudStorageQuota`          | Integer          | Remaining cloud quota field with unconfirmed units.                          |
| `cloudMode.localRecordDuration`            | Integer          | Local recording duration field with unconfirmed units.                       |
| `tzName`                                   | String           | Device timezone name.                                                        |
| `petFeature`                               | Array of strings | Pet feature references. The test does not establish their identifier format. |

`BindDevice.isJoyPrivacyStatus` reads `privacyMode.active`.
Use that field for the JOY1 app privacy state.
The separate `privacyStatus` flag does not establish the same behavior.
The samples contain `false` for both flags, so a privacy mode transition remains untested.

The `pir` object contains configuration for motion detection.
It does not contain a motion event in the inspected replies.
The presence of `recordInfo.recording` also does not establish whether a live stream is active.
The shadow can retain either value after its reporting time.

Android `JoyFillLightSetActivity.initStepViewData` labels levels `1`, `2`, and `3` as low, medium, and high.
Its slider fallback values are `40`, `70`, and `120`.
`JoyFillLightSetVM.requestConfigFillLight` obtains `brightness2` from a configuration map and falls back to `60` when the selected level has no entry.
These client defaults do not establish device limits or a percentage scale.

Android `JoyPirSenseSetActivity.initPirSenseLevelData` offers level `2` as medium and level `3` as high.
Its fallback `sense` values are `75` and `60`, respectively.
The app can replace those values through a configuration map.
The inspected UI does not establish a physical unit for `sense`.

Android `DeviceOtaMode` defines `0` as automatic, `1` as manual, and `2` as unknown.
These codes describe update mode rather than update progress or success.
`otaMode` reads do not establish that a firmware update is available.

#### State age and update messages

AWS field metadata records reporting times in Unix seconds.
Device-provided timestamps such as `esp32.connected.timestamp` are separate values with their own format.
Do not apply the metadata time unit to those values without evidence.
Use the field metadata to judge the age of a reported value.

The read test also subscribes to `/update/documents` for both shadows.
AWS accepts those subscriptions, but a 45-second observation receives no update messages.
This result does not establish a reporting interval or show that updates are unavailable.
Android handles these messages through `current.state.reported`.
`/get/accepted` replies place the state directly under `state.reported`.

AWS uses `version` to identify successive versions of a shadow.
Keep version tracking separate for each camera and shadow.
A version change does not establish that every field contains a new measurement.
See the [AWS shadow version and metadata definitions](https://docs.aws.amazon.com/iot/latest/developerguide/device-shadow-document.html).

### List visits for a day

`POST /api/v1/pet/toilet/event`

```json
{
  "IncludeLocal": true,
  "FollowRegisterTimezone": true,
  "Date": "2000-01-01 00:00:00"
}
```

`Data.TodaySummary` holds one entry per cat. The baseline fields depend on the
time in `Date`, and the visit list does not. The app sends the current time for
today, and the integration does the same.

| Field              | Meaning                                                             |
| ------------------ | ------------------------------------------------------------------- |
| `PottyTimes`       | Visit count for the day.                                            |
| `PottyAvgTime`     | Average visit duration in milliseconds.                             |
| `BaselineTimes`    | The cat's expected visit count from midnight to the time in `Date`. |
| `BaselineAvgTime`  | The cat's expected duration in milliseconds, for the same period.   |
| `NeededTotalDays`  | Days of data the baseline needs.                                    |
| `CurrentTotalDays` | Days of data collected so far.                                      |

`Data.List` holds one entry per visit.

| Field                 | Meaning                                                         |
| --------------------- | --------------------------------------------------------------- |
| `EventId`             | Visit identifier, a UUID. The reassignment call takes it.       |
| `PetId`               | The assigned cat.                                               |
| `PetIds`              | The assigned cats as an array. Reassignment writes this.        |
| `GroupId`             | Household identifier.                                           |
| `SN`                  | Camera serial number.                                           |
| `EventTimestamp`      | Visit start, milliseconds since epoch.                          |
| `Duration`            | Visit length in milliseconds.                                   |
| `Type`                | Event classification. See the values below.                     |
| `Note`                | Free text note, empty by default.                               |
| `CloudStorageStatus`  | Cloud storage flag.                                             |
| `LocalStorageStatus`  | Local storage flag.                                             |
| `TimestampAccurate`   | Timestamp accuracy flag.                                        |
| `EventAbnormal`       | Event abnormality code. The captured value is `0`.              |
| `FecesAbnormal`       | List of stool abnormality codes, or `null`.                     |
| `LabelPetIds`         | Additional cat labels. Their meaning remains unconfirmed.       |
| `ToiletVideo.Cover`   | Thumbnail object with `Url`, `Width`, `Height`, and `Size`.     |
| `ToiletVideo.RawInfo` | Video object. See the media section.                            |
| `FecesImage`          | Optional stool image with `Url`, `Width`, `Height`, and `Size`. |
| `UserAnnotation`      | Flags named `FecesError`, `MultiPet`, and `ToiletError`.        |

Resolve `PetId` and `PetIds` against the cat list to show names and avatars.
Preserve an unassigned or unknown cat when an identifier has no matching cat.
The response also contains `More` and `Track`. History paging remains untested.

### Event classification

Android defines these values in `PottyType`.

| `Type` | Android name | Meaning                 |
| ------ | ------------ | ----------------------- |
| `0`    | `UNKNOWN`    | Unknown classification. |
| `1`    | `STAY`       | Lingering.              |
| `2`    | `POTTY`      | Poop.                   |
| `3`    | `URINE`      | Pee.                    |

Android maps `POTTY` to the poop labels in its interface.
Its `PottyEvent.isPottyEvent` method treats both `2` and `3` as litter box use.
Keep `0` as unknown. Do not infer pee from a missing stool image.

Abnormality is separate from this classification.
Android marks a pee or poop event as abnormal when `FecesAbnormal` contains a positive value.
One captured poop event contains a stool image and `FecesAbnormal: [0, 0]`.
The complete meanings of the abnormality codes remain unknown.

All captured event examples use `Type: 2`. The other classification values come
from Android code and still need comparison with live examples.

### Read one recording

`POST /api/v1/device/toilet/event/detail`

```json
{
  "EventId": "<event id>"
}
```

The direct test returns HTTP 200 and `Code: 0`.
`Data` contains the same recording and metadata fields as an entry in the event list.
The endpoint uses `device` in its path.

### Edit a visit

`POST /api/v1/pet/toilet/event/annotate`

```json
{
  "EventId": "<event id>",
  "Result": "{\"PetIds\":[\"<pet id>\"],\"GonePotty\":true,\"Manual\":true}",
  "Type": 2
}
```

`Result` is a JSON object encoded as a string. Do not send it as a nested object.

| Field in `Result` | Meaning                                                               |
| ----------------- | --------------------------------------------------------------------- |
| `PetIds`          | The cats to assign. An array, so a shared visit is possible.          |
| `GonePotty`       | Whether the cat used the box. The app calls the other case Lingering. |
| `Manual`          | Marks a manual assignment.                                            |

The outer `Type` selects the edit operation. It is separate from the event classification.
Android defines these operations in `RequestAnnotateEventType`.

| Outer `Type` | Android name       | Fields inside the encoded `Result` |
| ------------ | ------------------ | ---------------------------------- |
| `1`          | `MultiPet`         | `PetIds`                           |
| `2`          | `ToiletError`      | `PetIds`, `GonePotty`, `Manual`    |
| `3`          | `ToiletFecesError` | `AbnormalType`, `Type`             |

For operation `3`, `AbnormalType` is a list and the inner `Type` is the event classification.
These schemas come from Android models and their repository methods.
Operation `1` remains untested against the service.

The response body is `{"Code":0,"Msg":"success","Data":{}}`.

A captured operation `2` reassigns a poop visit from one cat to another.
The next event list returns the new assignment.

Live tests on one visit give these results. The visit detail and the day list agree after each call.

| Call                                                     | Before    | After                                      |
| -------------------------------------------------------- | --------- | ------------------------------------------ |
| Operation `3` with `{"Type": 3}`                         | poop      | pee. `FecesAbnormal` is cleared to null.   |
| Operation `2` with `GonePotty` true, the same cats       | pee       | poop. `FecesAbnormal` stays null.          |
| Operation `3` with `{"AbnormalType": [0, 0], "Type": 2}` | pee       | poop with `FecesAbnormal` `[0, 0]`.        |
| Operation `2` with `GonePotty` false, the same cats      | poop      | lingering. `FecesAbnormal` stays `[0, 0]`. |
| Operation `2` with `GonePotty` true, the same cats       | lingering | poop. `FecesAbnormal` stays `[0, 0]`.      |
| Operation `2` with another cat and `Manual` true         | cat A     | cat B                                      |
| Operation `2` with two cats and `Manual` true            | cat A     | both cats in `PetIds`                      |

A stool image stays through all these calls. Only operation `3` to pee changes the stool codes.
Operation `3` with `{"Type": 3}` also turns a poop visit without a stool image into pee.
The Android app offers pee only from the stool image editor, so it asks for a photo first.
The responses do not contain `Manual`, so its stored value is not visible.

### Read the calendar

`POST /api/v1/pet/toilet/data/calendar`

This request reads daily summaries for one cat.
The following example requests the first day of January.
Its end date is the following day.

```json
{
  "PetId": "<pet id>",
  "StartDate": "2000-01-01 00:00:00",
  "EndDate": "2000-01-02 00:00:00",
  "IncludeLocal": true,
  "FollowRegisterTimezone": true
}
```

| Field                    | Type    | Meaning                                                            |
| ------------------------ | ------- | ------------------------------------------------------------------ |
| `PetId`                  | String  | Cat identifier from `/api/v1/user/pet/sync`.                       |
| `StartDate`              | String  | First requested calendar date, formatted as `YYYY-MM-DD HH:MM:SS`. |
| `EndDate`                | String  | Calendar date after the requested period, in the same format.      |
| `IncludeLocal`           | Boolean | Requests inclusion of local records. Tested with `true`.           |
| `FollowRegisterTimezone` | Boolean | Requests the registered timezone. Tested with `true`.              |

The direct tests return HTTP 200 and `Code: 0`.
`Data.PetId` matches the requested cat.
`Data.DataCalendar` contains daily entries, or `null` when the tested interval has no entries.
Treat a null value as an empty list.

This example shows the response data with sample values.

```json
{
  "PetId": "<pet id>",
  "DataCalendar": [
    {
      "Date": "2000-01-01",
      "Normal": 2,
      "Abnormal": 1,
      "NormalDuration": 120000,
      "AbnormalDuration": 60000,
      "AbnormalSummary": {
        "AboveBaseline": false,
        "Event": true,
        "Frequency": false,
        "IrregularDuration": false
      }
    }
  ]
}
```

| Daily field                         | Type    | Meaning                                                       |
| ----------------------------------- | ------- | ------------------------------------------------------------- |
| `Date`                              | String  | Calendar date formatted as `YYYY-MM-DD`.                      |
| `Normal`                            | Integer | Count of normal litter box use events.                        |
| `Abnormal`                          | Integer | Count of abnormal litter box use events.                      |
| `NormalDuration`                    | Integer | Total duration of normal events, in milliseconds.             |
| `AbnormalDuration`                  | Integer | Total duration of abnormal events, in milliseconds.           |
| `AbnormalSummary.AboveBaseline`     | Boolean | Above-baseline flag. The exact condition remains unknown.     |
| `AbnormalSummary.Event`             | Boolean | Event abnormality flag. The exact condition remains unknown.  |
| `AbnormalSummary.Frequency`         | Boolean | Frequency flag. The exact condition remains unknown.          |
| `AbnormalSummary.IrregularDuration` | Boolean | Irregular-duration flag. The exact condition remains unknown. |

`Normal` and `Abnormal` classify normality. They do not separate pee from poop.
Use event records to obtain waste type, cat assignment, and media references.
The calendar contains no event identifiers, recording URLs, or snapshot references.

#### Date boundaries and empty results

The tested interval includes the start date and excludes the end date.
A same-date request from `00:00:00` to `23:59:59` returns `DataCalendar: null`.
Moving the end date to the following midnight returns the selected day.
Changing that end time to `23:59:59` leaves the result unchanged in the comparison test.
Use midnight boundaries with the date after the last requested day as `EndDate`.

The wider response contains sorted, unique dates with gaps.
It does not provide a row for every requested date.
The response does not explain whether each missing date means no events or unavailable history.
The tested response contains no paging fields.
Maximum date range, retention limits, and alternate timezone behavior remain untested.

#### Comparison with event records

Two daily comparisons use `/api/v1/pet/toilet/event` with the same timezone and local-record flags.
Both event responses contain `More: false`.
The comparison selects the requested cat and event types `2` and `3`.
`Normal + Abnormal` matches the selected event count in both tests.
`NormalDuration + AbnormalDuration` matches the sum of event durations in milliseconds.

One tested day contains abnormal events.
Its `Abnormal` count and `AbnormalDuration` match events with a positive `FecesAbnormal` entry.
This sample does not establish every server rule for classifying abnormal events.

## Media

Images and video live in S3. A bucket key identifies an object within a bucket.
The `Url` fields in the captured records contain bucket keys.
`ToiletVideo.Cover.Url` identifies the thumbnail, and `ToiletVideo.RawInfo.Url` identifies the MP4 recording.
When `FecesImage` exists, `FecesImage.Url` identifies the stool image.

`ToiletVideo.RawInfo` also contains `CreateTime`, `Duration`, `Height`, `Width`, `Md5`, and `Size`.
The tested video size matches `Size` in bytes.
`Md5` is the lowercase hexadecimal MD5 of the whole file. A live download of a recording matched both `Md5` and `Size`.
`ToiletVideo.Cover.Size` and `FecesImage.Size` match the byte count of the image.
Both event `Duration` and video `Duration` match the decoded clip length when interpreted as milliseconds.

### Access media

`POST /api/v1/config/aws/auth` with `{}` returns temporary credentials.
Use the main API bearer token for this request.
The direct test returns HTTP 200 and `Code: 0`.

`Data` contains `ExpireTime`, `IdentityId`, `IdentityPoolId`, `Token`, `S3`, and `IotCore`.
`Data.S3` contains the fields needed for media access.

| Field             | Purpose                                             |
| ----------------- | --------------------------------------------------- |
| `AccessKeyId`     | Temporary access key identifier.                    |
| `SecretAccessKey` | Secret used to sign S3 requests.                    |
| `SessionToken`    | Temporary session credential required with the key. |
| `ExpireTime`      | Credential expiration.                              |
| `S3Bucket`        | Bucket used to retrieve media.                      |
| `UploadPath`      | Upload path supplied by the service.                |

Android `AWSManager` uses these three credentials with an S3 client in `us-east-1`.
Its `getS3Url` method signs a GET URL for `S3Bucket` and the requested object key.
A signed URL grants temporary access to one object.

The direct test uses AWS Signature Version 4 with a five-minute URL lifetime.
It retrieves a complete MP4 recording and its JPEG thumbnail through HTTP range requests.
Both requests return HTTP 206. The video byte count matches the API metadata.
The video decoder reads a frame successfully without additional decryption.

A separate test downloads the stool snapshot referenced by `FecesImage.Url`.
The request returns HTTP 200 and a JPEG image.
Its byte count, width, and height match the event metadata.
The image decoder reads it successfully. The tested snapshot contains a full camera frame.

The observed credential lifetime is about 10 hours.
A signed URL expires when its temporary credentials expire, even if its requested lifetime is longer.
See the [S3 signed URL documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).
Refresh expired credentials before generating a playback URL.
Keep credentials and signed URLs out of logs and published metadata.

### Home Assistant playback

Home Assistant integrations can expose recordings through its media browser.
The tested MP4 contains H.265 video. A codec is a format for encoding video or audio.
This sample has no audio stream.

Playback depends on whether the browser or player supports the codec.
Home Assistant media source does not convert media to another encoding.
See the [Home Assistant media documentation](https://www.home-assistant.io/integrations/media_source/).

Initial playback targets macOS and iPhone clients with native H.265 support.
Video conversion is outside this scope.

The integration shows the recordings in the Home Assistant media browser:

- A recording resolves to a signed S3 URL. Its lifetime is one hour, or less when the credentials expire sooner.
- Covers, stool images, and cat avatars go through an authenticated Home Assistant view.
  The view signs a 5-minute URL, fetches the image on the server, and returns the bytes.
- The integration renews the credentials 10 minutes before `ExpireTime`.
  When S3 returns 403 to the image view, the integration gets new credentials and tries once more.

The download and decoding tests establish access to cloud media.
Access to recordings stored only on the device remains untested.

### Home Assistant device state

The integration reads the device state as described in "Read the battery shadow":

- It keeps one MQTT connection open over secure WebSockets, with QoS 0 for subscriptions and reads.
- It subscribes to `get/accepted`, `get/rejected`, and `update/documents` for both shadows of each camera. Then it reads both shadows.
- It reads both shadows of each camera again every 5 minutes, because the rate of update messages is not known.
- It connects again with new credentials 10 minutes before the credentials expire.
- It ignores a document with a lower `version` than the last one of the same shadow.
- A camera is skipped for one hour when AWS IoT refuses its subscription, or when its start fails twice in a row. Its entities become unavailable, and the other cameras keep working.
- If the connection stays down for 15 minutes, the device state entities become unavailable.
- It never publishes to `update`, so it never changes a camera setting.

## Findings from the Android app

These findings come from static inspection of the Android app version 2.1.1.
They were not tested against the service unless this section says so.

### Session errors

- The app treats envelope `Code` -2 and -4 as an ended session. It then shows "Login failed" and opens the sign-in screen.
- The app does not read the HTTP status. The integration also treats HTTP 401 and 403 as an ended session.
- The app renews the token only when it opens, with the rule `now + 24 h > ExpireAt`. A failed renewal is only logged.
- A wrong email code at `/api/v1/user/email/register/login` returns `Code` 10004. The app shows other codes with `Msg`.
- The app has no screen that signs in with a password. It can set a password with an emailed code. See "Set a password".

### Request headers of the Android app

| Header                | Format                                       |
| --------------------- | -------------------------------------------- |
| `User-Agent`          | `siipet-app/<version>`                       |
| `X-App-Version`       | `<version>`                                  |
| `X-Device-Model`      | `android-phone <model>`                      |
| `X-Device-OS`         | The Android release number, for example `15` |
| `X-Device-Language`   | `en` or `zh-TW`                              |
| `X-Device-Identifier` | A stable per-install identifier              |
| `X-Timezone`          | An IANA time zone                            |
| `X-Timestamp`         | Milliseconds since the Unix epoch            |
| `Authorization`       | `Bearer <token>` after sign-in               |

The integration sends the header set of the captured iOS app with an Android-style `x-device-model`. Live tests show that the API accepts this mix.

### Day list paging

- The request class for `/api/v1/pet/toilet/event` has `Date`, `IncludeLocal`, `IsMock`, and `FollowRegisterTimezone`. It has no cursor field.
- The app makes one request per day. It never reads `More` or `Track`.

### Memo edit

- `POST /api/v1/pet/toilet/event/edit` with `{"EventId", "Note"}`.
- A live test sets a memo, and an empty `Note` clears it.
- The app limits the note to 200 characters. It allows the edit only when the visit `GroupId` equals the user `GroupId`.
- The request can also carry `FecesImage`. No screen in this app version sends it.

### Visit delete

- `POST /api/v1/device/toilet/event/delete` with `{"EventId"}` deletes a visit.
  A live test returns `Code` 0, and the visit leaves the day list.
  The detail call for it then returns `Code` 40000 with `Msg` "The media you viewed has expired".
  Its recording and cover were still in S3 right after the delete.
- `POST /api/v1/pet/toilet/event/feces/image/delete` with `{"EventId"}` deletes only the stool image.
- `POST /api/v1/device/replay/delete` is for behavior replays. The app does not call it.

### Invited accounts

- `PottyRepository.isMyMedia` compares the visit `GroupId` with the `GroupId` of the account.
  If both are set and they differ, the app shows `shared_device_tip` and stops.
- The edit button, the stool photo upload, and the delete use this check.
  For an invited account, the owner's visits fail it. "Memo edit" has the same `GroupId` rule.
- The check runs in the app. A live test shows that the server accepts operation 3 from an invited account. See Live checks.

### Annotate operations

- Operation 1 (`MultiPet`) sends `{"PetIds"}` from the multi-pet dialog.
- Operation 2 (`ToiletError`) sends `{"PetIds", "GonePotty", "Manual"}` from the "Edit Event" sheet.
  - `GonePotty` is the answer to "Did your cat use the litter box?".
  - `Manual` is true when you change the pets.
  - After success, the app sets the type to 2 for `GonePotty` true and to 1 for false. This operation cannot select pee.
- Operation 3 (`ToiletFecesError`) sends `{"AbnormalType": [shape, color], "Type"}` from the stool sheet.
  - Normal stool: `{"AbnormalType": [0, 0], "Type": 2}`.
  - Pee: `{"Type": 3}`.
- A change from lingering to pee takes two calls: operation 2 with `GonePotty` true, then operation 3 with `Type` 3.

### Abnormal codes

`/api/v1/config/system/config` returns `Data.Memory.AbnormalToilet`, a list of objects with `Shape`, `Color`, and `Event` lists.
Each item has `Type`, `Title`, and `Icon`. Code 0 means normal.

| Group | Codes                                |
| ----- | ------------------------------------ |
| Shape | 101 to 104, and 199 for other shapes |
| Color | 201 to 206, and 299 for other colors |
| Event | 301, "Potty Overtime"                |

The Android app also defines shape code 105 (sausage-shaped), which the
captured server config does not list.

- Index 0 of `FecesAbnormal` is the shape code. Index 1 is the color code.
- `EventAbnormal` holds an event code.

### Statistics endpoints

- `POST /api/v1/pet/toilet/data/trend` with `{"PetId", "Days": 7 or 30, "FollowRegisterTimezone": true}`.
- `POST /api/v1/pet/toilet/data/compare` with `{"PetId", "StartDate", "CompareType": 1 (week) or 2 (month), "FollowRegisterTimezone": true}`.
- Both return daily entries with `Date`, `Normal`, `Abnormal`, `NormalDuration`, `AbnormalDuration`, and `AbnormalSummary`.

## Live checks

These results come from tests against a real account.

- The server checks `x-device-model` on authenticated calls. With the same valid token and the same `x-device-identifier`, only the model changed:

  | `x-device-model`                 | Result    |
  | -------------------------------- | --------- |
  | `Home Assistant`                 | `Code` -2 |
  | `HomeAssistant`                  | `Code` -2 |
  | `Mac`                            | `Code` -2 |
  | `iPhone`                         | `Code` 0  |
  | `iPhone 16 Pro`                  | `Code` 0  |
  | `iPhone 16 Pro (Home Assistant)` | `Code` 0  |
  | `android-phone Home Assistant`   | `Code` 0  |

- The -2 response has `Msg` "token illegal, other device device has logged in". The message is misleading. The token is valid, and no other device caused the error.
- The `Accept`, `Accept-Language`, and `Accept-Encoding` headers do not change the result.
- The email-code sign-in returned `Code` 0 with the model `Home Assistant`. The error showed on the first authenticated call.
- A token from an email-code sign-in works from another client that sends the same `x-device-identifier` and an accepted model.
- After an email-code sign-in from another client, the phone app's session kept working for at least one hour. Then the phone's calls failed with -2, although the phone sent an accepted model. The cause is not known.
- After another client renewed the phone's token, the previous token kept working on the phone for about 70 minutes, until the failure above. The new token also worked.
- A 7-day local copy downloaded 52 recordings, 52 covers, and 12 stool photos. Every recording matched its `Size` and `Md5`, and every cover and stool photo matched its `Size`.
- An email-code session of a second client, neither Home Assistant nor the phone app, returned -2 about two days after its sign-in, while its `ExpireAt` was still in the future. The cause is not known.
- After an email-code sign-in from Home Assistant, the phone app kept its old session. Both sessions worked for about one hour, and the check stopped then. An email-code sign-in from Home Assistant always sends an `x-device-identifier` that Home Assistant made. The check does not show whether the phone fails later, as in the check above.
- The baseline fields change with the time in `Date`. For one day, `BaselineTimes` was 0.03 to 0.13 with 00:00:00, 1.46 to 1.69 with 06:00:00 and 12:00:00, and 2.04 to 3.13 with 23:59:59. `BaselineAvgTime` changed too. The visit list was the same.
- `Connected.Status` was false for every camera in every sample, also while the cameras recorded visits and during a live stream. Between a read during a live stream and a read after it, only the `AgoraAuth` tokens and expiry times changed, and they changed for every camera. `user/device/sync` has no field that shows a camera online or streaming.
- The email code request is rate limited per day: `Code` 10010, `Msg` "Too many request today. Please try again tomorrow."
- A wrong email code is `Code` 10004 (already handled).
- A SigV4 query-string presigned GET for `<bucket>.s3.amazonaws.com` in `us-east-1`, built without an AWS library, returns the cover image. S3 labels the cover object `image/jpg`. The bytes are JPEG.
- The media browser lists the recordings by day. The thumbnails load through the image view, and the browse results contain no S3 URL.
- The cat avatars are JPEG files, and they load through the image view.
- The recordings play in Safari on macOS and on iOS, and in the Home Assistant app on macOS and on iOS.
- The detail call for an event id that does not exist returns `Code` 10000 with an empty `Msg`.
- Edits and a delete were tested on visits that the account owner picked. See "Edit a visit" and "Visit delete".
- The three Home Assistant actions ran against the live account, on visits that the account owner picked. The SiiPet app showed each change.
  - `siipet.list_visits` returned today and the day before, and a day 20 days back. A date 31 days back was refused.
  - `siipet.update_visit` moved a poop visit to another cat and back. It set a memo and cleared it with an empty memo. A reassign kept the memo.
  - It changed a poop visit to pee. A reassign of that pee visit sent op 2 and then op 3, and the visit stayed pee with the new cat.
  - The same visit then went to poop, lingering, and poop. After pee to poop, `FecesAbnormal` was null, as the op 2 results predict.
  - A reassign to the Unknown cat, and a type that the visit already had, were refused before any call.
  - `siipet.delete_visit` deleted a lingering visit, and the visit left the day list.
- The websocket commands of the dashboard card ran against the live account.
  - A signed cover path from `siipet/day` loaded without a login header and returned a JPEG.
  - For one month, the days with any true `AbnormalSummary` flag matched the dots of the app's calendar for each cat.
  - Most of those days had no abnormal visit. Their dots came from `AboveBaseline`, `Frequency`, or `IrregularDuration`.
    The day with an abnormal visit had `Event` set.
  - `AbnormalSummary` held only the Boolean keys `AboveBaseline`, `Event`, `Frequency`, and `IrregularDuration`.
  - The calendar returned every day since the first day with data, about 75 days before the check.
    The day list keeps only 31 days. A month before the first day with data returned no entries.
- The day list returns visits for today and the 30 days before it. An older day returns an empty list, although the cat summaries report 55 to 63 days of collected data.
- An invited account (`Role` 2) changed a poop visit of the owner to pee through `siipet.update_visit`.
  - The integration sent operation 3 with `{"Type": 3}`. The server returned `Code` 0.
  - The detail read of the owner account then showed the visit as pee, with `FecesError` true.
  - The Android app blocks the same edit for that account. See "Invited accounts".
- An independent AWS IoT Device SDK client subscribed at QoS 0 against the owner account and an invited account, for 4 cameras over the same 900-second window.
  - Each account saw 24 of 24 subscriptions granted and 8 of 8 gets accepted, with every field the integration reads present.
  - The invited account read the owner's shadows.
  - Three of the eight shadows sent 2 update documents in the window, and the other five sent none. Both accounts saw the same counts, because they watched the same cameras.
  - Neither connection saw an interruption.
  - `battery.SOC` was an integer on three cameras and a fraction on one.
  - `Data.IotCore.Endpoint` uses an `https://` scheme.
- An account that had only signed in with email codes got a password through `/api/v1/user/email/reset`,
  with a code from `send/trustworthy` and `Scene` 0. The call returned `Code` 0.
  A sign-in through `/api/v1/user/email/login` with that password then returned a token,
  and `/api/v1/user/device/sync` with that token returned `Code` 0.
- A password sign-in from a script ended the session of the phone app on the same account.
  The app showed its sign-in screen. This fits one active session per account.
- `/api/v1/user/email/login` answered `Code` 10003 "not register" for an account without a password
  and for an address without an account.
- The integration's own MQTT connection ran for 120 seconds against the owner account. It connected and reported a state for all 4 cameras. Its log held no serial number, shadow name, identity, or signed URL.
- After the deploy of the device state, the invited-account instance created the device state entities of all 4 cameras. The owner instance showed battery values for all 4 cameras, all online, privacy mode off, and update mode manual. One camera on external power reported `charging: true` at 99% battery, the first live sample with that value.
- Both instances ran the device state for 11 hours after a restart, through the planned reconnect before the IoT credentials expire.
  - On the invited-account instance, the connection that was open 11 hours after the restart had sent about 230 data segments. At one ping each minute and 8 shadow reads every 5 minutes, that count fits a start about 9 hours 50 minutes after the restart. The renewal margin ends at that time. The first connection no longer existed.
  - Neither instance logged a device state warning, and no device state entity became unavailable.
  - Both instances received the same battery change after the planned reconnect.
  - A planned reconnect writes no log line and keeps `connected_since` in the diagnostics, so the socket counters were the only evidence.

## Open questions

- Charging transitions, and behavior when a full battery is on external power.
- Battery reporting intervals and observed changes through MQTT `/update/documents`.
- Privacy and recording transitions, illumination code meanings, and configuration field units.
- Whether the iPhone uses the Android renewal condition.
- How renewal behaves near or after the encoded token expiration, and how long
  the previous token remains valid after renewal.
- History paging with `More` and `Track`.
- Camera paging and continuation request fields.
- Camera connection timestamp semantics and subscription code meanings.
- JOY1 online state transitions through `esp32.connected.status`, including reporting delays.
- Live video and device replay through the credentials in `AgoraAuth`.
- How long the calendar keeps days (the tested account had about 75 days of data), and its behavior with alternate timezone flags.
- Complete rules for the calendar abnormality summary flags.
- Live examples of unknown and pee events. Lingering visits occur in the day list.
- How the server answers op 2 with an empty `PetIds` list. A type edit of an unrecognized visit sends it. No such visit was available for the live check.
- Stool code edits other than `[0, 0]`, and the effect of `Manual`.
- Whether S3 removes the media of a deleted visit later.
- Complete meanings of stool and event abnormality codes.
- Access to recordings stored only on the device.
- Whether the server accepts operations 1 and 2, a memo edit, and a delete from an
  invited account. Operation 3 works (see Live checks). The answer decides whether
  an invited account can replace the owner account for all edits.
- Which envelope codes the server returns for an expired or invalid token. The
  app treats -2 and -4 as an ended session.
- Whether the server checks `x-device-os`. `iOS 27.0` works with both model prefixes.
- Whether an account allows more than one active session. The earlier -2 results
  came from the model header, so they do not answer this. A password sign-in
  from a script ended the session of the phone app (see Live checks).
- The envelope code for a wrong password on an account that has a password.
- Whether the server accepts one code for both `/api/v1/user/email/reset` and
  `/api/v1/user/email/register/login`.
- Whether the session of the phone app lasts longer than one hour after an
  email-code sign-in from Home Assistant.
- Whether a renewal ends the other session when Home Assistant and the phone app
  use the same token and `x-device-identifier`, in either direction.
