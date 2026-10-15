"""Constants for the SiiPet integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "siipet"

CONF_AUTH_METHOD: Final = "auth_method"
CONF_CLIENT_ID: Final = "client_id"
CONF_CODE: Final = "code"
CONF_EXPIRE_AT: Final = "expire_at"
CONF_MEDIA_DAYS: Final = "media_days"
CONF_NEW_PASSWORD: Final = "new_password"
CONF_TOKEN: Final = "token"
# The keys that an entry needs to sign in. Entries from version 0.0.1 have none.
SESSION_KEYS: Final = (CONF_TOKEN, CONF_EXPIRE_AT, CONF_CLIENT_ID)

DEFAULT_MEDIA_DAYS: Final = 7
MAX_MEDIA_DAYS: Final = 30
# A dot folder, so that the local media browser does not list it.
MEDIA_FOLDER: Final = ".siipet"

AUTH_EMAIL: Final = "email"
AUTH_PASSWORD: Final = "password"
AUTH_TOKEN: Final = "token"

MANUFACTURER: Final = "SiiPet"
CAT_MODEL: Final = "Cat"
UNKNOWN_CAT_ID: Final = "unknown"
UNKNOWN_CAT_NAME: Final = "Unknown cat"

UPDATE_INTERVAL: Final = timedelta(minutes=5)
SYNC_INTERVAL: Final = timedelta(hours=1)
PAST_DAY_INTERVAL: Final = timedelta(hours=1)
LABELS_INTERVAL: Final = timedelta(hours=24)
MIDNIGHT_GRACE: Final = timedelta(hours=1)
WINDOW_DAYS: Final = 7
# How long the device state entities keep their values without a connection.
DEVICE_STATE_GRACE: Final = timedelta(minutes=15)
