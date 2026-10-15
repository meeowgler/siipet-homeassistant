"""Client for the SiiPet cloud API. This package has no Home Assistant imports."""

from .auth import Session
from .client import SiiPetClient
from .errors import (
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetConnectionError,
    SiiPetError,
)
from .lrtm import LrtmControl, LrtmError
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
    "MediaCredentials",
    "Session",
    "SiiPetApiError",
    "SiiPetAuthError",
    "SiiPetClient",
    "SiiPetConnectionError",
    "SiiPetError",
    "Visit",
    "VisitType",
]
