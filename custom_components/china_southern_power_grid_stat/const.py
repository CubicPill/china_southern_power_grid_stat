"""Constants for the China Southern Power Grid Statistics integration."""
from datetime import timedelta

DOMAIN = "china_southern_power_grid_stat"

CONF_ACCOUNT_NUMBER = "account_number"
CONF_LOGIN_TYPE = "login_type"
CONF_AUTH_TOKEN = "auth_token"
CONF_ACCOUNTS = "accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SETTINGS = "settings"
STEP_SETTINGS = "settings"
STEP_ADD_ACCOUNT = "add_account"
STEP_DELETE_ACCOUNT = "delete_account"
DEFAULT_UPDATE_INTERVAL = timedelta(hours=1).seconds
