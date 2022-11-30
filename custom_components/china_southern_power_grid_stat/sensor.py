"""Sensors for the China Southern Power Grid Statistics integration."""
from __future__ import annotations

import asyncio
import datetime
import logging
from datetime import timedelta
from typing import Any

import async_timeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_USERNAME,
    ENERGY_KILO_WATT_HOUR,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    ATTR_KEY_LAST_MONTH_BY_DAY,
    ATTR_KEY_LAST_YEAR_BY_MONTH,
    ATTR_KEY_LATEST_DAY_DATE,
    ATTR_KEY_THIS_MONTH_BY_DAY,
    ATTR_KEY_THIS_YEAR_BY_MONTH,
    CONF_ACCOUNTS,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_TIMEOUT,
    DATA_KEY_LAST_UPDATE_DAY,
    DOMAIN,
    STATE_UPDATE_UNCHANGED,
    SUFFIX_ARR,
    SUFFIX_BAL,
    SUFFIX_LAST_MONTH_KWH,
    SUFFIX_LAST_YEAR_COST,
    SUFFIX_LAST_YEAR_KWH,
    SUFFIX_LATEST_DAY_KWH,
    SUFFIX_THIS_MONTH_KWH,
    SUFFIX_THIS_YEAR_COST,
    SUFFIX_THIS_YEAR_KWH,
    SUFFIX_YESTERDAY_KWH,
    VALUE_CSG_LOGIN_TYPE_PWD,
)
from .csg_client import (
    CSGAPIError,
    CSGClient,
    CSGElectricityAccount,
    NotLoggedIn,
)
from .utils import async_refresh_login_and_update_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensors from a config entry created in the integrations UI."""
    if not config_entry.data[CONF_ACCOUNTS]:
        _LOGGER.info("No ele accounts in config, exit entry setup")
        return
    coordinator = CSGCoordinator(hass, config_entry.entry_id)

    all_sensors = []
    for account_number, _ in config_entry.data[CONF_ACCOUNTS].items():
        sensors = [
            # balance
            CSGCostSensor(coordinator, account_number, SUFFIX_BAL),
            # arrears
            CSGCostSensor(coordinator, account_number, SUFFIX_ARR),
            # yesterday kwh
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_YESTERDAY_KWH,
            ),
            # latest day data is available, with extra attributes about the date
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_LATEST_DAY_KWH,
                extra_state_attributes_key=ATTR_KEY_LATEST_DAY_DATE,
            ),
            # this year's total energy, with extra attributes about monthly usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_THIS_YEAR_KWH,
                extra_state_attributes_key=ATTR_KEY_THIS_YEAR_BY_MONTH,
            ),
            # this year's total cost
            CSGCostSensor(
                coordinator,
                account_number,
                SUFFIX_THIS_YEAR_COST,
            ),
            # this month's total energy, with extra attributes about daily usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_THIS_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_THIS_MONTH_BY_DAY,
            ),
            # last year's total energy, with extra attributes about monthly usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_LAST_YEAR_KWH,
                extra_state_attributes_key=ATTR_KEY_LAST_YEAR_BY_MONTH,
            ),
            # last year's total cost
            CSGCostSensor(
                coordinator,
                account_number,
                SUFFIX_LAST_YEAR_COST,
            ),
            # last month's total energy, with extra attributes about daily usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_LAST_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_LAST_MONTH_BY_DAY,
            ),
        ]

        all_sensors.extend(sensors)

    async_add_entities(all_sensors)

    await coordinator.async_refresh()


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
        _LOGGER.debug(
            "Ele account %s, sensor %s, coordinator update triggered",
            self._account_number,
            self._entity_suffix,
        )

        if not self._coordinator.data:
            _LOGGER.error("Coordinator has no data")
            self._attr_native_value = STATE_UNAVAILABLE
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        account_data = self._coordinator.data.get(self._account_number)
        if account_data is None:
            _LOGGER.warning(
                "Ele account %s not found in coordinator data", self._account_number
            )
            self._attr_native_value = STATE_UNAVAILABLE
            self._attr_extra_state_attributes = {}
            self.async_write_ha_state()
            return

        new_native_value = account_data.get(self._entity_suffix)
        if new_native_value is None:
            new_native_value = STATE_UNAVAILABLE
            _LOGGER.warning(
                "Ele account %s, sensor %s, data not found in coordinator data",
                self._account_number,
                self._entity_suffix,
            )
        elif new_native_value == STATE_UPDATE_UNCHANGED:
            # no update for this sensor, skip
            _LOGGER.debug(
                "Sensor %s_%s doesn't need to be updated, skip",
                self._account_number,
                self._entity_suffix,
            )
            # self.async_write_ha_state()
            return
        self._attr_native_value = new_native_value

        if self._extra_state_attributes_key:
            new_attributes = account_data.get(self._extra_state_attributes_key)
            if new_attributes is None:
                new_attributes = {}
                _LOGGER.warning(
                    "Ele account %s, sensor %s, attribute %s not found in coordinator data",
                    self._account_number,
                    self._entity_suffix,
                    self._extra_state_attributes_key,
                )
            self._attr_extra_state_attributes = new_attributes
        _LOGGER.debug(
            "Sensor %s_%s update done!",
            self._account_number,
            self._entity_suffix,
        )
        self.async_write_ha_state()


class CSGEnergySensor(CSGBaseSensor):
    """Representation of a CSG Energy Sensor."""

    _attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:lightning-bolt"


class CSGCostSensor(CSGBaseSensor):
    """Representation of a CSG Cost Sensor."""

    _attr_native_unit_of_measurement = "CNY"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-cny"


class CSGCoordinator(DataUpdateCoordinator):
    """CSG custom coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry_id: str) -> None:
        """Initialize coordinator."""
        self._config_entry_id = config_entry_id
        config = hass.config_entries.async_get_entry(self._config_entry_id).data
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=f"CSG Account {config[CONF_USERNAME]}",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(
                seconds=config[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        config = dict(
            self.hass.config_entries.async_get_entry(self._config_entry_id).data
        )

        self.update_interval = timedelta(
            seconds=config[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
        )
        _LOGGER.debug("Coordinator update interval: %d", self.update_interval.seconds)
        _LOGGER.debug("Coordinator update started")

        def _safe_fetch(func: callable, num_ret: int, *args, **kwargs):
            if num_ret == 1:
                ret = STATE_UNAVAILABLE
            else:
                ret = [STATE_UNAVAILABLE] * num_ret

            try:
                ret = func(*args, **kwargs)
            except CSGAPIError as err:
                _LOGGER.error(
                    "Error fetching data in coordinator: function %s, %s",
                    func.__name__,
                    err,
                )

            if num_ret == 1:
                # only one return value
                return ret
            if len(ret) != num_ret:
                raise ValueError(
                    f"Number of return args doesn't match, expected: {num_ret}, got: {len(ret)}"
                )
            return ret

        def csg_fetch_all() -> dict:

            if not config[CONF_ACCOUNTS]:
                # no linked ele accounts
                _LOGGER.info("No ele account linked, skip coordinator update")
                return {}
            client = CSGClient.load(
                {
                    CONF_AUTH_TOKEN: config[CONF_AUTH_TOKEN],
                    CONF_LOGIN_TYPE: VALUE_CSG_LOGIN_TYPE_PWD,
                }
            )
            if not client.verify_login():
                # expired session

                client = asyncio.get_event_loop().run_until_complete(
                    async_refresh_login_and_update_config(
                        client, self.hass, self.config_entry
                    )
                )

            client.initialize()

            # fetch data for each account
            data_ret = {}
            current_dt = datetime.datetime.now()
            this_year, this_month, this_day = (
                current_dt.year,
                current_dt.month,
                current_dt.day,
            )
            last_year, last_month = this_year - 1, this_month - 1

            # for last month and last year data, they won't change over a long period of time - so we could use cache
            #
            # update policy for last month:
            # for the first 5 days of a month, update every `update_interval`
            # for the rest of the time, do not update

            # update policy for last year:
            # for the first 5 days of Jan, update daily at first update
            # for the rest of the time, do not update
            #
            # when integration is reloaded, all updates will be triggered
            # so user could just reload the integration to refresh the data if needed

            if (
                self.hass.data[DOMAIN][self._config_entry_id].get(
                    DATA_KEY_LAST_UPDATE_DAY
                )
                is None
            ):
                # first update
                update_last_month = True
                update_last_year = True
                _LOGGER.info(
                    "First update for account %s, getting all past data",
                    config[CONF_USERNAME],
                )
            else:
                update_last_month = False
                update_last_year = False

                if this_day <= 5:
                    update_last_month = True
                today_first_update_triggered = (
                    self.hass.data[DOMAIN][self._config_entry_id][
                        DATA_KEY_LAST_UPDATE_DAY
                    ]
                    == this_day
                )
                if this_month == 1 and this_day <= 5:
                    if not today_first_update_triggered:
                        update_last_year = True

            for account_number, account_data in config[CONF_ACCOUNTS].items():

                account = CSGElectricityAccount.load(account_data)

                bal, arr = _safe_fetch(client.get_balance_and_arrears, 2, account)

                yesterday_kwh = _safe_fetch(client.get_yesterday_kwh, 1, account)

                (
                    this_year_cost,
                    this_year_kwh,
                    this_year_by_month,
                ) = _safe_fetch(client.get_year_month_stats, 3, account, this_year)

                this_month_kwh, this_month_by_day = _safe_fetch(
                    client.get_month_daily_usage_detail,
                    2,
                    account,
                    (this_year, this_month),
                )

                if update_last_year:
                    (
                        last_year_cost,
                        last_year_kwh,
                        last_year_by_month,
                    ) = _safe_fetch(client.get_year_month_stats, 3, account, last_year)
                else:
                    last_year_cost, last_year_kwh, last_year_by_month = (
                        STATE_UPDATE_UNCHANGED,
                        STATE_UPDATE_UNCHANGED,
                        STATE_UPDATE_UNCHANGED,
                    )
                    _LOGGER.info(
                        "Account %s, skipping getting last year data",
                        config[CONF_USERNAME],
                    )
                if (
                    update_last_month
                    or (not this_month_by_day)
                    or (this_month_by_day == STATE_UNAVAILABLE)
                ):
                    # either at the beginning of this month or this month's data hasn't been available yet
                    # in normal cases the second condition will become false earlier than the first one
                    (last_month_kwh, last_month_by_day,) = _safe_fetch(
                        client.get_month_daily_usage_detail,
                        2,
                        account,
                        (this_year, last_month),
                    )

                else:
                    last_month_kwh, last_month_by_day = (
                        STATE_UPDATE_UNCHANGED,
                        STATE_UPDATE_UNCHANGED,
                    )
                    _LOGGER.info(
                        "Account %s, skipping getting last month data",
                        config[CONF_USERNAME],
                    )

                # TODO refactor these logics
                if (
                    this_month_by_day == STATE_UNAVAILABLE
                    and last_month_by_day == STATE_UNAVAILABLE
                ):
                    latest_day_kwh = STATE_UNAVAILABLE
                    latest_day_date = STATE_UNAVAILABLE
                else:
                    if (
                        this_month_by_day != STATE_UNAVAILABLE
                        and len(this_month_by_day) >= 1
                    ):
                        latest_day_kwh = this_month_by_day[-1]["kwh"]
                        latest_day_date = this_month_by_day[-1]["date"]
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
                            latest_day_kwh = last_month_by_day[-1]["kwh"]
                            latest_day_date = last_month_by_day[-1]["date"]
                        else:
                            _LOGGER.error(
                                "Account %s, no latest day data available",
                                config[CONF_USERNAME],
                            )
                            latest_day_kwh = STATE_UNAVAILABLE
                            latest_day_date = STATE_UNAVAILABLE

                data_ret[account_number] = {
                    SUFFIX_BAL: bal,
                    SUFFIX_ARR: arr,
                    SUFFIX_YESTERDAY_KWH: yesterday_kwh,
                    SUFFIX_LATEST_DAY_KWH: latest_day_kwh,
                    ATTR_KEY_LATEST_DAY_DATE: {
                        ATTR_KEY_LATEST_DAY_DATE: latest_day_date
                    },
                    SUFFIX_THIS_YEAR_KWH: this_year_kwh,
                    SUFFIX_THIS_YEAR_COST: this_year_cost,
                    ATTR_KEY_THIS_YEAR_BY_MONTH: {
                        ATTR_KEY_THIS_YEAR_BY_MONTH: this_year_by_month
                    },
                    SUFFIX_LAST_YEAR_KWH: last_year_kwh,
                    SUFFIX_LAST_YEAR_COST: last_year_cost,
                    ATTR_KEY_LAST_YEAR_BY_MONTH: {
                        ATTR_KEY_LAST_YEAR_BY_MONTH: last_year_by_month
                    },
                    SUFFIX_THIS_MONTH_KWH: this_month_kwh,
                    ATTR_KEY_THIS_MONTH_BY_DAY: {
                        ATTR_KEY_THIS_MONTH_BY_DAY: this_month_by_day
                    },
                    SUFFIX_LAST_MONTH_KWH: last_month_kwh,
                    ATTR_KEY_LAST_MONTH_BY_DAY: {
                        ATTR_KEY_LAST_MONTH_BY_DAY: last_month_by_day
                    },
                }
            _LOGGER.info("Coordinator %s update done!", config[CONF_USERNAME])
            self.hass.data[DOMAIN][self._config_entry_id][
                DATA_KEY_LAST_UPDATE_DAY
            ] = this_day
            return data_ret

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(
                config[CONF_SETTINGS][CONF_UPDATE_TIMEOUT]
            ):
                return await self.hass.async_add_executor_job(csg_fetch_all)
        except NotLoggedIn as err:
            raise UpdateFailed("Session invalidated unexpectedly") from err
        except CSGAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            _LOGGER.error("Unexpected exception: %s", err)
            raise UpdateFailed(f"Unexpected exception: {err}") from err
