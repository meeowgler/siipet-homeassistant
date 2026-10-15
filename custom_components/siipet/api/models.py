"""Typed models for SiiPet API responses."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import IntEnum
import math
import re
from typing import Any, Final
from urllib.parse import urlsplit

# The two device shadows of a camera.
CONFIG_SHADOW: Final = "config"
SYSTEM_SHADOW: Final = "system"
SHADOW_KINDS: Final = (CONFIG_SHADOW, SYSTEM_SHADOW)


def _from_ms(value: Any) -> datetime | None:
    """Convert milliseconds since the Unix epoch to an aware datetime."""
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _media_key(media: Any) -> str | None:
    """Return the bucket key of a media object, or None."""
    if not isinstance(media, Mapping):
        return None
    return media.get("Url") or None


def _media_size(media: Any) -> int | None:
    """Return the positive byte size of a media object, or None."""
    if not isinstance(media, Mapping):
        return None
    try:
        size = int(media.get("Size") or 0)
    except TypeError, ValueError:
        return None
    return size if size > 0 else None


def _media_md5(media: Any) -> str | None:
    """Return the lowercase hex MD5 of a media object, or None."""
    if not isinstance(media, Mapping):
        return None
    value = str(media.get("Md5") or "").lower()
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else None


class VisitType(IntEnum):
    """Visit classification from the `Type` field of a visit."""

    UNKNOWN = 0
    LINGERING = 1
    POOP = 2
    PEE = 3

    @classmethod
    def from_api(cls, value: Any) -> VisitType:
        """Map an API value to a type. Values outside the enum map to UNKNOWN."""
        try:
            return cls(int(value))
        except TypeError, ValueError:
            return cls.UNKNOWN

    @property
    def key(self) -> str:
        """Lowercase name for entity states and event types."""
        return self.name.lower()

    @property
    def is_litter_use(self) -> bool:
        """True for pee and poop, the types that the calendar counts."""
        return self in (VisitType.POOP, VisitType.PEE)


@dataclass(frozen=True, slots=True)
class Cat:
    """A cat from `user/pet/sync`."""

    pet_id: str
    name: str
    avatar_key: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Cat:
        """Parse one entry of `Data.List`."""
        return cls(
            pet_id=str(data["PetId"]),
            name=str(data.get("Name") or ""),
            avatar_key=_media_key(data.get("avatar")),
        )


@dataclass(frozen=True, slots=True)
class CameraShadows:
    """The names of the two device shadows of a camera."""

    config: str = field(repr=False)
    system: str = field(repr=False)

    @classmethod
    def from_api(cls, topic: Any) -> CameraShadows | None:
        """Parse `Topic` of a camera. Return None without both shadow names."""
        shadow = topic.get("Shadow") if isinstance(topic, Mapping) else None
        if not isinstance(shadow, Mapping):
            return None
        names = (shadow.get("configInfo"), shadow.get("systemInfo"))
        if not all(isinstance(name, str) and name for name in names):
            return None
        return cls(config=str(names[0]), system=str(names[1]))

    def name(self, kind: str) -> str:
        """Return the shadow name for `CONFIG_SHADOW` or `SYSTEM_SHADOW`."""
        return self.config if kind == CONFIG_SHADOW else self.system


@dataclass(frozen=True, slots=True)
class Camera:
    """A camera from `user/device/sync`."""

    sn: str
    name: str
    product_id: str
    role: int
    subscription_expires: datetime | None
    shadows: CameraShadows | None = field(default=None, repr=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Camera:
        """Parse one entry of `Data.List`."""
        subscription = data.get("PurchaseSubscribe") or {}
        return cls(
            sn=str(data["SN"]),
            name=str(data.get("DeviceName") or data.get("ProductId") or "Camera"),
            product_id=str(data.get("ProductId") or ""),
            role=int(data.get("Role") or 0),
            subscription_expires=_from_ms(subscription.get("ExpireTime")),
            shadows=CameraShadows.from_api(data.get("Topic")),
        )


@dataclass(frozen=True, slots=True)
class Visit:
    """One litter box visit from `pet/toilet/event` or the event detail."""

    event_id: str
    sn: str
    pet_ids: tuple[str, ...]
    group_id: str
    start: datetime
    duration_ms: int
    type: VisitType
    note: str
    feces_abnormal: tuple[int | None, ...]
    event_abnormal: int
    cloud_stored: bool
    video_key: str | None
    cover_key: str | None
    stool_key: str | None
    video_size: int | None = None
    video_md5: str | None = None
    cover_size: int | None = None
    stool_size: int | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Visit:
        """Parse one visit. `PetIds` wins over `PetId` when both exist."""
        pet_ids = tuple(str(pet) for pet in data.get("PetIds") or () if pet)
        if not pet_ids and data.get("PetId"):
            pet_ids = (str(data["PetId"]),)
        video = data.get("ToiletVideo") or {}
        return cls(
            event_id=str(data["EventId"]),
            sn=str(data.get("SN") or ""),
            pet_ids=pet_ids,
            group_id=str(data.get("GroupId") or ""),
            start=_from_ms(data.get("EventTimestamp"))
            or datetime.fromtimestamp(0, UTC),
            duration_ms=int(data.get("Duration") or 0),
            type=VisitType.from_api(data.get("Type")),
            note=str(data.get("Note") or ""),
            feces_abnormal=tuple(
                None if code is None else int(code)
                for code in data.get("FecesAbnormal") or ()
            ),
            event_abnormal=int(data.get("EventAbnormal") or 0),
            cloud_stored=bool(data.get("CloudStorageStatus")),
            video_key=_media_key(video.get("RawInfo")),
            cover_key=_media_key(video.get("Cover")),
            stool_key=_media_key(data.get("FecesImage")),
            video_size=_media_size(video.get("RawInfo")),
            video_md5=_media_md5(video.get("RawInfo")),
            cover_size=_media_size(video.get("Cover")),
            stool_size=_media_size(data.get("FecesImage")),
        )

    @property
    def abnormal(self) -> bool:
        """Pee or poop with a positive stool code or a positive event code."""
        if not self.type.is_litter_use:
            return False
        if self.event_abnormal > 0:
            return True
        return any(code is not None and code > 0 for code in self.feces_abnormal)


@dataclass(frozen=True, slots=True)
class DaySummary:
    """One entry of `Data.TodaySummary`."""

    pet_id: str
    baseline_times: float
    baseline_avg_ms: float
    needed_days: int
    current_days: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> DaySummary:
        """Parse one summary entry."""
        return cls(
            pet_id=str(data["PetId"]),
            baseline_times=float(data.get("BaselineTimes") or 0),
            baseline_avg_ms=float(data.get("BaselineAvgTime") or 0),
            needed_days=int(data.get("NeededTotalDays") or 0),
            current_days=int(data.get("CurrentTotalDays") or 0),
        )


@dataclass(frozen=True, slots=True)
class DayVisits:
    """The visit list and the per-cat summaries of one day."""

    visits: tuple[Visit, ...]
    summaries: Mapping[str, DaySummary]
    more: bool

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> DayVisits:
        """Parse `Data` of `pet/toilet/event`."""
        summaries = (
            DaySummary.from_api(item) for item in data.get("TodaySummary") or ()
        )
        return cls(
            visits=tuple(Visit.from_api(item) for item in data.get("List") or ()),
            summaries={summary.pet_id: summary for summary in summaries},
            more=bool(data.get("More")),
        )


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """One day of `pet/toilet/data/calendar` for one cat."""

    date: date
    normal: int
    abnormal: int
    normal_ms: int
    abnormal_ms: int
    flagged: bool

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> CalendarDay:
        """Parse one entry of `Data.DataCalendar`."""
        summary = data.get("AbnormalSummary") or {}
        return cls(
            date=date.fromisoformat(data["Date"]),
            normal=int(data.get("Normal") or 0),
            abnormal=int(data.get("Abnormal") or 0),
            normal_ms=int(data.get("NormalDuration") or 0),
            abnormal_ms=int(data.get("AbnormalDuration") or 0),
            flagged=any(value is True for value in summary.values()),
        )


@dataclass(frozen=True, slots=True)
class AbnormalLabels:
    """Titles for abnormal codes from `Data.Memory.AbnormalToilet`."""

    shape: Mapping[int, str] = field(default_factory=dict)
    color: Mapping[int, str] = field(default_factory=dict)
    event: Mapping[int, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> AbnormalLabels:
        """Parse `Data` of `config/system/config`. Code 0 means normal and is skipped."""
        groups: dict[str, dict[int, str]] = {"Shape": {}, "Color": {}, "Event": {}}
        for entry in (data.get("Memory") or {}).get("AbnormalToilet") or ():
            for group, labels in groups.items():
                for item in entry.get(group) or ():
                    code = int(item.get("Type") or 0)
                    title = str(item.get("Title") or "").strip()
                    if code > 0 and title:
                        labels[code] = title
        return cls(shape=groups["Shape"], color=groups["Color"], event=groups["Event"])

    def reasons(self, visit: Visit) -> list[str]:
        """Titles for the positive codes of an abnormal visit."""
        if not visit.abnormal:
            return []
        reasons: list[str] = []
        for index, code in enumerate(visit.feces_abnormal):
            if code is None or code <= 0:
                continue
            labels = self.shape if index == 0 else self.color
            reasons.append(labels.get(code, str(code)))
        if visit.event_abnormal > 0:
            reasons.append(
                self.event.get(visit.event_abnormal, str(visit.event_abnormal))
            )
        return reasons


@dataclass(frozen=True, slots=True)
class MediaCredentials:
    """Temporary S3 credentials from `Data.S3` of `config/aws/auth`."""

    bucket: str = field(repr=False)
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    session_token: str = field(repr=False)
    expires: datetime

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MediaCredentials:
        """Parse `Data` of `config/aws/auth`."""
        s3 = data["S3"]
        expires = _from_ms(s3["ExpireTime"])
        if expires is None:
            raise ValueError("The media credentials have no expiry")
        return cls(
            bucket=str(s3["S3Bucket"]),
            access_key_id=str(s3["AccessKeyId"]),
            secret_access_key=str(s3["SecretAccessKey"]),
            session_token=str(s3["SessionToken"]),
            expires=expires,
        )


def _iot_host(endpoint: str) -> str:
    """Return the host of `IotCore.Endpoint`, which carries an https scheme."""
    host = urlsplit(endpoint).hostname if "://" in endpoint else endpoint
    if not host or "/" in host:
        raise ValueError("The IoT endpoint has no host")
    return host.lower()


def _iot_region(host: str) -> str:
    """Return the region of an AWS IoT data endpoint host."""
    parts = host.split(".")
    if len(parts) < 5 or parts[-4] != "iot" or parts[-2:] != ["amazonaws", "com"]:
        raise ValueError("The IoT endpoint has no region")
    return parts[-3]


@dataclass(frozen=True, slots=True)
class IotCredentials:
    """Temporary AWS IoT credentials from `Data.IotCore` of `config/aws/auth`."""

    endpoint: str = field(repr=False)
    region: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    session_token: str = field(repr=False)
    identity_id: str = field(repr=False)
    expires: datetime

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> IotCredentials:
        """Parse `Data` of `config/aws/auth`."""
        iot = data["IotCore"]
        host = _iot_host(str(iot["Endpoint"]))
        expires = _from_ms(iot["ExpireTime"])
        if expires is None:
            raise ValueError("The IoT credentials have no expiry")
        identity_id = str(data["IdentityId"])
        if not identity_id:
            raise ValueError("The IoT credentials have no identity")
        return cls(
            endpoint=host,
            region=_iot_region(host),
            access_key_id=str(iot["AccessKeyId"]),
            secret_access_key=str(iot["SecretAccessKey"]),
            session_token=str(iot["SessionToken"]),
            identity_id=identity_id,
            expires=expires,
        )


def _dig(data: Any, path: Sequence[str]) -> Any:
    """Return the value at `path` in nested mappings, or None."""
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_percent(value: Any) -> int | None:
    """Round a battery reading half up, like the app. Reject bools, NaN, infinity."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return math.floor(value + 0.5) if math.isfinite(value) else None


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


