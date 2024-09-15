"""helper functions"""
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import CONF_AUTH_TOKEN, CONF_ELE_ACCOUNTS, CONF_UPDATED_AT, CONF_VERIFICATION_CODE
from .csg_client import CSGClient, InvalidCredentials

_LOGGER = logging.getLogger(__name__)


async def async_refresh_login_and_update_config(
    client: CSGClient, hass: HomeAssistant, entry: ConfigEntry
) -> CSGClient:
    """config data could change after calling this function"""
    try:
        await hass.async_add_executor_job(
            client.authenticate,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_VERIFICATION_CODE],
        )
    except InvalidCredentials as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    accounts = await hass.async_add_executor_job(client.get_all_electricity_accounts)

    dumped = client.dump()
    new_data = entry.data.copy()
    new_data[CONF_AUTH_TOKEN] = dumped[CONF_AUTH_TOKEN]

    # update account data
    for account in accounts:
        if account.account_number in new_data[CONF_ELE_ACCOUNTS]:
            new_data[CONF_ELE_ACCOUNTS][account.account_number] = account.dump()

    new_data[CONF_UPDATED_AT] = int(time.time() * 1000)
    hass.config_entries.async_update_entry(
        entry,
        data=new_data,
    )
    _LOGGER.info(
        "Account login refreshed: %s",
        entry.data[CONF_USERNAME],
    )
    return client
