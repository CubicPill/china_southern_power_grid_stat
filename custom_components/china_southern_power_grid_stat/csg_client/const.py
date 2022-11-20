"""Constants for csg_client"""
from enum import Enum

# BASE_PATH_WEB = "https://95598.csg.cn/ucs/ma/wt/"
BASE_PATH_APP = "https://95598.csg.cn/ucs/ma/zt/"

# https://95598.csg.cn/js/app.1.6.177.1667607288138.js
PARAM_KEY = "cOdHFNHUNkZrjNaN".encode("utf8")
PARAM_IV = "oMChoRLZnTivcQyR".encode("utf8")
LOGON_CHANNEL_ONLINE_HALL = "3"  # web
LOGON_CHANNEL_HANDHELD_HALL = "4"  # app
RESP_STA_SUCCESS = "00"
RESP_STA_EMPTY_PARAMETER = "01"
RESP_STA_SYSTEM_ERROR = "02"
RESP_STA_NO_LOGIN = "04"
SESSION_KEY_LOGIN_TYPE = "10"


class LoginType(Enum):
    """Login type from JS"""

    LOGIN_TYPE_SMS = "11"
    LOGIN_TYPE_PWD = "10"
    LOGIN_TYPE_WX_QR = "20"
    LOGIN_TYPE_ALI_QR = "21"
    LOGIN_TYPE_CSG_QR = "30"


AREACODE_FALLBACK = AREACODE_GUANGDONG = "030000"

# https://95598.csg.cn/js/chunk-31aec193.1.6.177.1667607288138.js
CREDENTIAL_PUBKEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD1RJE6GBKJlFQvTU6g0ws9R"
    "+qXFccKl4i1Rf4KVR8Rh3XtlBtvBxEyTxnVT294RVvYz6THzHGQwREnlgdkjZyGBf7tmV2CgwaHF+ttvupuzOmRVQ"
    "/difIJtXKM+SM0aCOqBk0fFaLiHrZlZS4qI2/rBQN8VBoVKfGinVMM+USswwIDAQAB"
)

# the value of these login types are the same as the enum above
# however they're not programmatically linked in the source code
# use them as seperated parameters for now
LOGIN_TYPE_PHONE_CODE = "11"
LOGIN_TYPE_PHONE_PWD = "10"
SEND_MSG_TYPE_VERIFICATION_CODE = "1"
VERIFICATION_CODE_TYPE_LOGIN = "1"

# https://95598.csg.cn/js/chunk-49c87982.1.6.177.1667607288138.js
RESP_STA_QR_TIMEOUT = "00010001"

# from packet capture
RESP_STA_LOGIN_WRONG_CREDENTIAL = "00010002"

ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_AREA_CODE = "area_code"
ATTR_ELE_CUSTOMER_ID = "ele_customer_id"
ATTR_METERING_POINT_ID = "metering_point_id"
ATTR_ADDRESS = "address"
ATTR_USER_NAME = "user_name"

HEADER_X_AUTH_TOKEN = "x-auth-token"
HEADER_CUST_NUMBER = "custNumber"

ATTR_AUTH_TOKEN = "auth_token"
ATTR_LOGIN_TYPE = "login_type"