# For each shadow: DeviceState field -> (path under `state.reported`, converter).
_SHADOW_FIELDS: Final[
    Mapping[str, Mapping[str, tuple[tuple[str, ...], Callable[[Any], Any]]]]
] = {
    CONFIG_SHADOW: {
        "battery": (("battery", "SOC"), _as_percent),
        "charging": (("battery", "charging"), _as_bool),
        "privacy": (("privacyMode", "active"), _as_bool),
        "fill_light": (("fillLight", "level"), _as_int),
        "fill_light_auto": (("fillLight", "autoLight"), _as_bool),
        "fill_light_low": (("fillLight", "lowLight"), _as_bool),
        "fill_light_brightness": (("fillLight", "brightness2"), _as_int),
        "motion_level": (("pir", "level"), _as_int),
        "update_mode": (("otaMode", "mode"), _as_int),
        "cloud_storage": (("cloudMode", "enableCloud"), _as_bool),
    },
    SYSTEM_SHADOW: {
        "online": (("esp32", "connected", "status"), _as_bool),
        "firmware": (("main", "sysVersion"), _as_text),
        "rssi": (("main", "rssi"), _as_int),
    },
}


@dataclass(frozen=True, slots=True)
class ShadowPart:
    """The fields that the integration reads from one shadow document."""

    values: Mapping[str, Any]
    reported_at: datetime | None
    version: int | None


