# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/eversolar-pmu-ha

"""Sensor platform for Eversolar PMU."""
import logging
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    EntityCategory,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_INVERTER_ID,
    ATTR_MODE,
    ATTR_PMU_EPOCH,
    ATTR_PMU_EPOCH_STEP,
    ATTR_PMU_TIME_STUCK,
    ATTR_PMU_TIME_UTC,
    DOMAIN,
    ERROR_MESSAGES,
    SENSOR_ENERGY_TODAY,
    SENSOR_ENERGY_TOTAL,
    SENSOR_FREQUENCY,
    SENSOR_HOURS_TOTAL,
    SENSOR_POWER,
    SENSOR_PV_CURRENT,
    SENSOR_PV_POWER,
    SENSOR_PV_VOLTAGE,
    SENSOR_VOLTAGE,
)
from .coordinator import EversolarDataUpdateCoordinator
from .entity import EversolarEntity

_LOGGER = logging.getLogger(__name__)


def _inverter_entities(coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> list:
    """Build the sensor entities for one inverter."""
    c, i = coordinator, inverter_id
    return [
        EversolarSensor(c, i, SENSOR_POWER, "Power", "power_w",
                        SensorDeviceClass.POWER, "W", SensorStateClass.MEASUREMENT),
        EversolarSensor(c, i, SENSOR_VOLTAGE, "AC Voltage", "vac_v",
                        SensorDeviceClass.VOLTAGE, "V", SensorStateClass.MEASUREMENT),
        EversolarSensor(c, i, SENSOR_FREQUENCY, "AC Frequency", "fac_hz",
                        SensorDeviceClass.FREQUENCY, "Hz", SensorStateClass.MEASUREMENT),
        EversolarSensor(c, i, SENSOR_ENERGY_TODAY, "Energy Today", "e_today_kwh",
                        SensorDeviceClass.ENERGY, "kWh", SensorStateClass.TOTAL_INCREASING),
        EversolarSensor(c, i, SENSOR_ENERGY_TOTAL, "Total Energy", "e_total_kwh",
                        SensorDeviceClass.ENERGY, "kWh", SensorStateClass.TOTAL_INCREASING),
        EversolarSensor(c, i, SENSOR_HOURS_TOTAL, "Total Operation Hours", "h_total_hours",
                        None, "h", SensorStateClass.TOTAL_INCREASING),
        EversolarSensor(c, i, SENSOR_PV_VOLTAGE, "PV Voltage", "pv_v",
                        SensorDeviceClass.VOLTAGE, "V", SensorStateClass.MEASUREMENT),
        EversolarSensor(c, i, SENSOR_PV_CURRENT, "PV Current", "pv_a",
                        SensorDeviceClass.CURRENT, "A", SensorStateClass.MEASUREMENT),
        EversolarSensor(c, i, SENSOR_PV_POWER, "PV Power", "pv_w_est",
                        SensorDeviceClass.POWER, "W", SensorStateClass.MEASUREMENT),
        EversolarTimestampSensor(c, i, "ac_online_time", "AC Online Time"),
        EversolarTimestampSensor(c, i, "ac_offline_time", "AC Offline Time"),
        EversolarOperationModeSensor(c, i),
        EversolarErrorMessageSensor(c, i),
        EversolarDailyEfficiencySensor(c, i),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform from a config entry."""
    coordinator: EversolarDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new_inverters() -> None:
        """Add entities for inverters not seen before (also handles late arrivals)."""
        new_ids = [i for i in coordinator.inverter_ids if i not in known]
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities([e for i in new_ids for e in _inverter_entities(coordinator, i)])

    _add_new_inverters()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_inverters))


class EversolarSensor(EversolarEntity, SensorEntity):
    """Representation of an Eversolar sensor."""

    def __init__(
        self,
        coordinator: EversolarDataUpdateCoordinator,
        inverter_id: str,
        sensor_type: str,
        name: str,
        data_key: str,
        device_class: Optional[SensorDeviceClass],
        unit: str,
        state_class: SensorStateClass,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, sensor_type)
        self._sensor_type = sensor_type
        self._data_key = data_key

        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Coordinator unavailable, or this inverter not reported by the PMU
        return super().available:
        if not super().available:
            return False

        # If inverter is fully down, mark power-related sensors as unavailable
        if self.coordinator.is_fully_down(self._inverter_id):
            unavailable_types = {
                SENSOR_POWER,
                SENSOR_VOLTAGE,
                SENSOR_FREQUENCY,
                SENSOR_ENERGY_TODAY,
                SENSOR_PV_VOLTAGE,
                SENSOR_PV_CURRENT,
                SENSOR_PV_POWER,
            }
            if self._sensor_type in unavailable_types:
                return False

        # If PV voltage is below stats cutoff, mark statistics as unreliable
        if self.coordinator.is_below_stats_cutoff(self._inverter_id):
            stats_types = {
                SENSOR_ENERGY_TODAY,
                SENSOR_ENERGY_TOTAL,
                SENSOR_HOURS_TOTAL,
                SENSOR_POWER,
                SENSOR_PV_POWER,
            }
            if self._sensor_type in stats_types:
                return False

        return True

    @property
    def native_value(self) -> Optional[Any]:
        """Return the state of the sensor."""
        data = self.inverter_data
        if not data:
            return None
        return data.get(self._data_key)


class EversolarDiagnosticSensor(EversolarSensor):
    """Diagnostic sensor with additional attributes."""

    _attr_entity_registry_enabled_default = True

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        data = self.inverter_data
        if not data:
            return {}

        attrs = {ATTR_INVERTER_ID: self._inverter_id}
        if ATTR_MODE in data:
            attrs[ATTR_MODE] = data.get("mode")
        if data.get("pmu_time_utc"):
            attrs[ATTR_PMU_TIME_UTC] = data.get("pmu_time_utc")
        if data.get("pmu_epoch") is not None:
            attrs[ATTR_PMU_EPOCH] = data.get("pmu_epoch")
        if data.get("pmu_epoch_step") is not None:
            attrs[ATTR_PMU_EPOCH_STEP] = data.get("pmu_epoch_step")
        if data.get("pmu_time_stuck") is not None:
            attrs[ATTR_PMU_TIME_STUCK] = data.get("pmu_time_stuck")

        return attrs


class EversolarTimestampSensor(EversolarEntity, SensorEntity):
    """AC online/offline timestamp sensor."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: EversolarDataUpdateCoordinator,
        inverter_id: str,
        data_key: str,
        name: str,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, data_key)
        self._data_key = data_key
        self._attr_name = name

    @property
    def native_value(self) -> Optional[Any]:
        """Return the timestamp (a timezone-aware datetime)."""
        data = self.inverter_data
        if not data:
            return None
        return data.get(self._data_key)


class EversolarOperationModeSensor(EversolarEntity, SensorEntity):
    """Operation Mode sensor."""

    _attr_name = "Operation Mode"

    def __init__(self, coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, "operation_mode")

    @property
    def native_value(self) -> Optional[str]:
        """Return the operation mode state."""
        data = self.inverter_data
        if not data:
            return None
        mode = data.get("mode")
        if mode is None:
            return None

        mode_map = {
            0x0000: "Wait",
            0x0001: "Normal",
            0x0002: "Fault",
            0x0003: "Permanent Fault",
        }
        return mode_map.get(mode, "Unknown")


class EversolarErrorMessageSensor(EversolarEntity, SensorEntity):
    """Error Message Bit Flags sensor."""

    _attr_name = "Error Messages"

    def __init__(self, coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, "error_messages")

    @property
    def native_value(self) -> Optional[str]:
        """Return the active error messages."""
        data = self.inverter_data
        if not data:
            return None
        error_flags = data.get("error_flags")
        if error_flags is None:
            return "No errors"

        if error_flags == 0:
            return "No errors"

        active_errors = []
        for bit_pos, error_name in ERROR_MESSAGES.items():
            if error_flags & (1 << bit_pos):
                active_errors.append(error_name)

        if not active_errors:
            return "No errors"

        return ", ".join(active_errors)

    @property
    def extra_state_attributes(self) -> dict:
        """Return error flags as attributes."""
        data = self.inverter_data
        if not data:
            return {}

        error_flags = data.get("error_flags")
        if error_flags is None:
            return {}

        attrs = {
            "error_flags_hex": f"0x{error_flags:08x}",
            "error_flags_int": error_flags,
        }

        # Add individual bit states
        for bit_pos, error_name in ERROR_MESSAGES.items():
            is_active = bool(error_flags & (1 << bit_pos))
            attrs[f"bit_{bit_pos}_{error_name.lower().replace('-', '_')}"] = is_active

        return attrs


class EversolarDailyEfficiencySensor(EversolarEntity, SensorEntity):
    """Daily Efficiency sensor."""

    _attr_name = "Daily Efficiency"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EversolarDataUpdateCoordinator, inverter_id: str) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, inverter_id, "daily_efficiency")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
       # return super().available
        if not super().available:
            return False
        # Available only if both energy and power data exist
        data = self.inverter_data
        if not data:
            return False
        energy = data.get("e_today_kwh")
        power = data.get("pv_w_est")
        return energy is not None and power is not None and power > 0

    @property
    def native_value(self) -> Optional[float]:
        """Return the daily efficiency percentage."""
        data = self.inverter_data
        if not data:
            return None

        energy_kwh = data.get("e_today_kwh")
        power_w = data.get("pv_w_est")

        if energy_kwh is None or power_w is None or power_w <= 0:
            return None

        # efficiency = (energy_kwh / 24 / (power_w / 1000)) * 100
        try:
            efficiency = (energy_kwh / 24 / (power_w / 1000)) * 100
            return round(efficiency, 1)
        except (ValueError, ZeroDivisionError):
            return None
