# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/eversolar-pmu-ha

"""Data update coordinator for Eversolar PMU."""
import logging
from datetime import date, datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTO_SYNC_DELAY,
    CONF_AUTO_SYNC_ENABLED,
    CONF_HOST,
    CONF_PORT,
    CONF_PV_VOLTAGE_STATS_CUTOFF,
    CONF_PV_VOLTAGE_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .eversolar_protocol import EversolarPMU

_LOGGER = logging.getLogger(__name__)


class EversolarDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinate Eversolar PMU data updates.

    One PMU can report several inverters. ``self.data`` is a dict keyed by
    inverter ID, each value being that inverter's readings.
    """

    def __init__(self, hass: HomeAssistant, entry) -> None:
        """Initialize coordinator."""
        self.pmu = EversolarPMU(
            host=entry.data[CONF_HOST],
            port=entry.data.get(CONF_PORT, 8080),
            timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )
        self.config_entry = entry
        self.inverter_ids: list[str] = []

        # PMU-wide state tracking
        self._synced_today: bool = False
        self._last_sync_date: date | None = None
        self._was_connected: bool = False
        self._time_sync_success: bool = False

        # Per-inverter state tracking, keyed by inverter ID
        self._last_mode: dict[str, int | None] = {}
        self._ac_online_time: dict[str, datetime] = {}
        self._ac_offline_time: dict[str, datetime] = {}

        update_interval = timedelta(
            seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    def _get_config(self, key, default=None):
        opts = self.config_entry.options
        if key in opts:
            return opts[key]
        return self.config_entry.data.get(key, default)

    def inverter_data(self, inverter_id: str) -> dict | None:
        """Return the latest readings for one inverter, if it was reported."""
        if not self.data:
            return None
        return self.data.get(inverter_id)

    def is_fully_down(self, inverter_id):
        data = self.inverter_data(inverter_id)
        if not data:
            return False
        threshold = self._get_config(CONF_PV_VOLTAGE_THRESHOLD, 50)
        if not threshold:          # 0 = disabled
            return False
        return data.get("mode") == 0 and (data.get("pv_v") or 0) < threshold

    def is_below_stats_cutoff(self, inverter_id):
        data = self.inverter_data(inverter_id)
        if not data:
            return False
        cutoff = self._get_config(CONF_PV_VOLTAGE_STATS_CUTOFF, 20)
        if not cutoff:             # 0 = disabled
            return False
        return (data.get("pv_v") or 0) < cutoff

    @property
    def time_sync_success(self) -> bool:
        """Return True if time sync was successful."""
        return self._time_sync_success

    def _track_ac_transitions(self, inverter_id: str, data: dict) -> None:
        """Record when an inverter's AC side went online/offline."""
        current_mode = data.get("mode")
        last_mode = self._last_mode.get(inverter_id)
        if current_mode is not None and last_mode is not None:
            if last_mode == 0x0000 and current_mode == 0x0001:
                # Wait -> Normal: AC came online
                self._ac_online_time[inverter_id] = datetime.now(timezone.utc)
                _LOGGER.info(
                    "Inverter %s AC came online at %s",
                    inverter_id,
                    self._ac_online_time[inverter_id].isoformat(),
                )
            elif last_mode == 0x0001 and current_mode == 0x0000:
                # Normal -> Wait: AC went offline
                self._ac_offline_time[inverter_id] = datetime.now(timezone.utc)
                _LOGGER.info(
                    "Inverter %s AC went offline at %s",
                    inverter_id,
                    self._ac_offline_time[inverter_id].isoformat(),
                )
        if current_mode is not None:
            self._last_mode[inverter_id] = current_mode

        # Timestamp sensors expect datetime objects
        if inverter_id in self._ac_online_time:
            data["ac_online_time"] = self._ac_online_time[inverter_id]
        if inverter_id in self._ac_offline_time:
            data["ac_offline_time"] = self._ac_offline_time[inverter_id]

    async def _async_update_data(self) -> dict:
        """Fetch data for every inverter from the PMU."""
        try:
            data = await self.hass.async_add_executor_job(
                self.pmu.connect_and_poll_all,
                False,  # set_time=False for normal polling
                self.hass.config.time_zone,
            )

            self.inverter_ids = list(data)
            _LOGGER.debug("Inverters reported by PMU: %s", self.inverter_ids)

            current_date = datetime.now().date()

            # Reset daily sync flag at midnight
            if self._last_sync_date != current_date:
                self._synced_today = False
                self._last_sync_date = current_date

            # Sync time on first poll of the day or after connection loss
            should_sync = False
            if not self._synced_today:
                should_sync = True
                _LOGGER.info("First successful poll of the day - syncing time")
            elif not self._was_connected:
                should_sync = True
                _LOGGER.info("Connection restored - syncing time")

            if should_sync:
                success = await self.async_sync_time()
                if success:
                    self._synced_today = True
                    self._time_sync_success = True
                    _LOGGER.info("Time sync completed successfully")
                else:
                    self._time_sync_success = False
                    _LOGGER.warning("Time sync failed")

            # Mark connection as active
            self._was_connected = True

            for inverter_id, inverter in data.items():
                self._track_ac_transitions(inverter_id, inverter)

            return data
        except Exception as err:
            self._was_connected = False
            raise UpdateFailed(f"Error communicating with PMU: {err}") from err

    async def async_sync_time(self) -> bool:
        """Sync PMU time to host time."""
        try:
            tz_name = self.hass.config.time_zone
            await self.hass.async_add_executor_job(
                self.pmu.sync_time,
                tz_name,
            )
            _LOGGER.debug("PMU time synced")
            # Request immediate refresh to update time_delta
            await self.async_request_refresh()
            return True
        except Exception as err:
            _LOGGER.error("Error syncing PMU time: %s", err)
            return False
