# -*- coding: utf-8 -*-
"""The China Southern Power Grid Statistics integration."""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_UPDATED_AT,
    DATA_KEY_UNSUB_UPDATE_LISTENER,
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

    # validate session, re-authenticate if needed
    client = CSGClient.load(
        {
            CONF_AUTH_TOKEN: entry.data[CONF_AUTH_TOKEN],
            CONF_LOGIN_TYPE: VALUE_CSG_LOGIN_TYPE_PWD,
        }
    )
    if not await hass.async_add_executor_job(client.verify_login):
        try:
            await hass.async_add_executor_job(
                client.authenticate,
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
            )
        except InvalidCredentials as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        dumped = client.dump()
        new_data = entry.data.copy()
        new_data[CONF_AUTH_TOKEN] = dumped[CONF_AUTH_TOKEN]
        new_data[CONF_UPDATED_AT] = int(time.time() * 1000)
        # this will not trigger update listener
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
        )
        _LOGGER.info(
            "Account login refreshed: %s",
            entry.data[CONF_USERNAME],
        )
    # Registers update listener to update config entry when options are updated.
    unsub_update_listener = entry.add_update_listener(update_listener)
    # Store a reference to the unsubscribe function to clean up if an entry is unloaded.

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_KEY_UNSUB_UPDATE_LISTENER: unsub_update_listener
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][entry.entry_id][DATA_KEY_UNSUB_UPDATE_LISTENER]()

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
