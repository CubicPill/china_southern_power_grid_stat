"""Sensors for the China Southern Power Grid Statistics integration."""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
import traceback
from datetime import timedelta
from typing import Any

import async_timeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, STATE_UNAVAILABLE, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import CONF_UPDATED_AT
from .const import (
    ATTR_KEY_CURRENT_LADDER_START_DATE,
    ATTR_KEY_LAST_MONTH_BY_DAY,
    ATTR_KEY_LAST_YEAR_BY_MONTH,
    ATTR_KEY_LATEST_DAY_DATE,
    ATTR_KEY_THIS_MONTH_BY_DAY,
    ATTR_KEY_THIS_YEAR_BY_MONTH,
    CONF_AUTH_TOKEN,
    CONF_ELE_ACCOUNTS,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    DATA_KEY_LAST_UPDATE_DAY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DOMAIN,
    LADDER_TIER_NAMES,
    RETRY_BACKOFF_MULTIPLIER,
    SETTING_LAST_MONTH_UPDATE_DAY_THRESHOLD,
    SETTING_LAST_YEAR_UPDATE_DAY_THRESHOLD,
    SETTING_UPDATE_TIMEOUT,
    STATE_UPDATE_UNCHANGED,
    SUFFIX_ARR,
    SUFFIX_BAL,
    SUFFIX_CURRENT_LADDER,
    SUFFIX_CURRENT_LADDER_REMAINING_KWH,
    SUFFIX_CURRENT_LADDER_TARIFF,
    SUFFIX_LAST_MONTH_COST,
    SUFFIX_LAST_MONTH_KWH,
    SUFFIX_LAST_YEAR_COST,
    SUFFIX_LAST_YEAR_KWH,
    SUFFIX_LATEST_DAY_COST,
    SUFFIX_LATEST_DAY_KWH,
    SUFFIX_THIS_MONTH_COST,
    SUFFIX_THIS_MONTH_KWH,
    SUFFIX_THIS_YEAR_BILL_COST,
    SUFFIX_THIS_YEAR_BILL_KWH,
    SUFFIX_THIS_YEAR_COST,
    SUFFIX_THIS_YEAR_KWH,
    SUFFIX_YESTERDAY_KWH,
    SUFFIX_YEARLY_LADDER_TOTAL_KWH,
)
from .csg_client import (
    JSON_KEY_METERING_POINT_NUMBER,
    WF_ATTR_CHARGE,
    WF_ATTR_DATE,
    WF_ATTR_KWH,
    WF_ATTR_LADDER,
    WF_ATTR_LADDER_REMAINING_KWH,
    WF_ATTR_LADDER_START_DATE,
    WF_ATTR_LADDER_TARIFF,
    WF_ATTR_YEARLY_LADDER_TOTAL_KWH,
    CSGAPIError,
    CSGClient,
    CSGElectricityAccount,
    NotLoggedIn,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensors from a config entry created in the integrations UI."""
    if not config_entry.data[CONF_ELE_ACCOUNTS]:
        _LOGGER.info("No ele accounts in config, exit entry setup")
        return
    coordinator = CSGCoordinator(hass, config_entry.entry_id)

    all_sensors = []
    for ele_account_number, _ in config_entry.data[CONF_ELE_ACCOUNTS].items():
        sensors = [
            # balance
            CSGCostSensor(coordinator, ele_account_number, SUFFIX_BAL),
            # arrears
            CSGCostSensor(coordinator, ele_account_number, SUFFIX_ARR),
            # yesterday kwh
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_YESTERDAY_KWH,
            ),
            # latest day usage that is available, with extra attributes about the date
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_LATEST_DAY_KWH,
                extra_state_attributes_key=ATTR_KEY_LATEST_DAY_DATE,
            ),
            # latest day cost that is available, with extra attributes about the date
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_LATEST_DAY_COST,
                extra_state_attributes_key=ATTR_KEY_LATEST_DAY_DATE,
            ),
            # this year's bill energy (settled months only), with extra attributes about monthly usage
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_YEAR_BILL_KWH,
                extra_state_attributes_key=ATTR_KEY_THIS_YEAR_BY_MONTH,
            ),
            # this year's bill cost (settled months only)
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_YEAR_BILL_COST,
            ),
            # this year's actual energy (bill + current month)
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_YEAR_KWH,
            ),
            # this year's actual cost (bill + current month)
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_YEAR_COST,
            ),
            # this month's total energy, with extra attributes about daily usage
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_THIS_MONTH_BY_DAY,
            ),
            # this month's total cost, with extra attributes about daily usage
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_THIS_MONTH_COST,
                extra_state_attributes_key=ATTR_KEY_THIS_MONTH_BY_DAY,
            ),
            # current ladder, with extra attributes about start date
            CSGLadderStageSensor(
                coordinator,
                ele_account_number,
                SUFFIX_CURRENT_LADDER,
                extra_state_attributes_key=ATTR_KEY_CURRENT_LADDER_START_DATE,
            ),
            # current ladder remaining kwh
            CSGEnergySensor(
                coordinator, ele_account_number, SUFFIX_CURRENT_LADDER_REMAINING_KWH
            ),
            # current ladder tariff
            CSGCostSensor(
                coordinator, ele_account_number, SUFFIX_CURRENT_LADDER_TARIFF
            ),
            # last year's total energy, with extra attributes about monthly usage
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_LAST_YEAR_KWH,
                extra_state_attributes_key=ATTR_KEY_LAST_YEAR_BY_MONTH,
            ),
            # last year's total cost
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_LAST_YEAR_COST,
            ),
            # last month's total energy, with extra attributes about daily usage
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_LAST_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_LAST_MONTH_BY_DAY,
            ),
            # last month's total cost, with extra attributes about daily usage
            CSGCostSensor(
                coordinator,
                ele_account_number,
                SUFFIX_LAST_MONTH_COST,
                extra_state_attributes_key=ATTR_KEY_LAST_MONTH_BY_DAY,
            ),
            # yearly ladder total kwh (cumulative consumption in year for tiered pricing)
            CSGEnergySensor(
                coordinator,
                ele_account_number,
                SUFFIX_YEARLY_LADDER_TOTAL_KWH,
            ),
        ]

        all_sensors.extend(sensors)

    async_add_entities(all_sensors)
    _LOGGER.debug(f"created {len(all_sensors)} sensors for config {config_entry.title}")
    # Schedule the first update to run in the background
    config_entry.async_create_task(
        hass,
        coordinator.async_config_entry_first_refresh(),
        f"{config_entry.title}_first_update",
    )


class CSGBaseSensor(
    CoordinatorEntity,
    SensorEntity,
):
    """Base CSG sensor"""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        account_number: str,
        entity_suffix: str,
        extra_state_attributes_key: str | None = None,
    ) -> None:
        SensorEntity.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._coordinator = coordinator
        self._account_number = account_number

        self._entity_suffix = entity_suffix
        self._attr_extra_state_attributes = {}
        self._extra_state_attributes_key = extra_state_attributes_key

    @property
    def unique_id(self) -> str | None:
        return f"{DOMAIN}.{self._account_number}.{self._entity_suffix}"

    @property
    def name(self) -> str | None:
        return f"{self._account_number}-{self._entity_suffix}"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_number)},
            name=f"CSGAccount-{self._account_number}",
            manufacturer="CSG",
            model="CSG Virtual Electricity Meter",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # _LOGGER.debug(
        #     "%s coordinator update triggered",
        #     self.unique_id,
        # )

        if not self._coordinator.data:
            _LOGGER.error(
                "%s coordinator has no data",
                self.unique_id,
            )
            self._attr_available = False
            self.async_write_ha_state()
            return

        account_data = self._coordinator.data.get(self._account_number)
        if account_data is None:
            _LOGGER.warning("%s not found in coordinator data", self.unique_id)
            self._attr_available = False
            self.async_write_ha_state()
            return

        # Session-expired sentinel: skip update, preserve last known value
        if account_data == CSGCoordinator.SESSION_EXPIRED:
            _LOGGER.debug("%s session expired, preserving last state", self.unique_id)
            return

        new_native_value = account_data.get(self._entity_suffix)
        if new_native_value is None:
            _LOGGER.warning("%s data not found in coordinator data", self.unique_id)
            self._attr_available = False
            self.async_write_ha_state()
            return

        if new_native_value == STATE_UNAVAILABLE:
            # Preserve last known value on transient fetch failures (e.g. CSG upstream
            # returns sta=09 "无此用户数据" or marketing system outage). This keeps
            # the dashboard showing the last successful reading instead of going to
            # unknown / unavailable, so the user no longer needs to manually reload
            # the integration after every blip.
            if self._attr_native_value is not None:
                _LOGGER.debug(
                    "%s fetch returned unavailable, preserving last value %s",
                    self.unique_id,
                    self._attr_native_value,
                )
                return
            # First-time fetch failed (no previous value to keep): mark unavailable.
            _LOGGER.debug("%s data is unavailable", self.unique_id)
            self._attr_available = False
            self.async_write_ha_state()
            return

        # from this point the value is available
        self._attr_available = True

        if new_native_value == STATE_UPDATE_UNCHANGED:
            # no update for this sensor, skip
            _LOGGER.debug("%s doesn't need to be updated, skip", self.unique_id)
            return

        # from this point, `new_native_value` is a true value
        self._attr_native_value = new_native_value

        if self._extra_state_attributes_key:
            new_attributes = account_data.get(self._extra_state_attributes_key)
            if new_attributes is None:
                new_attributes = {}
                _LOGGER.warning(
                    "%s attribute %s not found in coordinator data",
                    self.unique_id,
                    self._extra_state_attributes_key,
                )
            self._attr_extra_state_attributes = new_attributes
        _LOGGER.debug("%s state update done!", self.unique_id)
        self.async_write_ha_state()


class CSGEnergySensor(CSGBaseSensor):
    """Representation of a CSG Energy Sensor."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:lightning-bolt"


class CSGCostSensor(CSGBaseSensor):
    """Representation of a CSG Cost Sensor."""

    _attr_native_unit_of_measurement = "CNY"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-cny"


class CSGLadderStageSensor(CSGBaseSensor):
    """Representation of a CSG Ladder Stage Sensor."""

    _attr_icon = "mdi:stairs"

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator with ladder name conversion."""
        # Call parent method first
        super()._handle_coordinator_update()

        # Convert ladder number to name if available
        if self._attr_native_value is not None and self._attr_available:
            try:
                ladder_num = int(self._attr_native_value)
                if ladder_num in LADDER_TIER_NAMES:
                    self._attr_native_value = LADDER_TIER_NAMES[ladder_num]
            except (ValueError, TypeError):
                # Keep original value if conversion fails
                pass


class CSGCoordinator(DataUpdateCoordinator):
    """CSG custom coordinator."""

    # Special internal value indicating session has expired
    SESSION_EXPIRED = "__CSG_SESSION_EXPIRED__"

    def __init__(self, hass: HomeAssistant, config_entry_id: str) -> None:
        """Initialize coordinator."""
        self._config_entry_id = config_entry_id
        self._config = hass.config_entries.async_get_entry(self._config_entry_id).data
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=f"CSG Account {self._config[CONF_USERNAME]}",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(
                seconds=self._config[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
            ),
        )
        self._client: CSGClient | None = None
        self._if_update_last_month = True
        self._if_update_last_year = True
        self._this_day = None
        self._this_year = None
        self._this_month_ym = None
        self._last_year = None
        self._last_month_ym = None
        self._this_month_update_completed_flag = asyncio.Event()
        self._gathered_data = {}
        # Auto retry settings
        self._max_retries = DEFAULT_MAX_RETRIES
        self._retry_delay = DEFAULT_RETRY_DELAY
        self._consecutive_failures = 0
        # Track session state to avoid spamming login-expired warnings
        self._session_expired_logged = False
        # Count consecutive successes for periodic reload
        self._consecutive_successes = 0

    async def _async_refresh_client(self) -> bool:
        """Refresh the client, update the user data.

        Returns True if session is valid and client is ready,
        False if session has expired (token invalid but present).
        Does NOT raise exceptions.
        """
        _LOGGER.debug("Refreshing client")
        self._client = await self.hass.async_add_executor_job(
            CSGClient.load,
            {
                CONF_AUTH_TOKEN: self._config[CONF_AUTH_TOKEN],
            },
        )
        logged_in = await self.hass.async_add_executor_job(
            self._client.verify_login,
        )
        if not logged_in:
            if not self._session_expired_logged:
                _LOGGER.warning(
                    f"{self._config[CONF_USERNAME]}: Login expired, will retry with extended interval"
                )
                self._session_expired_logged = True
            return False

        self._session_expired_logged = False
        _LOGGER.debug(f"{self._config[CONF_USERNAME]}: Session still valid")
        await self.hass.async_add_executor_job(self._client.initialize)
        return True

    async def _async_fetch(self, func: callable, *args, **kwargs) -> (bool, tuple):
        """Wrapper to fetch data from API. Return (success, result) with timeout.
        Also handle all exceptions here to avoid task group being cancelled.
        """
        try:
            async with async_timeout.timeout(SETTING_UPDATE_TIMEOUT):
                return True, await self.hass.async_add_executor_job(
                    func, *args, **kwargs
                )

        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout fetching data in function: %s", func.__name__)
            return False, (func.__name__, err)
        except NotLoggedIn as err:
            _LOGGER.error(
                "Session invalidated unexpectedly in function: %s", func.__name__
            )
            return False, (func.__name__, err)
        except CSGAPIError as err:
            _LOGGER.error(
                "Error fetching data in coordinator: API error, function %s, %s",
                func.__name__,
                err,
            )
            return False, (func.__name__, err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected exception: %s", err)
            _LOGGER.error(traceback.format_exc())
            return False, (func.__name__, err)

    async def _async_fetch_with_retry(self, func: callable, *args, **kwargs) -> (bool, tuple):
        """Wrapper to fetch data from API with retry mechanism.

        Returns (success, result) where result is either the data or error info.
        Implements exponential backoff for retries.
        """
        retry_count = 0
        delay = self._retry_delay
        last_error = None

        while retry_count <= self._max_retries:
            success, result = await self._async_fetch(func, *args, **kwargs)

            if success:
                self._consecutive_failures = 0
                return True, result

            # Store the error for logging
            last_error = result

            # If this is the last retry, return failure
            if retry_count == self._max_retries:
                _LOGGER.error(
                    "Max retries (%d) reached for function %s",
                    self._max_retries,
                    func.__name__
                )
                self._consecutive_failures += 1
                return False, last_error

            # Wait before retry with exponential backoff
            _LOGGER.warning(
                "Fetch failed for %s (attempt %d/%d), retrying in %d seconds... Error: %s",
                func.__name__,
                retry_count + 1,
                self._max_retries + 1,
                delay,
                last_error[1] if isinstance(last_error, tuple) and len(last_error) > 1 else last_error
            )
            await asyncio.sleep(delay)
            delay *= RETRY_BACKOFF_MULTIPLIER
            retry_count += 1

        return False, last_error

    async def _async_update_bal_arr(self, account: CSGElectricityAccount):
        """Update balance and arrears"""
        success, result = await self._async_fetch_with_retry(
            self._client.get_balance_and_arrears, account
        )
        if success:
            balance, arrears = result
            _LOGGER.debug(
                "Updated balance and arrears for account %s: %s",
                account.account_number,
                result,
            )
        else:
            balance, arrears = STATE_UNAVAILABLE, STATE_UNAVAILABLE
            _LOGGER.error(
                "Error updating balance and arrears for account %s: %s",
                account.account_number,
                result,
            )
        self._gathered_data[account.account_number][SUFFIX_BAL] = balance
        self._gathered_data[account.account_number][SUFFIX_ARR] = arrears

    async def _async_update_yesterday_kwh(self, account: CSGElectricityAccount):
        """Update yesterday's kwh"""
        success, result = await self._async_fetch_with_retry(
            self._client.get_yesterday_kwh,
            account,
        )
        if success and result is not None:
            yesterday_kwh = result
            _LOGGER.debug(
                "Updated yesterday's kwh for account %s: %s",
                account.account_number,
                result,
            )
        else:
            yesterday_kwh = STATE_UNAVAILABLE
            _LOGGER.error(
                "Error updating yesterday's kwh for account %s: %s",
                account.account_number,
                result,
            )
        self._gathered_data[account.account_number][
            SUFFIX_YESTERDAY_KWH
        ] = yesterday_kwh

    async def _async_update_this_year_stats(self, account: CSGElectricityAccount):
        """Update this year's bill data (settled months only)"""
        success, result = await self._async_fetch_with_retry(
            self._client.get_year_month_stats, account, self._this_year
        )
        if success:
            (
                this_year_bill_cost,
                this_year_bill_kwh,
                this_year_by_month,
            ) = result

            _LOGGER.debug(
                "Updated this year's bill data for account %s: %s",
                account.account_number,
                result,
            )
        else:
            _LOGGER.error(
                "Error updating this year's bill data for account %s: %s",
                account.account_number,
                result,
            )
            this_year_bill_cost, this_year_bill_kwh, this_year_by_month = (
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
            )
        # Store bill data (settled months only)
        self._gathered_data[account.account_number][
            SUFFIX_THIS_YEAR_BILL_KWH
        ] = this_year_bill_kwh
        self._gathered_data[account.account_number][
            SUFFIX_THIS_YEAR_BILL_COST
        ] = this_year_bill_cost
        self._gathered_data[account.account_number][ATTR_KEY_THIS_YEAR_BY_MONTH] = {
            ATTR_KEY_THIS_YEAR_BY_MONTH: this_year_by_month
        }

    async def _async_update_last_year_stats(self, account: CSGElectricityAccount):
        """Update last year's data"""
        if not self._if_update_last_year:
            self._gathered_data[account.account_number][
                SUFFIX_LAST_YEAR_KWH
            ] = STATE_UPDATE_UNCHANGED
            self._gathered_data[account.account_number][
                SUFFIX_LAST_YEAR_COST
            ] = STATE_UPDATE_UNCHANGED
            self._gathered_data[account.account_number][ATTR_KEY_LAST_YEAR_BY_MONTH] = {
                ATTR_KEY_LAST_YEAR_BY_MONTH: STATE_UPDATE_UNCHANGED
            }
            _LOGGER.debug(
                "Last year's data for account %s: no need to update",
                account.account_number,
            )
            return
        success, result = await self._async_fetch_with_retry(
            self._client.get_year_month_stats, account, self._last_year
        )
        if success:
            (
                last_year_cost,
                last_year_kwh,
                last_year_by_month,
            ) = result

            _LOGGER.debug(
                "Updated last year's data for account %s: %s",
                account.account_number,
                result,
            )
        else:
            _LOGGER.error(
                "Error updating last year's data for account %s: %s",
                account.account_number,
                result,
            )
            last_year_cost, last_year_kwh, last_year_by_month = (
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
            )
        self._gathered_data[account.account_number][
            SUFFIX_LAST_YEAR_KWH
        ] = last_year_kwh
        self._gathered_data[account.account_number][
            SUFFIX_LAST_YEAR_COST
        ] = last_year_cost
        self._gathered_data[account.account_number][ATTR_KEY_LAST_YEAR_BY_MONTH] = {
            ATTR_KEY_LAST_YEAR_BY_MONTH: last_year_by_month
        }

    @staticmethod
    def merge_by_day_data(
        by_day_from_cost: list | str,
        kwh_from_cost: float | str,
        by_day_from_usage: list | str,
        kwh_from_usage: float | str,
    ) -> (list | str, float | str):
        """Merge by_day_from_usage and by_day_from_cost data"""
        # merge by_day
        # determine which is the latest
        if (
            by_day_from_cost == STATE_UNAVAILABLE
            and by_day_from_usage == STATE_UNAVAILABLE
        ):
            by_day = STATE_UNAVAILABLE
        elif by_day_from_cost == STATE_UNAVAILABLE:
            by_day = by_day_from_usage
        elif by_day_from_usage == STATE_UNAVAILABLE:
            by_day = by_day_from_cost
        else:
            # both are available
            if len(by_day_from_cost) >= len(by_day_from_usage):
                # the result from daily cost is newer
                by_day = by_day_from_cost
            else:
                # the result from daily usage is newer
                # but since the result from daily cost contains cost data, need to merge them
                by_day = by_day_from_usage
                for idx, item in enumerate(by_day_from_cost):
                    by_day[idx][WF_ATTR_CHARGE] = item[WF_ATTR_CHARGE]

        # determine which one to use as kwh
        if kwh_from_cost == STATE_UNAVAILABLE and kwh_from_usage == STATE_UNAVAILABLE:
            kwh = STATE_UNAVAILABLE
        elif kwh_from_cost == STATE_UNAVAILABLE:
            kwh = kwh_from_usage
        elif kwh_from_usage == STATE_UNAVAILABLE:
            kwh = kwh_from_cost
        else:
            # determine which kwh is the latest
            # get the larger one
            kwh = max(kwh_from_cost, kwh_from_usage)
        return by_day, kwh

    async def _async_update_this_month_stats_and_ladder(
        self, account: CSGElectricityAccount
    ):
        """Update this month's usage, cost and ladder"""
        # fetch usage and cost in parallel
        task_fetch_usage = asyncio.create_task(
            self._async_fetch(
                self._client.get_month_daily_usage_detail, account, self._this_month_ym
            )
        )
        task_fetch_cost = asyncio.create_task(
            self._async_fetch(
                self._client.get_month_daily_cost_detail, account, self._this_month_ym
            )
        )

        results = await asyncio.gather(task_fetch_usage, task_fetch_cost)

        (success_usage, result_usage), (success_cost, result_cost) = results

        if success_usage:
            this_month_kwh_from_usage, this_month_by_day_from_usage = result_usage
        else:
            this_month_kwh_from_usage = STATE_UNAVAILABLE
            this_month_by_day_from_usage = STATE_UNAVAILABLE

        if success_cost:
            (
                this_month_cost,
                this_month_kwh_from_cost,
                ladder,
                this_month_by_day_from_cost,
            ) = result_cost
            # special processing
            if this_month_cost is None:
                this_month_cost = STATE_UNAVAILABLE
            if this_month_kwh_from_cost is None:
                this_month_kwh_from_cost = STATE_UNAVAILABLE
            ladder_stage = (
                ladder[WF_ATTR_LADDER]
                if ladder[WF_ATTR_LADDER] is not None
                else STATE_UNAVAILABLE
            )
            ladder_remaining_kwh = (
                ladder[WF_ATTR_LADDER_REMAINING_KWH]
                if ladder[WF_ATTR_LADDER_REMAINING_KWH] is not None
                else STATE_UNAVAILABLE
            )
            ladder_tariff = (
                ladder[WF_ATTR_LADDER_TARIFF]
                if ladder[WF_ATTR_LADDER_TARIFF] is not None
                else STATE_UNAVAILABLE
            )
            ladder_start_date = (
                ladder[WF_ATTR_LADDER_START_DATE]
                if ladder[WF_ATTR_LADDER_START_DATE] is not None
                else STATE_UNAVAILABLE
            )
        else:
            (
                this_month_cost,
                this_month_kwh_from_cost,
                this_month_by_day_from_cost,
                ladder_stage,
                ladder_remaining_kwh,
                ladder_tariff,
                ladder_start_date,
            ) = (
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
            )
        this_month_by_day, this_month_kwh = self.merge_by_day_data(
            by_day_from_usage=this_month_by_day_from_usage,
            kwh_from_usage=this_month_kwh_from_usage,
            by_day_from_cost=this_month_by_day_from_cost,
            kwh_from_cost=this_month_kwh_from_cost,
        )

        if this_month_by_day == STATE_UNAVAILABLE:
            # need last month's data to update `latest_day` entity
            self._if_update_last_month = True

        self._gathered_data[account.account_number][
            SUFFIX_THIS_MONTH_KWH
        ] = this_month_kwh
        self._gathered_data[account.account_number][
            SUFFIX_THIS_MONTH_COST
        ] = this_month_cost
        self._gathered_data[account.account_number][ATTR_KEY_THIS_MONTH_BY_DAY] = {
            ATTR_KEY_THIS_MONTH_BY_DAY: this_month_by_day
        }
        self._gathered_data[account.account_number][
            SUFFIX_CURRENT_LADDER
        ] = ladder_stage
        self._gathered_data[account.account_number][
            SUFFIX_CURRENT_LADDER_REMAINING_KWH
        ] = ladder_remaining_kwh
        self._gathered_data[account.account_number][
            SUFFIX_CURRENT_LADDER_TARIFF
        ] = ladder_tariff
        self._gathered_data[account.account_number][
            ATTR_KEY_CURRENT_LADDER_START_DATE
        ] = {ATTR_KEY_CURRENT_LADDER_START_DATE: ladder_start_date}

        self._this_month_update_completed_flag.set()

    async def _async_update_last_month_stats(self, account: CSGElectricityAccount):
        """Update last month's usage and cost"""
        if not self._if_update_last_month:
            # original condition, don't need to update last month's data

            # wait for this month's data to be updated to see if last month's data is needed
            await self._this_month_update_completed_flag.wait()

            if not self._if_update_last_month:
                # don't need last month's data for latest day
                _LOGGER.debug(
                    "Last month's data for account %s: no need to update",
                    account.account_number,
                )
                self._gathered_data[account.account_number][
                    SUFFIX_LAST_MONTH_KWH
                ] = STATE_UPDATE_UNCHANGED
                self._gathered_data[account.account_number][
                    SUFFIX_LAST_MONTH_COST
                ] = STATE_UPDATE_UNCHANGED
                self._gathered_data[account.account_number][
                    ATTR_KEY_LAST_MONTH_BY_DAY
                ] = {ATTR_KEY_LAST_MONTH_BY_DAY: STATE_UPDATE_UNCHANGED}
                return

        # continue to update last month's data
        # fetch usage and cost in parallel
        task_fetch_usage = asyncio.create_task(
            self._async_fetch(
                self._client.get_month_daily_usage_detail, account, self._last_month_ym
            )
        )
        task_fetch_cost = asyncio.create_task(
            self._async_fetch(
                self._client.get_month_daily_cost_detail, account, self._last_month_ym
            )
        )

        results = await asyncio.gather(task_fetch_usage, task_fetch_cost)

        (success_usage, result_usage), (success_cost, result_cost) = results

        if success_usage:
            last_month_kwh_from_usage, last_month_by_day_from_usage = result_usage
        else:
            last_month_kwh_from_usage = STATE_UNAVAILABLE
            last_month_by_day_from_usage = STATE_UNAVAILABLE

        if success_cost:
            (
                last_month_cost,
                last_month_kwh_from_cost,
                _,  # ladder is discarded
                last_month_by_day_from_cost,
            ) = result_cost

            # for last month, it's safe to calculate total kwh from cost
            if not last_month_cost:
                last_month_cost = sum(
                    d[WF_ATTR_CHARGE] for d in last_month_by_day_from_cost
                )
            if not last_month_kwh_from_cost:
                last_month_kwh_from_cost = sum(
                    d[WF_ATTR_KWH] for d in last_month_by_day_from_cost
                )
        else:
            (
                last_month_cost,
                last_month_kwh_from_cost,
                last_month_by_day_from_cost,
            ) = (
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
                STATE_UNAVAILABLE,
            )
        last_month_by_day, last_month_kwh = self.merge_by_day_data(
            by_day_from_usage=last_month_by_day_from_usage,
            kwh_from_usage=last_month_kwh_from_usage,
            by_day_from_cost=last_month_by_day_from_cost,
            kwh_from_cost=last_month_kwh_from_cost,
        )

        self._gathered_data[account.account_number][
            SUFFIX_LAST_MONTH_KWH
        ] = last_month_kwh
        self._gathered_data[account.account_number][
            SUFFIX_LAST_MONTH_COST
        ] = last_month_cost
        self._gathered_data[account.account_number][ATTR_KEY_LAST_MONTH_BY_DAY] = {
            ATTR_KEY_LAST_MONTH_BY_DAY: last_month_by_day
        }

    def _update_latest_day(self, account: CSGElectricityAccount):
        """Update latest day sensors from API data (no estimation)

        Data sources:
        - latest_day_kwh: from this_month_by_day[-1]["kwh"] or last_month_by_day[-1]["kwh"]
        - latest_day_cost: from this_month_by_day[-1]["charge"] or calculated from kwh × tariff
        - latest_day_date: from this_month_by_day[-1]["date"] or last_month_by_day[-1]["date"]

        Note: This method only uses data directly from API. No estimation/fallback.
        """
        this_month_by_day = self._gathered_data[account.account_number][
            ATTR_KEY_THIS_MONTH_BY_DAY
        ][ATTR_KEY_THIS_MONTH_BY_DAY]
        last_month_by_day = self._gathered_data[account.account_number][
            ATTR_KEY_LAST_MONTH_BY_DAY
        ][ATTR_KEY_LAST_MONTH_BY_DAY]

        if (
            this_month_by_day == STATE_UNAVAILABLE
            and last_month_by_day == STATE_UNAVAILABLE
        ):
            latest_day_kwh = STATE_UNAVAILABLE
            latest_day_cost = STATE_UNAVAILABLE
            latest_day_date = STATE_UNAVAILABLE
        else:
            if this_month_by_day != STATE_UNAVAILABLE and len(this_month_by_day) >= 1:
                # we have this month's data, use the latest day
                latest_day_kwh = this_month_by_day[-1][WF_ATTR_KWH]
                latest_day_cost = (
                    this_month_by_day[-1].get(WF_ATTR_CHARGE) or STATE_UNAVAILABLE
                )
                latest_day_date = this_month_by_day[-1][WF_ATTR_DATE]
            else:
                # this month isn't available yet (typically during the first 3 days)
                # let's try last month
                if (
                    last_month_by_day
                    not in [
                        STATE_UNAVAILABLE,
                        STATE_UPDATE_UNCHANGED,
                    ]
                    and len(last_month_by_day) >= 1
                ):
                    latest_day_kwh = last_month_by_day[-1][WF_ATTR_KWH]
                    latest_day_cost = STATE_UNAVAILABLE
                    latest_day_date = last_month_by_day[-1][WF_ATTR_DATE]
                else:
                    # No daily detail data available from API
                    latest_day_kwh = STATE_UNAVAILABLE
                    latest_day_cost = STATE_UNAVAILABLE
                    latest_day_date = STATE_UNAVAILABLE

        # Calculate latest_day_cost from latest_day_kwh if not available.
        # Prefer the real average unit price from settled bills:
        # time-of-use accounts cannot be estimated from the flat tier tariff.
        if latest_day_cost == STATE_UNAVAILABLE and latest_day_kwh not in [STATE_UNAVAILABLE, None]:
            current_tariff = self._gathered_data[account.account_number].get(
                SUFFIX_CURRENT_LADDER_TARIFF
            )
            if current_tariff in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED]:
                current_tariff = None
            est_price = current_tariff
            try:
                tym = self._gathered_data[account.account_number][
                    ATTR_KEY_THIS_YEAR_BY_MONTH
                ][ATTR_KEY_THIS_YEAR_BY_MONTH]
                bill_cost = sum(float(m.get(WF_ATTR_CHARGE) or 0) for m in tym)
                bill_kwh = sum(float(m.get(WF_ATTR_KWH) or 0) for m in tym)
                if bill_kwh > 0:
                    est_price = bill_cost / bill_kwh
            except (KeyError, TypeError, ValueError):
                pass
            if est_price is not None:
                latest_day_cost = round(latest_day_kwh * est_price, 2)
                _LOGGER.debug(
                    "Calculated latest_day_cost from latest_day_kwh: %s kWh × %s (avg) = %s CNY",
                    latest_day_kwh, round(est_price, 4), latest_day_cost
                )

        self._gathered_data[account.account_number][
            SUFFIX_LATEST_DAY_KWH
        ] = latest_day_kwh
        self._gathered_data[account.account_number][
            SUFFIX_LATEST_DAY_COST
        ] = latest_day_cost
        self._gathered_data[account.account_number][ATTR_KEY_LATEST_DAY_DATE] = {
            ATTR_KEY_LATEST_DAY_DATE: latest_day_date
        }

    def _update_this_year_actual(self, account: CSGElectricityAccount):
        """Calculate this year's actual data (bill + current month)"""
        # Get bill data (settled months)
        this_year_bill_kwh = self._gathered_data[account.account_number].get(
            SUFFIX_THIS_YEAR_BILL_KWH
        )
        this_year_bill_cost = self._gathered_data[account.account_number].get(
            SUFFIX_THIS_YEAR_BILL_COST
        )

        # Get current month data
        this_month_kwh = self._gathered_data[account.account_number].get(
            SUFFIX_THIS_MONTH_KWH
        )
        this_month_cost = self._gathered_data[account.account_number].get(
            SUFFIX_THIS_MONTH_COST
        )

        # Calculate actual data (bill + current month)
        if (
            this_year_bill_kwh not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_kwh not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            this_year_actual_kwh = this_year_bill_kwh + this_month_kwh
        elif (
            this_year_bill_kwh in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_kwh not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            # Only have current month data
            this_year_actual_kwh = this_month_kwh
        elif (
            this_year_bill_kwh not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_kwh in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            # Only have bill data
            this_year_actual_kwh = this_year_bill_kwh
        else:
            this_year_actual_kwh = STATE_UNAVAILABLE

        if (
            this_year_bill_cost not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_cost not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            this_year_actual_cost = this_year_bill_cost + this_month_cost
        elif (
            this_year_bill_cost in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_cost not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            # Only have current month data
            this_year_actual_cost = this_month_cost
        elif (
            this_year_bill_cost not in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
            and this_month_cost in [STATE_UNAVAILABLE, STATE_UPDATE_UNCHANGED, None]
        ):
            # Only have bill data
            this_year_actual_cost = this_year_bill_cost
        else:
            this_year_actual_cost = STATE_UNAVAILABLE

        self._gathered_data[account.account_number][
            SUFFIX_THIS_YEAR_KWH
        ] = this_year_actual_kwh
        self._gathered_data[account.account_number][
            SUFFIX_THIS_YEAR_COST
        ] = this_year_actual_cost

        _LOGGER.debug(
            "Ele account %s, this year actual: kwh=%s, cost=%s (bill: kwh=%s, cost=%s + month: kwh=%s, cost=%s)",
            account.account_number,
            this_year_actual_kwh,
            this_year_actual_cost,
            this_year_bill_kwh,
            this_year_bill_cost,
            this_month_kwh,
            this_month_cost,
        )

    async def _async_update_yearly_ladder_info(
        self, account: CSGElectricityAccount
    ):
        """Update yearly ladder (tiered pricing) cumulative consumption"""
        success, result = await self._async_fetch_with_retry(
            self._client.get_yearly_ladder_info, account, self._this_year
        )
        if success:
            yearly_ladder_info = result
            _LOGGER.debug(
                "Updated yearly ladder info for account %s: %s",
                account.account_number,
                result,
            )

            # Extract data from yearly ladder info
            total_kwh = yearly_ladder_info.get(WF_ATTR_YEARLY_LADDER_TOTAL_KWH)

            self._gathered_data[account.account_number][
                SUFFIX_YEARLY_LADDER_TOTAL_KWH
            ] = total_kwh if total_kwh is not None else STATE_UNAVAILABLE
        else:
            _LOGGER.error(
                "Error updating yearly ladder info for account %s: %s",
                account.account_number,
                result,
            )
            self._gathered_data[account.account_number][
                SUFFIX_YEARLY_LADDER_TOTAL_KWH
            ] = STATE_UNAVAILABLE

    def _update_states(self):
        current_dt = datetime.datetime.now()
        this_year, this_month, this_day = (
            current_dt.year,
            current_dt.month,
            current_dt.day,
        )
        last_year, last_month = this_year - 1, this_month - 1
        if last_month == 0:
            last_month_ym = (last_year, 12)
        else:
            last_month_ym = (this_year, last_month)
        self._this_day = this_day
        self._this_year = this_year
        self._this_month_ym = (this_year, this_month)
        self._last_year = last_year
        self._last_month_ym = last_month_ym

        # for last month and last year data, they won't change over a long period of time
        # so we could use cache
        #
        # update policy for last month:
        # for the first <LAST_MONTH_UPDATE_DAY_THRESHOLD> days of a month,
        # update every `update_interval`.
        # for the rest of the time, do not update.

        # update policy for last year:
        # for the first <LAST_YEAR_UPDATE_DAY_THRESHOLD> days of Jan, update daily at first update
        # for the rest of the time, do not update
        #
        # when integration is reloaded, all updates will be triggered
        # so user could just reload the integration to refresh the data if needed

        if (
            self.hass.data[DOMAIN][self._config_entry_id].get(DATA_KEY_LAST_UPDATE_DAY)
            is None
        ):
            # first update
            update_last_month = True
            update_last_year = True
            _LOGGER.debug(
                "First update for account %s, getting all past data",
                self._config[CONF_USERNAME],
            )
        else:
            update_last_month = False
            update_last_year = False

            if this_day <= SETTING_LAST_MONTH_UPDATE_DAY_THRESHOLD:
                update_last_month = True
            today_first_update_triggered = (
                self.hass.data[DOMAIN][self._config_entry_id][DATA_KEY_LAST_UPDATE_DAY]
                == this_day
            )
            if this_month == 1 and this_day <= SETTING_LAST_YEAR_UPDATE_DAY_THRESHOLD:
                if not today_first_update_triggered:
                    update_last_year = True
        self._if_update_last_month = update_last_month
        self._if_update_last_year = update_last_year

    async def _async_update_account_data(self, account: CSGElectricityAccount):
        start_time = time.time()
        # TODO use asyncio.TaskGroup() in 3.11

        # async with asyncio.TaskGroup() as task_group:
        #     task_group.create_task(self._async_update_bal_arr(account))
        #     task_group.create_task(self._async_update_yesterday_kwh(account))
        #     task_group.create_task(self._async_update_this_year_stats(account))
        #     task_group.create_task(self._async_update_last_year_stats(account))
        #     task_group.create_task(
        #         self._async_update_this_month_stats_and_ladder(account)
        #     )
        #     task_group.create_task(self._async_update_last_month_stats(account))
        await asyncio.gather(
            self._async_update_bal_arr(account),
            self._async_update_yesterday_kwh(account),
            self._async_update_this_year_stats(account),
            self._async_update_last_year_stats(account),
            self._async_update_this_month_stats_and_ladder(account),
            self._async_update_last_month_stats(account),
            self._async_update_yearly_ladder_info(account),
            return_exceptions=True,
        )
        try:
            self._update_latest_day(account)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error(
                "Ele account %s, update latest day data failed: %s",
                account.account_number,
                exc,
            )

        # Calculate this year's actual data (bill + current month)
        try:
            self._update_this_year_actual(account)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error(
                "Ele account %s, update this year actual data failed: %s",
                account.account_number,
                exc,
            )

        _LOGGER.debug(
            "Ele account %s, update took %s seconds",
            account.account_number,
            time.time() - start_time,
        )

    # Auto-reload threshold: after this many consecutive failures, reload the
    # entire integration to re-initialize session and API connections.
    AUTO_RELOAD_FAILURE_THRESHOLD = 6
    # Delay before a scheduled entry reload runs, to let the current
    # coordinator update cycle finish first (avoid unload/refresh deadlock).
    ENTRY_RELOAD_DELAY_SECONDS = 5

    @callback
    def _schedule_entry_reload(self) -> None:
        """Schedule a config entry reload from within the update cycle.

        Never await async_reload() directly inside _async_update_data: the
        unload path waits for the in-flight coordinator refresh, which is
        itself waiting on the reload — a mutual deadlock that leaves the
        entry stuck in unload_in_progress.
        """

        async def _deferred_reload() -> None:
            await asyncio.sleep(self.ENTRY_RELOAD_DELAY_SECONDS)
            await self.hass.config_entries.async_reload(self._config_entry_id)

        self.hass.async_create_task(_deferred_reload())

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # Dynamically adjust update interval based on consecutive failures
        if self._consecutive_failures >= 5:
            _LOGGER.warning(
                "Too many consecutive failures (%d), increasing update interval to 1 hour",
                self._consecutive_failures
            )
            self.update_interval = timedelta(hours=1)
        elif self._consecutive_failures >= 3:
            _LOGGER.warning(
                "Multiple consecutive failures (%d), increasing update interval to 30 minutes",
                self._consecutive_failures
            )
            self.update_interval = timedelta(minutes=30)
        else:
            # Normal update interval
            self.update_interval = timedelta(
                seconds=self._config[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
            )

        self._update_states()
        # _LOGGER.debug("Coordinator update interval: %d", self.update_interval.seconds)
        _LOGGER.debug("Coordinator update started (consecutive failures: %d)", self._consecutive_failures)
        start_time = time.time()


        metering_point_data = {}
        config_entry_need_update = False

        # Check session validity before doing any data fetching
        session_ok = await self._async_refresh_client()
        if not session_ok:
            # Session expired: extend interval, return SESSION_EXPIRED sentinel
            # so sensors preserve last known value instead of going unavailable
            if self._consecutive_failures >= 5:
                self.update_interval = timedelta(hours=6)
            elif self._consecutive_failures >= 3:
                self.update_interval = timedelta(hours=2)
            else:
                self.update_interval = timedelta(minutes=30)
            self._consecutive_failures += 1
            _LOGGER.warning(
                "Session expired, will retry in %s (failure #%d)",
                self.update_interval,
                self._consecutive_failures
            )

            # Auto-reload integration after consecutive session failures
            if self._consecutive_failures >= self.AUTO_RELOAD_FAILURE_THRESHOLD:
                _LOGGER.warning(
                    "Reached auto-reload threshold (%d consecutive failures), "
                    "reloading integration to reinitialize session",
                    self._consecutive_failures,
                )
                self._consecutive_failures = 0
                self._schedule_entry_reload()
                # Return sentinel — reload will trigger a fresh update cycle
                return {CSGCoordinator.SESSION_EXPIRED: True}

            # Return sentinel — all sensors will retain their last state
            return {CSGCoordinator.SESSION_EXPIRED: True}

        new_config = self._config.copy()
        for account_number, account_data in self._config[CONF_ELE_ACCOUNTS].items():
            self._gathered_data[account_number] = {}
            account = CSGElectricityAccount.load(account_data)
            # handling the addition of metering point number
            if not account.metering_point_number:
                if not metering_point_data:
                    ok, data = await self._async_fetch_with_retry(
                        self._client.api_get_metering_point,
                        account.area_code,
                        account.ele_customer_id,
                    )
                    if ok:
                        metering_point_data = data
                if metering_point_data:
                    for mp in metering_point_data:
                        if mp["eleCustNumber"] == account.account_number:
                            config_entry_need_update = True
                            account.metering_point_number = mp[
                                JSON_KEY_METERING_POINT_NUMBER
                            ]
                            new_config[CONF_ELE_ACCOUNTS][
                                account_number
                            ] = account.dump()
                            break

            await self._async_update_account_data(account)
        if config_entry_need_update:
            new_config[CONF_UPDATED_AT] = str(int(time.time() * 1000))
            self.hass.config_entries.async_update_entry(
                self.hass.config_entries.async_get_entry(self._config_entry_id),
                data=new_config,
            )
            _LOGGER.debug("Updated accounts with metering point number")
        _LOGGER.debug("Coordinator update took %s seconds", time.time() - start_time)
        self.hass.data[DOMAIN][self._config_entry_id][
            DATA_KEY_LAST_UPDATE_DAY
        ] = self._this_day

        # All data fetched successfully — check if we also need periodic reload
        # to prevent session staleness (南网 session typically expires after ~24h)
        self._consecutive_successes = getattr(self, '_consecutive_successes', 0) + 1
        PERIODIC_RELOAD_SUCCESS_COUNT = 6  # ~24h at 4h default interval
        if self._consecutive_successes >= PERIODIC_RELOAD_SUCCESS_COUNT:
            _LOGGER.info(
                "Periodic reload: %d successful updates, reloading to refresh session",
                self._consecutive_successes,
            )
            self._consecutive_successes = 0
            self._schedule_entry_reload()

        return self._gathered_data
