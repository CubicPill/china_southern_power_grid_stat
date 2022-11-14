"""
Config flow for China Southern Power Grid Statistics integration.
Steps:
1. User input account credentials (username and password), the validity of credential verified
2. Get all electricity accounts linked to the user account, let user select one of them
3. Get the rest of needed parameters and save the config entries
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from requests import RequestException

from .const import (CONF_ACCOUNTS, CONF_AUTH_TOKEN, CONF_LOGIN_TYPE, CONF_SETTINGS, CONF_UPDATE_INTERVAL,
                    DEFAULT_UPDATE_INTERVAL, DOMAIN, STEP_ADD_ACCOUNT, STEP_DELETE_ACCOUNT, STEP_SETTINGS)
from .csg_client import CSGClient, CSGElectricityAccount, InvalidCredentials

_LOGGER = logging.getLogger(__name__)


def authenticate_csg(username: str, password: str) -> CSGClient:
    """use username and password combination to authenticate"""
    client = CSGClient()
    try:
        client.authenticate(username, password)
    except InvalidCredentials as exc:
        raise InvalidAuth from exc
    except RequestException as exc:
        raise CannotConnect from exc
    else:
        return client


async def validate_input(
    hass: HomeAssistant, data: dict[str, str]
) -> dict[str, Any] | None:
    """Validate the credentials (login)"""

    client = await hass.async_add_executor_job(
        authenticate_csg, data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    return client.dump_session()


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
            return self.async_create_entry(
                title=f"CSG-{user_input[CONF_USERNAME]}",
                data={
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_AUTH_TOKEN: session_data[CONF_AUTH_TOKEN],
                    CONF_LOGIN_TYPE: session_data[CONF_LOGIN_TYPE],
                    CONF_ACCOUNTS: {},
                    CONF_SETTINGS: {CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL},
                },
            )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class CSGOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for China Southern Power Grid Statistics."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.all_electricity_accounts: list[CSGElectricityAccount] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        schema = vol.Schema(
            {
                vol.Required("action", default="add_account"): vol.In(
                    [
                        STEP_ADD_ACCOUNT,
                        STEP_DELETE_ACCOUNT,
                        STEP_SETTINGS,
                    ]
                ),
            }
        )
        if user_input:
            if user_input["action"] == STEP_ADD_ACCOUNT:
                return await self.async_step_select_account()
            if user_input["action"] == STEP_DELETE_ACCOUNT:
                return await self.async_step_delete_account()
            if user_input["action"] == STEP_SETTINGS:
                return await self.async_step_settings()
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_select_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select one of the electricity accounts from current account"""
        # account_no: f'{account_no} ({name} {addr})'

        schema_no_selections = vol.Schema(
            {
                vol.Required("account_number"): vol.In(["no_account"]),
            }
        )
        if user_input:
            electricity_account_number = user_input["account_number"]
            for account in self.all_electricity_accounts:
                if account.account_number == electricity_account_number:
                    # store the account config in main entry instead of creating new entries
                    new_data = self.config_entry.data.copy()
                    new_data[CONF_ACCOUNTS][electricity_account_number] = account.dump()
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=new_data,
                    )
                    # no separate entry created
                    return self.async_create_entry(
                        title="",
                        data={},
                    )

        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        client: CSGClient | None = None
        for entry in all_entries:
            if entry.data.get(CONF_AUTH_TOKEN):
                client = CSGClient()
                client.restore_session(
                    {
                        CONF_AUTH_TOKEN: entry.data[CONF_AUTH_TOKEN],
                        CONF_LOGIN_TYPE: entry.data[CONF_LOGIN_TYPE],
                    }
                )
                logged_in = await self.hass.async_add_executor_job(client.verify_login)
                if not logged_in:
                    # token expired, re-authenticate
                    await self.hass.async_add_executor_job(
                        client.authenticate,
                        entry.data[CONF_USERNAME],
                        entry.data[CONF_PASSWORD],
                    )
                await self.hass.async_add_executor_job(client.initialize)
                break
        if not client:
            return self.async_show_form(
                step_id="select_account",
                data_schema=schema_no_selections,
                errors={"base": "no_config"},
            )
        accounts = await self.hass.async_add_executor_job(
            client.get_all_electricity_accounts
        )
        self.all_electricity_accounts = accounts

        selections = {}
        for account in accounts:
            selections[
                account.account_number
            ] = f"{account.account_number} {account.user_name} {account.address}"

        schema = vol.Schema(
            {
                vol.Required("account_number"): vol.In(selections),
            }
        )
        return self.async_show_form(
            step_id="select_account",
            data_schema=schema,
        )

    async def async_step_delete_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        raise NotImplementedError

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:

        raise NotImplementedError


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
