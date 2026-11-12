"""Client for the SiiPet cloud API. This package has no Home Assistant imports."""

from .auth import Session, hash_password
from .client import SiiPetClient
from .errors import (
    LrtmError,
    LrtmServerError,
    LrtmTransportError,
    LrtmUnconfirmedError,
    SettingUnavailableError,
    ShadowWriteError,
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetConnectionError,
    SiiPetError,
)
from .lrtm import LrtmClient
from .models import (
    AbnormalLabels,
    CalendarDay,
    Camera,
    CameraShadows,
    Cat,
    DaySummary,
    DayVisits,
    DeviceSettings,
    DeviceState,
    FeatureRules,
    IotCredentials,
    MediaCredentials,
    Visit,
    VisitType,
)

__all__ = [
    "AbnormalLabels",
    "CalendarDay",
    "Camera",
    "CameraShadows",
    "Cat",
    "DaySummary",
    "DayVisits",
    "DeviceSettings",
    "DeviceState",
    "FeatureRules",
    "IotCredentials",
    "LrtmClient",
    "LrtmError",
    "LrtmServerError",
    "LrtmTransportError",
    "LrtmUnconfirmedError",
    "MediaCredentials",
    "Session",
    "SettingUnavailableError",
    "ShadowWriteError",
    "SiiPetApiError",
    "SiiPetAuthError",
    "SiiPetClient",
    "SiiPetConnectionError",
    "SiiPetError",
    "Visit",
    "VisitType",
    "hash_password",
]
