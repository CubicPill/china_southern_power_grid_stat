"""The China Southern Power Grid Statistics integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from csg_client import CSGAPIError, CSGClient, NotLoggedIn
from .const import (
    CONF_ACCOUNT_NUMBER,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


class CSGCoordinator(DataUpdateCoordinator):
    """CSG custom coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry_id: str):
        """Initialize coordinator."""
        config = hass.data[DOMAIN][config_entry_id]
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=f"CSG Client {config[CONF_ACCOUNT_NUMBER]}",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=config[CONF_UPDATE_INTERVAL]),
        )
        self.config_entry_id = config_entry_id

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """

        def csg_fetch_all():
            pass

        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(20):
                return await self.hass.async_add_executor_job(csg_fetch_all)
        except NotLoggedIn as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except CSGAPIError as err:
            raise UpdateFailed(f"Error communicating with API: {err}")


async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up China Southern Power Grid Statistics from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][entry.entry_id] = hass_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][entry.entry_id]["unsub_options_update_listener"]()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
