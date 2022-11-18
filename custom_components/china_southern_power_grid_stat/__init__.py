# -*- coding: utf-8 -*-
"""The China Southern Power Grid Statistics integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    DOMAIN,
    VALUE_CSG_LOGIN_TYPE_PWD,
)
from .csg_client import (
    CSGAPIError,
    CSGClient,
    CSGElectricityAccount,
    InvalidCredentials,
    NotLoggedIn,
)
from .sensor import (
    CSGCostSensor,
    CSGEnergySensor,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.info("Reloading entry")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up China Southern Power Grid Statistics from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass_data = dict(entry.data)
    # Registers update listener to update config entry when options are updated.
    unsub_update_listener = entry.add_update_listener(update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.

    hass.data[DOMAIN][entry.entry_id] = {"unsub_update_listener": unsub_update_listener}

    hass_data["unsub_update_listener"] = unsub_update_listener
    hass.data[DOMAIN][entry.entry_id] = hass_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][entry.entry_id]["unsub_update_listener"]()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    _LOGGER.info("Removing entry: account %s", entry.data[CONF_USERNAME])

    # logout
    def client_logout():
        client = CSGClient.load(
            {
                CONF_AUTH_TOKEN: entry.data[CONF_AUTH_TOKEN],
                CONF_LOGIN_TYPE: VALUE_CSG_LOGIN_TYPE_PWD,
            }
        )
        if client.verify_login():
            client.logout()
            _LOGGER.info("CSG account %s logged out", entry.data[CONF_USERNAME])

    await hass.async_add_executor_job(client_logout)
