"""The China Southern Power Grid Statistics integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from copy import deepcopy
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .csg_client import (
    CSGAPIError,
    CSGClient,
    NotLoggedIn,
    InvalidCredentials,
    CSGElectricityAccount,
)
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    CONF_ACCOUNTS,
    VALUE_CSG_LOGIN_TYPE_PWD,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


class CSGCoordinator(DataUpdateCoordinator):
    """CSG custom coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry_id: str):
        """Initialize coordinator."""
        self._config_entry_id = config_entry_id
        config = hass.data[DOMAIN][config_entry_id]
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=f"CSG Account {config[CONF_ACCOUNT_NUMBER]}",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=config[CONF_UPDATE_INTERVAL]),
        )

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        def csg_fetch_all():
            # restore session or re-auth
            client = CSGClient()
            config = self.hass.data[DOMAIN][self._config_entry_id]

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
            self.hass.data[DOMAIN][self._config_entry_id][CONF_AUTH_TOKEN] = dumped[
                CONF_AUTH_TOKEN
            ]

            # fetch data for each account
            data_ret = {}
            for account_number, account_data in config[CONF_ACCOUNTS].items():
                account = CSGElectricityAccount()
                account.load(account_data)
                bal, arr = client.get_balance_and_arrears(account)
                year_month_stats = client.get_year_month_stats(account)
                month_daily_usage = client.get_month_daily_usage_detail(account)
                data_ret[account_number] = {
                    "balance": bal,
                    "arrears": arr,
                    "year_total_charge": year_month_stats["year_total_charge"],
                    "year_total_kwh": year_month_stats["year_total_kwh"],
                    "by_month": year_month_stats["by_month"],
                    "month_total": month_daily_usage["month_total"],
                    "by_day": month_daily_usage["by_day"],
                }
            return data_ret

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(20):
                return await self.hass.async_add_executor_job(csg_fetch_all)
        except InvalidCredentials as err:
            raise ConfigEntryAuthFailed from err
        except NotLoggedIn as err:
            raise UpdateFailed(f"Session invalidated unexpectedly") from err
        except CSGAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}")


async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> bool:
    """Set up China Southern Power Grid Statistics from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][entry.entry_id] = hass_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator = CSGCoordinator(hass, entry.entry_id)

    await coordinator.async_config_entry_first_refresh()

    # async_add_entities(
    #         MyEntity(coordinator, idx) for idx, ent in enumerate(coordinator.data)
    # )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][entry.entry_id]["unsub_options_update_listener"]()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
