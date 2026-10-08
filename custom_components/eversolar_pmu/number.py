# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/eversolar-pmu-ha

"""Number platform for Eversolar PMU."""
import logging
from typing import Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PV_VOLTAGE_STATS_CUTOFF, DOMAIN
from .coordinator import EversolarDataUpdateCoordinator
from .entity import EversolarEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number platform from a config entry."""
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
            [EversolarPVVoltageStatsCutoffNumber(hass, coordinator, entry, i) for i in new_ids]
        )

    _add_new_inverters()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_inverters))


class EversolarPVVoltageStatsCutoffNumber(EversolarEntity, NumberEntity):
    """PV Voltage Stats Cutoff number entity.

    The cutoff is one option shared by all inverters on the PMU, so every
    inverter's entity reads and writes the same value.
    """

    _attr_name = "PV Voltage Stats Cutoff"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 200
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "V"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EversolarDataUpdateCoordinator,
        entry: ConfigEntry,
        inverter_id: str,
    ) -> None:
        """Initialize number entity."""
        super().__init__(coordinator, inverter_id, "pv_voltage_stats_cutoff")
        self.hass = hass
        self.config_entry = entry

    @property
    def native_value(self) -> Optional[float]:
        """Return the current PV voltage stats cutoff."""
        return float(self.coordinator._get_config(CONF_PV_VOLTAGE_STATS_CUTOFF, 20))

    async def async_set_native_value(self, value: float) -> None:
        """Set PV voltage stats cutoff."""
        # Create a new options dict with the updated value
        new_options = dict(self.config_entry.options)
        new_options[CONF_PV_VOLTAGE_STATS_CUTOFF] = int(value)

        # Update the config entry options using Home Assistant API
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options=new_options,
        )

        # Update UI state
        self.async_write_ha_state()
