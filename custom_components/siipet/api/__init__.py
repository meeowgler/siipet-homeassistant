"""Client for the SiiPet cloud API. This package has no Home Assistant imports."""

from .auth import Session, hash_password
from .client import SiiPetClient
from .errors import (
    LrtmError,
    LrtmServerError,
    LrtmTransportError,
    SettingUnavailableError,
    ShadowWriteError,
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetConnectionError,
    SiiPetError,
)
from .lrtm import LrtmControl
from .models import (
    AbnormalLabels,
    CalendarDay,
    Camera,
    CameraShadows,
    Cat,
    DaySummary,
    DayVisits,
    DeviceState,
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
    "DeviceState",
    "IotCredentials",
    "LrtmControl",
    "LrtmError",
    "LrtmServerError",
    "LrtmTransportError",
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
