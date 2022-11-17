# -*- coding: utf-8 -*-
"""
Config flow for China Southern Power Grid Statistics integration.
Steps:
1. User input account credentials (username and password), the validity of credential verified
2. Get all electricity accounts linked to the user account, let user select one of them
3. Get the rest of needed parameters and save the config entries
"""
from __future__ import annotations

import logging
import time
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry, entity_registry
from requests import RequestException

from .const import (
    CONF_ACCOUNTS,
    CONF_AUTH_TOKEN,
    CONF_LOGIN_TYPE,
    CONF_SETTINGS,
    CONF_UPDATED_AT,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_UPDATE_TIMEOUT,
    DOMAIN,
    STEP_ADD_ACCOUNT,
    STEP_DELETE_ACCOUNT,
    STEP_SETTINGS,
    VALUE_CSG_LOGIN_TYPE_PWD,
)
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

        await self.async_set_unique_id(user_input[CONF_USERNAME])
        self._abort_if_unique_id_configured()

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

            _LOGGER.info("Adding csg account %s", user_input[CONF_USERNAME])
            return self.async_create_entry(
                title=f"CSG-{user_input[CONF_USERNAME]}",
                data={
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_AUTH_TOKEN: session_data[CONF_AUTH_TOKEN],
                    CONF_ACCOUNTS: {},
                    CONF_SETTINGS: {
                        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                        CONF_UPDATE_TIMEOUT: DEFAULT_UPDATE_TIMEOUT,
                    },
                    CONF_UPDATED_AT: str(int(time.time() * 1000)),
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
                    {
                        STEP_ADD_ACCOUNT: "添加已绑定的缴费号",
                        STEP_DELETE_ACCOUNT: "移除缴费号实体",
                        STEP_SETTINGS: "参数设置",
                    }
                ),
            }
        )
        if user_input:
            if user_input["action"] == STEP_ADD_ACCOUNT:
                return await self.async_step_add_account()
            if user_input["action"] == STEP_DELETE_ACCOUNT:
                return await self.async_step_remove_account()
            if user_input["action"] == STEP_SETTINGS:
                return await self.async_step_settings()
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_add_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select one of the electricity accounts from current account"""
        # account_no: f'{account_no} ({name} {addr})'

        if user_input:
            account_num_to_add = user_input["account_number"]
            for account in self.all_electricity_accounts:
                if account.account_number == account_num_to_add:
                    # store the account config in main entry instead of creating new entries
                    new_data = self.config_entry.data.copy()
                    new_data[CONF_ACCOUNTS][account_num_to_add] = account.dump()
                    # this must be set or update won't be detected
                    new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=new_data,
                    )
                    _LOGGER.info(
                        "Added ele account to %s: %s",
                        self.config_entry.data[CONF_USERNAME],
                        account_num_to_add,
                    )
                    # no separate entry created
                    return self.async_create_entry(
                        title="",
                        data={},
                    )

        client = CSGClient()
        client.restore_session(
            {
                CONF_AUTH_TOKEN: self.config_entry.data[CONF_AUTH_TOKEN],
                CONF_LOGIN_TYPE: VALUE_CSG_LOGIN_TYPE_PWD,
            }
        )
        logged_in = await self.hass.async_add_executor_job(client.verify_login)
        if not logged_in:
            # token expired, re-authenticate
            await self.hass.async_add_executor_job(
                client.authenticate,
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
        await self.hass.async_add_executor_job(client.initialize)

        accounts = await self.hass.async_add_executor_job(
            client.get_all_electricity_accounts
        )
        self.all_electricity_accounts = accounts
        if not accounts:
            _LOGGER.warning(
                "No linked ele accounts found in csg account %s",
                self.config_entry.data[CONF_USERNAME],
            )
            return self.async_abort(reason="no_account")
        selections = {}
        for account in accounts:
            if account.account_number not in self.config_entry.data[CONF_ACCOUNTS]:
                # avoid adding one ele account twice
                selections[
                    account.account_number
                ] = f"{account.account_number} ({account.user_name} {account.address})"
        if not selections:
            _LOGGER.info(
                "Account %s: no ele account to add (all already added), abort",
                self.config_entry.data[CONF_USERNAME],
            )
            return self.async_abort(reason="all_added")

        schema = vol.Schema(
            {
                vol.Required("account_number"): vol.In(selections),
            }
        )
        return self.async_show_form(
            step_id="add_account",
            data_schema=schema,
        )

    async def async_step_remove_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """remove config and entities"""
        if not self.config_entry.data[CONF_ACCOUNTS]:
            return self.async_abort(reason="no_account_to_delete")

        selections = {}
        for _, account_data in self.config_entry.data[CONF_ACCOUNTS].items():
            account = CSGElectricityAccount()
            account.load(account_data)
            selections[
                account.account_number
            ] = f"{account.account_number} ({account.user_name} {account.address})"
        schema = vol.Schema(
            {
                vol.Required("account_number"): vol.In(selections),
            }
        )
        if user_input is None:
            return self.async_show_form(step_id="remove_account", data_schema=schema)

        account_num_to_remove = user_input["account_number"]

        # remove entities and device
        device_reg = device_registry.async_get(self.hass)
        entity_reg = entity_registry.async_get(self.hass)
        all_entities = {
            ent.unique_id: ent.entity_id
            for ent in entity_registry.async_entries_for_config_entry(
                entity_reg, self.config_entry.entry_id
            )
        }

        entities_removed = []
        for unique_id, entity_id in all_entities.items():
            _, account_no, _ = unique_id.split(".")
            if account_no == account_num_to_remove:
                entity_reg.async_remove(entity_id)
                entities_removed.append(unique_id)
        if entities_removed:
            _LOGGER.info("Removed entities: %s", entities_removed)

        device_identifier = {(DOMAIN, account_num_to_remove)}
        device_entry = device_reg.async_get_device(device_identifier)
        if device_entry:
            device_reg.async_remove_device(device_entry.id)
            device_removed = device_identifier
            _LOGGER.info("Removed device: %s", device_removed)

        new_data = self.config_entry.data.copy()
        new_data[CONF_ACCOUNTS].pop(account_num_to_remove)
        new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
        )
        _LOGGER.info(
            "Removed ele account from %s: %s",
            self.config_entry.data[CONF_USERNAME],
            account_num_to_remove,
        )
        return self.async_create_entry(
            title="",
            data={},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Settings of parameters"""
        update_interval = self.config_entry.data[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
        update_timeout = self.config_entry.data[CONF_SETTINGS][CONF_UPDATE_TIMEOUT]
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=update_interval): vol.All(
                    int, min=60
                ),
                vol.Required(CONF_UPDATE_TIMEOUT, default=update_timeout): vol.All(
                    int, min=10
                ),
            }
        )
        if user_input is None:
            return self.async_show_form(step_id="settings", data_schema=schema)

        new_data = self.config_entry.data.copy()
        new_data[CONF_SETTINGS][CONF_UPDATE_INTERVAL] = user_input[CONF_UPDATE_INTERVAL]
        new_data[CONF_SETTINGS][CONF_UPDATE_TIMEOUT] = user_input[CONF_UPDATE_TIMEOUT]
        new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
        )
        return self.async_create_entry(
            title="",
            data={},
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
