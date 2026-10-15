"""The SiiPet integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import LrtmControl, Session, SiiPetClient
from .api.s3 import S3Signer
from .calendar_data import SiiPetCalendar
from .card import async_register_card
from .const import (
    CONF_CLIENT_ID,
    CONF_EXPIRE_AT,
    CONF_MEDIA_DAYS,
    CONF_TOKEN,
    DEFAULT_MEDIA_DAYS,
    DOMAIN,
    SESSION_KEYS,
    UNKNOWN_CAT_ID,
)
from .coordinator import SiiPetConfigEntry, SiiPetCoordinator, SiiPetRuntime
from .device_state import SiiPetDeviceCoordinator
from .media import SiiPetMedia
from .media_mirror import (
    ISSUE_FOLDER,
    SiiPetMirror,
    async_clear_issues,
    async_raise_issue,
)
from .media_store import MediaStore, MediaStoreError, async_delete_folder, media_root
from .services import async_setup_services
from .views import SiiPetImageView, SiiPetRecordingView
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the image and recording views, the actions, the card commands, and the card."""
    hass.http.register_view(SiiPetImageView(hass))
    hass.http.register_view(SiiPetRecordingView(hass))
    async_setup_services(hass)
    async_setup_websocket_api(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SiiPetConfigEntry) -> bool:
    """Set up SiiPet from a config entry."""
    if any(key not in entry.data for key in SESSION_KEYS):
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="entry_outdated"
        )

    @callback
    def _async_save_session(session: Session) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TOKEN: session.token,
                CONF_EXPIRE_AT: session.expire_at,
            },
        )

    client = SiiPetClient(
        async_get_clientsession(hass),
        client_id=entry.data[CONF_CLIENT_ID],
        time_zone=str(hass.config.time_zone),
        session=Session(entry.data[CONF_TOKEN], entry.data[CONF_EXPIRE_AT]),
        on_session_update=_async_save_session,
    )
    control = LrtmControl(async_get_clientsession(hass), lambda: client.session)
    coordinator = SiiPetCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    media = SiiPetMedia(
        hass, coordinator, client, S3Signer(client.get_media_credentials)
    )
    device_state = SiiPetDeviceCoordinator(hass, entry, coordinator, client)
    entry.runtime_data = SiiPetRuntime(
        client=client,
        control=control,
        coordinator=coordinator,
        media=media,
        calendar=SiiPetCalendar(client),
        device_state=device_state,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    device_state.async_start()
    entry.runtime_data.mirror = await _async_start_mirror(hass, entry)
    return True


async def _async_start_mirror(
    hass: HomeAssistant, entry: SiiPetConfigEntry
) -> SiiPetMirror | None:
    """Start the local media copy, or delete it when the option is 0 days."""
    days = entry.options.get(CONF_MEDIA_DAYS, DEFAULT_MEDIA_DAYS)
    root = media_root(hass)
    if not days:
        async_clear_issues(hass)
        if root is not None:
            await async_delete_folder(hass, root)
        return None
    try:
        if root is None:
            raise MediaStoreError("Home Assistant has no local media folder")
        store = MediaStore(hass, root)
        await store.async_load()
    except MediaStoreError as err:
        _LOGGER.warning("SiiPet cannot keep a local media copy: %s", err)
        async_raise_issue(hass, ISSUE_FOLDER)
        return None
    async_clear_issues(hass)
    runtime = entry.runtime_data
    runtime.media.store = store
    mirror = SiiPetMirror(hass, entry, runtime.coordinator, runtime.media, store, days)
    await mirror.async_start()
    return mirror


async def async_unload_entry(hass: HomeAssistant, entry: SiiPetConfigEntry) -> bool:
    """Unload a SiiPet config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SiiPetConfigEntry) -> None:
    """Delete the local media copy of a removed entry."""
    async_clear_issues(hass)
    if (root := media_root(hass)) is not None:
        await async_delete_folder(hass, root)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SiiPetConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removal of a cat or camera device that the account no longer has.

    Without a loaded entry there is no current data, so nothing is removable.
    """
    if entry.state is not ConfigEntryState.LOADED:
        return False
    data = entry.runtime_data.coordinator.data
    current = {UNKNOWN_CAT_ID, *data.cats, *data.cameras}
    return not any(
        domain == DOMAIN and identifier in current
        for domain, identifier in device_entry.identifiers
    )
