"""Sensors for the China Southern Power Grid Statistics integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import async_timeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    ENERGY_KILO_WATT_HOUR,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    ATTR_KEY_MONTH_BY_DAY,
    ATTR_KEY_YEAR_BY_MONTH,
    CONF_ACCOUNTS,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_TIMEOUT,
    DOMAIN,
    SUFFIX_ARR,
    SUFFIX_BAL,
    SUFFIX_MONTH_KWH,
    SUFFIX_YEAR_COST,
    SUFFIX_YEAR_KWH,
    VALUE_CSG_LOGIN_TYPE_PWD,
)
from .csg_client import (
    CSGAPIError,
    CSGClient,
    CSGElectricityAccount,
    InvalidCredentials,
    NotLoggedIn,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensors from a config entry created in the integrations UI."""
    if not config_entry.data[CONF_ACCOUNTS]:
        _LOGGER.info("No accounts in config, exit entry setup")
        return

    coordinator = CSGCoordinator(hass, config_entry.entry_id)

    all_sensors = []
    for account_number, account_data in config_entry.data[CONF_ACCOUNTS].items():
        account = CSGElectricityAccount()
        account.load(account_data)

        sensors = [
            # balance
            CSGCostSensor(coordinator, account_number, SUFFIX_BAL),
            # arrears
            CSGCostSensor(coordinator, account_number, SUFFIX_ARR),
            # this year's total energy, with extra attributes about monthly usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_YEAR_KWH,
                extra_state_attributes_key=ATTR_KEY_YEAR_BY_MONTH,
            ),
            # this year's total cost
            CSGCostSensor(
                coordinator,
                account_number,
                SUFFIX_YEAR_COST,
            ),
            # this month's total energy, with extra attributes about daily usage
            CSGEnergySensor(
                coordinator,
                account_number,
                SUFFIX_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_MONTH_BY_DAY,
            ),
        ]

        all_sensors.extend(sensors)

    async_add_entities(all_sensors)

    await coordinator.async_config_entry_first_refresh()


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
        _LOGGER.info(
            "Ele account %s, sensor %s, coordinator update triggered",
            self._account_number,
            self._entity_suffix,
        )
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

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        config = dict(
            self.hass.config_entries.async_get_entry(self._config_entry_id).data
        )

        def csg_fetch_all():

            # restore session or re-auth
            client = CSGClient()

            if not config[CONF_ACCOUNTS]:
                # no linked ele accounts
                return {}

            client.restore_session(
                {
                    CONF_AUTH_TOKEN: config[CONF_AUTH_TOKEN],
                    CONF_LOGIN_TYPE: VALUE_CSG_LOGIN_TYPE_PWD,
                }
            )
            if not client.verify_login():
                # expired session
                client.authenticate(config[CONF_USERNAME], config[CONF_PASSWORD])
            client.initialize()

            # save new access token
            dumped = client.dump_session()
            config[CONF_AUTH_TOKEN] = dumped[CONF_AUTH_TOKEN]
            self.hass.config_entries.async_update_entry(
                self.hass.config_entries.async_get_entry(self._config_entry_id),
                data=config,
            )

            # fetch data for each account
            data_ret = {}
            for account_number, account_data in config[CONF_ACCOUNTS].items():
                account = CSGElectricityAccount()
                account.load(account_data)
                bal, arr = client.get_balance_and_arrears(account)
                year_month_stats = client.get_year_month_stats(account)
                month_daily_usage = client.get_month_daily_usage_detail(account)
                data_ret[account_number] = {
                    SUFFIX_BAL: bal,
                    SUFFIX_ARR: arr,
                    SUFFIX_YEAR_KWH: year_month_stats["year_total_kwh"],
                    SUFFIX_YEAR_COST: year_month_stats["year_total_charge"],
                    ATTR_KEY_YEAR_BY_MONTH: year_month_stats,
                    SUFFIX_MONTH_KWH: month_daily_usage["month_total_kwh"],
                    ATTR_KEY_MONTH_BY_DAY: month_daily_usage,
                }
            _LOGGER.info("Coordinator update done!")
            return data_ret

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(
                config[CONF_SETTINGS][CONF_UPDATE_TIMEOUT]
            ):
                return await self.hass.async_add_executor_job(csg_fetch_all)
        except InvalidCredentials as err:
            raise ConfigEntryAuthFailed from err
        except NotLoggedIn as err:
            raise UpdateFailed("Session invalidated unexpectedly") from err
        except CSGAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
