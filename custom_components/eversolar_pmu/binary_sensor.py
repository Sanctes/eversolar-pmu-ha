# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/eversolar-pmu-ha

"""Binary sensor platform for Eversolar PMU."""
import logging
from typing import Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EversolarDataUpdateCoordinator
from .entity import EversolarEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor platform from a config entry."""
    coordinator: EversolarDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new_inverters() -> None:
        """Add entities for inverters not seen before (also handles late arrivals)."""
        new_ids = [i for i in coordinator.inverter_ids if i not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            [
                entity
                for i in new_ids
                for entity in (
                    EversolarACDCOfflineSensor(coordinator, i),
                    EversolarTimeSyncSensor(coordinator, i),
                )
            ]
        )

    _add_new_inverters()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_inverters))


class EversolarACDCOfflineSensor(EversolarEntity, BinarySensorEntity):
    """DC Online binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_name = "DC Online"

    def __init__(self, coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, "dc_online")

    @property
    def is_on(self) -> Optional[bool]:
        """Return True if DC is online (inverter not fully down)."""
        return not self.coordinator.is_fully_down(self._inverter_id)


class EversolarTimeSyncSensor(EversolarEntity, BinarySensorEntity):
    """Time Sync binary sensor.

    Time sync is a PMU-wide operation, so every inverter reports the same state.
    """

    _attr_name = "Time Sync"

    def __init__(self, coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, "time_sync")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        # Unavailable when both AC and DC are down (fully down)
        if self.coordinator.is_fully_down(self._inverter_id):
            return False
        return True

    @property
    def is_on(self) -> bool:
        """Return True if time sync was successful."""
        return self.coordinator.time_sync_success
