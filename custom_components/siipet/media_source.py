"""Media source for SiiPet cloud recordings and visit images."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaImage,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import Visit
from .const import DOMAIN, UNKNOWN_CAT_NAME
from .coordinator import SiiPetData
from .media import MediaError, MediaKind, SiiPetMedia
from .views import image_path

BROWSE_DAYS = 30


async def async_get_media_source(hass: HomeAssistant) -> SiiPetMediaSource:
    """Return the SiiPet media source."""
    return SiiPetMediaSource(hass)


def visit_title(data: SiiPetData, visit: Visit) -> str:
    """Return `HH:MM <cats> - <Type> (<m:ss>)` for a visit."""
    names = [
        data.cats[cat_id].name for cat_id in data.cat_ids(visit) if cat_id in data.cats
    ] or [UNKNOWN_CAT_NAME]
    minutes, seconds = divmod(round(visit.duration_ms / 1000), 60)
    start = dt_util.as_local(visit.start)
    title = (
        f"{start:%H:%M} {', '.join(names)} - {visit.type.key.capitalize()} "
        f"({minutes}:{seconds:02d})"
    )
    if not visit.cloud_stored:
        title += " (on camera only)"
    return title


class SiiPetMediaSource(MediaSource):
    """Browse and play the cloud recordings of SiiPet visits, and read their images."""

    name = "SiiPet"

    def __init__(self, hass: HomeAssistant) -> None:
        """Create the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    def _media(self) -> SiiPetMedia | None:
        entries = self.hass.config_entries.async_loaded_entries(DOMAIN)
        return entries[0].runtime_data.media if entries else None

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a recording to a signed URL, and an image to the image view."""
        media = self._media()
        if media is None:
            raise Unresolvable("SiiPet is not loaded")
        # The root has no identifier.
        kind, _, item_id = (item.identifier or "").partition("/")
        if not item_id:
            raise Unresolvable("Unknown SiiPet media item")
        try:
            if kind == "visit":
                return PlayMedia(await media.async_video_url(item_id), "video/mp4")
            try:
                image_kind = MediaKind(kind)
            except ValueError:
                raise Unresolvable("Unknown SiiPet media item") from None
            await media.async_image_key(image_kind, item_id)
        except MediaError as err:
            raise Unresolvable(str(err)) from err
        return PlayMedia(image_path(image_kind, item_id), "image/jpeg")

    async def async_get_media_image(self, item: MediaSourceItem) -> MediaImage | None:
        """Return the bytes of an image, so that AI Task can attach it.

        A recording, a folder, and an unknown item have no single image.
        """
        # The root has no identifier.
        kind, _, item_id = (item.identifier or "").partition("/")
        try:
            image_kind = MediaKind(kind)
        except ValueError:
            return None
        if not item_id:
            return None
        media = self._media()
        if media is None:
            raise Unresolvable("SiiPet is not loaded")
        try:
            content = await media.async_read_image(image_kind, item_id)
        except MediaError as err:
            raise Unresolvable(str(err)) from err
        return MediaImage(content=content, mime_type="image/jpeg")

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse the last 30 days, then the visits of one day."""
        media = self._media()
        if media is None:
            raise BrowseError("SiiPet is not loaded")
        if not item.identifier:
            return self._browse_root(media)
        kind, _, value = item.identifier.partition("/")
        try:
            day = date.fromisoformat(value) if kind == "day" else None
        except ValueError:
            day = None
        if day is None:
            raise BrowseError("Unknown SiiPet folder")
        try:
            visits = await media.async_day_visits(day)
        except MediaError as err:
            raise BrowseError(str(err)) from err
        data = media.coordinator.data
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=item.identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=day.isoformat(),
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.VIDEO,
            children=[_visit_item(data, visit) for visit in visits],
        )

    def _browse_root(self, media: SiiPetMedia) -> BrowseMediaSource:
        today = media.coordinator.data.today
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title="SiiPet",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                _day_folder(today - timedelta(days=offset))
                for offset in range(BROWSE_DAYS)
            ],
        )


def _day_folder(day: date) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=f"day/{day.isoformat()}",
        media_class=MediaClass.DIRECTORY,
        media_content_type="",
        title=day.isoformat(),
        can_play=False,
        can_expand=True,
    )


def _visit_item(data: SiiPetData, visit: Visit) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=f"visit/{visit.event_id}",
        media_class=MediaClass.VIDEO,
        media_content_type="video/mp4",
        title=visit_title(data, visit),
        can_play=visit.cloud_stored and visit.video_key is not None,
        can_expand=False,
        thumbnail=(
            image_path(MediaKind.COVER, visit.event_id) if visit.cover_key else None
        ),
    )
