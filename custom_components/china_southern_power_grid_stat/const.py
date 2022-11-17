"""Constants for the China Southern Power Grid Statistics integration."""
from datetime import timedelta

DOMAIN = "china_southern_power_grid_stat"

CONF_ACCOUNT_NUMBER = "account_number"
CONF_LOGIN_TYPE = "login_type"
CONF_AUTH_TOKEN = "auth_token"
CONF_ACCOUNTS = "accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_UPDATE_TIMEOUT = "update_timeout"
CONF_SETTINGS = "settings"
CONF_UPDATED_AT = "updated_at"

STEP_SETTINGS = "settings"
STEP_ADD_ACCOUNT = "add_account"
STEP_DELETE_ACCOUNT = "delete_account"

VALUE_CSG_LOGIN_TYPE_PWD = "10"

DEFAULT_UPDATE_INTERVAL = timedelta(hours=1).seconds
DEFAULT_UPDATE_TIMEOUT = 20

SUFFIX_BAL = "balance"
SUFFIX_ARR = "arrears"
SUFFIX_YEAR_KWH = "this_year_total_usage"
SUFFIX_YEAR_COST = "this_year_total_cost"
SUFFIX_MONTH_KWH = "this_month_total_usage"

ATTR_KEY_MONTH_BY_DAY = "this_month_by_day"
ATTR_KEY_YEAR_BY_MONTH = "this_year_by_month"
