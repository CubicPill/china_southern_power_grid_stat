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
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError


from .const import DOMAIN
from .csg_client import CSGWebClient, CSGAPIError
from requests import RequestException

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
) -> CSGWebClient | None:
    """
    Validate the credentials (login)
    """

    authenticate_result = await hass.async_add_executor_job(
        authenticate_csg, data["username"], data["password"]
    )
    if not authenticate_result["ok"]:
        if authenticate_result["reason"] == "wrong_cred":
            raise InvalidAuth
        elif authenticate_result["reason"] == "network":
            raise CannotConnect
        else:
            # won't reach here
            pass

    # Return the client object
    return authenticate_result["data"]


class CSGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for China Southern Power Grid Statistics."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Handle the initial step.
        Login and get all electricity accounts for later use
        """
        schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        errors = {}

        try:
            result = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return await self.async_step_select_account()

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_select_account(self, user_input: str = None) -> FlowResult:
        """Let user select specific electricity account"""

        all_accounts = []
        schema = vol.Schema({vol.Required("account_no"): vol.In([all_accounts])})
        if user_input is None:
            return self.async_show_form(step_id="select_account", data_schema=schema)

        await self.async_set_unique_id(user_input["account_no"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f'CSG{user_input["account_no"]}', data={})


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
