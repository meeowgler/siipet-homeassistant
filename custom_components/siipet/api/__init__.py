"""Client for the SiiPet cloud API. This package has no Home Assistant imports."""

from .auth import Session, hash_password
from .client import SiiPetClient
from .errors import (
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetConnectionError,
    SiiPetError,
)
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
    "MediaCredentials",
    "Session",
    "SiiPetApiError",
    "SiiPetAuthError",
    "SiiPetClient",
    "SiiPetConnectionError",
    "SiiPetError",
    "Visit",
    "VisitType",
    "hash_password",
]
