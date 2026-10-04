# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/eversolar-pmu-ha

"""Shared base entity for Eversolar PMU."""
from typing import Any, Optional

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EversolarDataUpdateCoordinator


class EversolarEntity(CoordinatorEntity):
    """Base class: one entity belonging to one inverter behind a PMU."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EversolarDataUpdateCoordinator,
        inverter_id: str,
        key: str,
    ) -> None:
        """Initialize entity."""
        super().__init__(coordinator)
        self._inverter_id = inverter_id
        self._attr_unique_id = f"{DOMAIN}_{inverter_id}_{key}"

    @property
    def inverter_data(self) -> Optional[dict[str, Any]]:
        """Latest readings for this inverter (None if the PMU did not report it)."""
        return self.coordinator.inverter_data(self._inverter_id)

    @property
    def available(self) -> bool:
        """Unavailable when the PMU update failed or this inverter is not reported."""
        return super().available and self.inverter_data is not None

    @property
    def device_info(self) -> dict:
        """Return device info (one device per inverter)."""
        return {
            "identifiers": {(DOMAIN, self._inverter_id)},
            "name": f"Eversolar Inverter {self._inverter_id}",
            "manufacturer": "Eversolar",
            "model": "PMU (TCP/IP)",
        }
