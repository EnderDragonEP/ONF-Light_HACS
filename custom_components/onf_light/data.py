"""Runtime data shared between the ONF Light platforms."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .ble_client import ONFLightBLEClient
    from .coordinator import ONFLightDiagnosticCoordinator
    from .light import ONFLightEntity


@dataclass
class ONFLightData:
    """Objects owned by one config entry, stored in entry.runtime_data."""

    client: ONFLightBLEClient
    coordinator: ONFLightDiagnosticCoordinator
    diagnostics: dict[str, Any] = field(default_factory=dict)
    entity: ONFLightEntity | None = None


type ONFLightConfigEntry = ConfigEntry[ONFLightData]
