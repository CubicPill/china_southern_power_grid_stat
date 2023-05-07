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
    ABORT_ALL_ADDED,
    ABORT_NO_ACCOUNT,
    ABORT_NO_ACCOUNT_TO_DELETE,
    CONF_ACCOUNTS,
    CONF_ACCOUNT_NUMBER,
    CONF_ACTION,
    CONF_AUTH_TOKEN,
    CONF_GENERAL_ERROR,
    CONF_LOGIN_TYPE,
    CONF_SETTINGS,
    CONF_UPDATED_AT,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATE_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_UPDATE_TIMEOUT,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
    STEP_ADD_ACCOUNT,
    STEP_INIT,
    STEP_REMOVE_ACCOUNT,
    STEP_SETTINGS,
    STEP_USER,
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
        _LOGGER.error("Authentication failed: %s", exc)
        raise InvalidAuth from exc
    except RequestException as exc:
        raise CannotConnect from exc
    return client


async def validate_input(
    hass: HomeAssistant, data: dict[str, str]
) -> dict[str, Any] | None:
    """Validate the credentials (login)"""

    client = await hass.async_add_executor_job(
        authenticate_csg, data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    return client.dump()


class CSGConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for China Southern Power Grid Statistics."""

    VERSION = 1
    reauth_entry: config_entries.ConfigEntry | None = None

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
            return self.async_show_form(step_id=STEP_USER, data_schema=schema)

        errors = {}
        unique_id = f"CSG-{user_input[CONF_USERNAME]}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # noinspection PyBroadException
        try:
            session_data = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors[CONF_GENERAL_ERROR] = ERROR_CANNOT_CONNECT
        except InvalidAuth:
            errors[CONF_GENERAL_ERROR] = ERROR_INVALID_AUTH
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors[CONF_GENERAL_ERROR] = ERROR_UNKNOWN
        else:
            if self.reauth_entry:
                new_data = self.reauth_entry.data.copy()
                if user_input[CONF_USERNAME] != new_data[CONF_USERNAME]:
                    _LOGGER.warning(
                        "Account name changed: previous: %s, now: %s",
                        new_data[CONF_USERNAME],
                        user_input[CONF_USERNAME],
                    )
                new_data[CONF_USERNAME] = user_input[CONF_USERNAME]
                new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                new_data[CONF_AUTH_TOKEN] = session_data[CONF_AUTH_TOKEN]
                new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
                self.hass.config_entries.async_update_entry(
                    self.reauth_entry,
                    data=new_data,
                    title=f"CSG-{user_input[CONF_USERNAME]}",
                )
                await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                _LOGGER.info(
                    "Reauth of account %s is successful!", user_input[CONF_USERNAME]
                )
                return self.async_abort(reason="reauth_successful")

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

        return self.async_show_form(
            step_id=STEP_USER, data_schema=schema, errors=errors
        )

    async def async_step_reauth(self, user_input=None):
        """Perform reauth upon an API authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
            )
        return await self.async_step_user()


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
                vol.Required(CONF_ACTION, default=STEP_ADD_ACCOUNT): vol.In(
                    {
                        STEP_ADD_ACCOUNT: "添加已绑定的缴费号",
                        STEP_REMOVE_ACCOUNT: "移除缴费号实体",
                        STEP_SETTINGS: "参数设置",
                    }
                ),
            }
        )
        if user_input:
            if user_input[CONF_ACTION] == STEP_ADD_ACCOUNT:
                return await self.async_step_add_account()
            if user_input[CONF_ACTION] == STEP_REMOVE_ACCOUNT:
                return await self.async_step_remove_account()
            if user_input[CONF_ACTION] == STEP_SETTINGS:
                return await self.async_step_settings()
        return self.async_show_form(step_id=STEP_INIT, data_schema=schema)

    async def async_step_add_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select one of the electricity accounts from current account"""
        # account_no: f'{account_no} ({name} {addr})'

        all_csg_config_entries = self.hass.config_entries.async_entries(DOMAIN)
        # get a list of all account numbers from all config entries
        all_account_numbers = []
        for config_entry in all_csg_config_entries:
            all_account_numbers.extend(config_entry.data[CONF_ACCOUNTS].keys())
        if user_input:
            account_num_to_add = user_input[CONF_ACCOUNT_NUMBER]
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
                    _LOGGER.info("Reloading entry because of new added account")
                    await self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                    return self.async_create_entry(
                        title="",
                        data={},
                    )
        # end of handling add account

        # start of getting all unbound accounts
        client = CSGClient.load(
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
            return self.async_abort(reason=ABORT_NO_ACCOUNT)
        selections = {}
        for account in accounts:
            if account.account_number not in all_account_numbers:
                # avoid adding one ele account twice
                selections[
                    account.account_number
                ] = f"{account.account_number} ({account.user_name} {account.address})"
        if not selections:
            _LOGGER.info(
                "Account %s: no ele account to add (all already added), abort",
                self.config_entry.data[CONF_USERNAME],
            )
            return self.async_abort(reason=ABORT_ALL_ADDED)

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_NUMBER): vol.In(selections),
            }
        )
        return self.async_show_form(
            step_id=STEP_ADD_ACCOUNT,
            data_schema=schema,
        )

    async def async_step_remove_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """remove config and entities"""
        if not self.config_entry.data[CONF_ACCOUNTS]:
            return self.async_abort(reason=ABORT_NO_ACCOUNT_TO_DELETE)

        selections = {}
        for _, account_data in self.config_entry.data[CONF_ACCOUNTS].items():
            account = CSGElectricityAccount.load(account_data)
            selections[
                account.account_number
            ] = f"{account.account_number} ({account.user_name} {account.address})"
        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_NUMBER): vol.In(selections),
            }
        )
        if user_input is None:
            return self.async_show_form(step_id=STEP_REMOVE_ACCOUNT, data_schema=schema)

        account_num_to_remove = user_input[CONF_ACCOUNT_NUMBER]

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
        _LOGGER.info("Reloading entry because of deleted account")
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

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
                    int, vol.Range(min=60)
                ),
                vol.Required(CONF_UPDATE_TIMEOUT, default=update_timeout): vol.All(
                    int, vol.Range(min=10)
                ),
            }
        )
        if user_input is None:
            return self.async_show_form(step_id=STEP_SETTINGS, data_schema=schema)

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