def parse_shadow(kind: str, message: Any) -> ShadowPart | None:
    """Read a shadow document from `/get/accepted` or `/update/documents`.

    Return None when the message has no `state.reported` object.
    """
    if not isinstance(message, Mapping):
        return None
    document = message.get("current", message)
    reported = _dig(document, ("state", "reported"))
    if not isinstance(reported, Mapping):
        return None
    metadata = _dig(document, ("metadata", "reported"))
    values: dict[str, Any] = {}
    stamps: list[int] = []
    for name, (path, convert) in _SHADOW_FIELDS[kind].items():
        values[name] = convert(_dig(reported, path))
        stamp = _as_int(_dig(metadata, (*path, "timestamp")))
        if stamp is not None and stamp > 0:
            stamps.append(stamp)
    return ShadowPart(
        values=values,
        reported_at=datetime.fromtimestamp(max(stamps), tz=UTC) if stamps else None,
        version=_as_int(document.get("version")),
    )


@dataclass(frozen=True, slots=True)
class DeviceState:
    """The device state of one camera, from both of its shadows."""

    battery: int | None = None
    charging: bool | None = None
    privacy: bool | None = None
    fill_light: int | None = None
    fill_light_auto: bool | None = None
    fill_light_low: bool | None = None
    fill_light_brightness: int | None = None
    motion_level: int | None = None
    update_mode: int | None = None
    cloud_storage: bool | None = None
    online: bool | None = None
    firmware: str | None = None
    rssi: int | None = None
    reported_at: datetime | None = None

    @classmethod
    def from_parts(
        cls, config: ShadowPart | None, system: ShadowPart | None
    ) -> DeviceState:
        """Merge the parts of both shadows. A missing part leaves its fields None."""
        parts = [part for part in (config, system) if part is not None]
        values = {name: value for part in parts for name, value in part.values.items()}
        stamps = [part.reported_at for part in parts if part.reported_at is not None]
        return cls(**values, reported_at=max(stamps) if stamps else None)
