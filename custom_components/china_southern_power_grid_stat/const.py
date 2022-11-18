"""Constants for the China Southern Power Grid Statistics integration."""
from datetime import timedelta

DOMAIN = "china_southern_power_grid_stat"

DATA_KEY_UNSUB_UPDATE_LISTENER = "unsub_update_listener"
STATE_UPDATE_UNCHANGED = "unchanged"
DATA_KEY_LAST_UPDATE_DAY = "last_update_day"

CONF_ACCOUNT_NUMBER = "account_number"
CONF_LOGIN_TYPE = "login_type"
CONF_AUTH_TOKEN = "auth_token"
CONF_ACCOUNTS = "accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_UPDATE_TIMEOUT = "update_timeout"
CONF_SETTINGS = "settings"
CONF_UPDATED_AT = "updated_at"
CONF_ACTION = "action"

STEP_USER = "user"
STEP_INIT = "init"
STEP_SETTINGS = "settings"
STEP_ADD_ACCOUNT = "add_account"
STEP_REMOVE_ACCOUNT = "remove_account"

ABORT_NO_ACCOUNT = "no_account"
ABORT_ALL_ADDED = "all_added"
ABORT_NO_ACCOUNT_TO_DELETE = "no_account_to_delete"

CONF_GENERAL_ERROR = "base"
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

VALUE_CSG_LOGIN_TYPE_PWD = "10"

DEFAULT_UPDATE_INTERVAL = timedelta(hours=4).seconds
DEFAULT_UPDATE_TIMEOUT = 20

SUFFIX_BAL = "balance"
SUFFIX_ARR = "arrears"
SUFFIX_YESTERDAY_KWH = "yesterday_kwh"
SUFFIX_THIS_YEAR_KWH = "this_year_total_usage"
SUFFIX_THIS_YEAR_COST = "this_year_total_cost"
SUFFIX_THIS_MONTH_KWH = "this_month_total_usage"
SUFFIX_LAST_YEAR_KWH = "last_year_total_usage"
SUFFIX_LAST_YEAR_COST = "last_year_total_cost"
SUFFIX_LAST_MONTH_KWH = "last_month_total_usage"

ATTR_KEY_THIS_MONTH_BY_DAY = "this_month_by_day"
ATTR_KEY_THIS_YEAR_BY_MONTH = "this_year_by_month"
ATTR_KEY_LAST_MONTH_BY_DAY = "last_month_by_day"
ATTR_KEY_LAST_YEAR_BY_MONTH = "last_year_by_month"
