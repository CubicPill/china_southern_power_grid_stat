"""Constants for the China Southern Power Grid Statistics integration."""
from datetime import timedelta

DOMAIN = "china_southern_power_grid_stat"

# config flow
# main account (phone number)
CONF_ACCOUNT_NUMBER = "account_number"
CONF_LOGIN_TYPE = "login_type"
CONF_AUTH_TOKEN = "auth_token"
# electricity accounts
CONF_ELE_ACCOUNTS = "accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SETTINGS = "settings"
CONF_UPDATED_AT = "updated_at"
CONF_ACTION = "action"
CONF_SMS_CODE = "sms_code"

STEP_USER = "user"
STEP_SMS_LOGIN = "sms_login"
STEP_SMS_PWD_LOGIN = "sms_pwd_login"
STEP_VALIDATE_SMS_CODE = "validate_sms_code"
STEP_CSG_QR_LOGIN = "csg_qr_login"
STEP_WX_QR_LOGIN = "wx_qr_login"
STEP_ALI_QR_LOGIN = "ali_qr_login"
STEP_QR_LOGIN = "qr_login"
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

# api


# sensor updates
SUFFIX_BAL = "balance"
SUFFIX_ARR = "arrears"
SUFFIX_YESTERDAY_KWH = "yesterday_kwh"
SUFFIX_LATEST_DAY_KWH = "latest_day_kwh"
SUFFIX_LATEST_DAY_COST = "latest_day_cost"
SUFFIX_THIS_YEAR_KWH = "this_year_total_usage"
SUFFIX_THIS_YEAR_COST = "this_year_total_cost"
SUFFIX_THIS_MONTH_KWH = "this_month_total_usage"
SUFFIX_THIS_MONTH_COST = "this_month_total_cost"
SUFFIX_CURRENT_LADDER = "current_ladder"
SUFFIX_CURRENT_LADDER_REMAINING_KWH = "current_ladder_remaining_kwh"
SUFFIX_CURRENT_LADDER_TARIFF = "current_ladder_tariff"
SUFFIX_LAST_YEAR_KWH = "last_year_total_usage"
SUFFIX_LAST_YEAR_COST = "last_year_total_cost"
SUFFIX_LAST_MONTH_KWH = "last_month_total_usage"
SUFFIX_LAST_MONTH_COST = "last_month_total_cost"

ATTR_KEY_THIS_MONTH_BY_DAY = "this_month_by_day"
ATTR_KEY_THIS_YEAR_BY_MONTH = "this_year_by_month"
ATTR_KEY_LAST_MONTH_BY_DAY = "last_month_by_day"
ATTR_KEY_LAST_YEAR_BY_MONTH = "last_year_by_month"
ATTR_KEY_LATEST_DAY_DATE = "latest_day_date"
ATTR_KEY_CURRENT_LADDER_START_DATE = "current_ladder_start_date"

STATE_UPDATE_UNCHANGED = "unchanged"
DATA_KEY_LAST_UPDATE_DAY = "last_update_day"

# settings

# currently, this timeout is for each request, user should not need to set it manually
SETTING_UPDATE_TIMEOUT = 60
# the first n days in a month that will get data of last month
SETTING_LAST_MONTH_UPDATE_DAY_THRESHOLD = 3
# the first n days in a year that will get data of last year
SETTING_LAST_YEAR_UPDATE_DAY_THRESHOLD = 7


# defaults
DEFAULT_UPDATE_INTERVAL = timedelta(hours=4).seconds
