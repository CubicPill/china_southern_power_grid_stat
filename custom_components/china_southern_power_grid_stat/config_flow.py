"""
Config flow for China Southern Power Grid Statistics integration.
Steps:
1. User input account credentials (username and password), the validity of credential verified
2. Get all electricity accounts bound to the user account, let user select one of them
3. Get the rest of needed parameters and save the config entries
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (CONF_PASSWORD, CONF_USERNAME)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from requests import RequestException

from .const import (CONF_AUTH_TOKEN, CONF_LOGIN_TYPE, DOMAIN)
from .csg_client import CSGAPIError, CSGWebClient

_LOGGER = logging.getLogger(__name__)


def authenticate_csg(username: str, password: str) -> dict[str, Any]:
    client = CSGWebClient()
    try:
        client.authenticate(username, password)
    except CSGAPIError:
        return {"ok": False, "reason": "wrong_cred"}
    except RequestException:
        return {"ok": False, "reason": "network"}
    else:
        return {"ok": True, "reason": None, "data": client}


async def validate_input(
        hass: HomeAssistant, data: dict[str, str]
) -> dict[str, Any] | None:
    """
    Validate the credentials (login)
    """

    authenticate_result = await hass.async_add_executor_job(
            authenticate_csg, data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    if not authenticate_result["ok"]:
        if authenticate_result["reason"] == "wrong_cred":
            raise InvalidAuth
        elif authenticate_result["reason"] == "network":
            raise CannotConnect
        else:
            # won't reach here
            pass

    client: CSGWebClient = authenticate_result["data"]
    return client.dump()


class CSGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for China Southern Power Grid Statistics."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
            config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return CSGOptionsFlowHandler(config_entry)

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Handle the initial step.
        Login and get all electricity accounts for later use
        """
        schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
        )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        errors = {}

        try:
            session_data = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_USERNAME], data={
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_AUTH_TOKEN: session_data[CONF_AUTH_TOKEN],
                CONF_LOGIN_TYPE: session_data[CONF_LOGIN_TYPE]
            })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # async def async_step_select_account(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    #     """Let user select specific electricity account"""
    #
    #     all_accounts = []
    #     schema = vol.Schema({vol.Required(CONF_ACCOUNT_NUMBER): vol.In([all_accounts])})
    #     if user_input is None:
    #         return self.async_show_form(step_id="select_account", data_schema=schema)
    #
    #     await self.async_set_unique_id(user_input[CONF_ACCOUNT_NUMBER])
    #     self._abort_if_unique_id_configured()
    #     return self.async_create_entry(title=f'CSG{user_input[CONF_ACCOUNT_NUMBER]}', data={})
    #


class CSGOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for China Southern Power Grid Statistics."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        schema = vol.Schema({
            vol.Required('action', default='add_account'): vol.In({'add_account': "Add account"}),
        })
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                        {
                            vol.Required(
                                    "show_things",
                                    default=self.config_entry.options.get("show_things"),
                            ): bool
                        }
                ),
        )

    async def async_step_select_account(self, user_input: dict[str, Any] | None = None):
        # account_no: f'{account_no} ({name} {addr})'
        all_accounts = {}

        schema = vol.Schema({
            vol.Required('account_number', default='add_account'): vol.In(all_accounts),
        })


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
