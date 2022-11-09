"""
Implementations of CSG's Web API
this library is synchronous - since the updates are not frenquent (12h+)
and each update only contains a few requests
"""
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
import json
import requests
import logging
import random
import time
from enum import Enum
import datetime
from typing import Any
from hashlib import md5

from base64 import b64decode, b64encode

_LOGGER = logging.getLogger(__name__)

BASE_PATH = "https://95598.csg.cn/ucs/ma/wt/"

# https://95598.csg.cn/js/app.1.6.177.1667607288138.js
PARAM_KEY = "cOdHFNHUNkZrjNaN".encode("utf8")
PARAM_IV = "oMChoRLZnTivcQyR".encode("utf8")
LOGIN_CHANNEL_ONLINE_HALL = "3"
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


class AreaCode(Enum):
    """Area codes"""

    GUANGZHOU = "080000"
    SHENZHEN = "090000"
    GUANGDONG = "030000"  # Rest of Guangdong
    GUANGXI = "040000"
    YUNNAN = "050000"
    GUIZHOU = "060000"
    HAINAN = "070000"


AREACODE_FALLBACK = AreaCode.GUANGDONG.value


# https://95598.csg.cn/js/chunk-31aec193.1.6.177.1667607288138.js
CREDENTIAL_PUBKEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD1RJE6GBKJlFQvTU6g0ws9R+qXFccKl4i1Rf4KVR8Rh3XtlBtvBxEyTxnVT294RVvYz6THzHGQwREnlgdkjZyGBf7tmV2CgwaHF+ttvupuzOmRVQ/difIJtXKM+SM0aCOqBk0fFaLiHrZlZS4qI2/rBQN8VBoVKfGinVMM+USswwIDAQAB"
rsa_key = RSA.import_key(b64decode(CREDENTIAL_PUBKEY))

# the value of these login types are the same as the enum above
# however they're not programatically linked in the source code
# use them as seperated parameters for now
LOGIN_TYPE_PHONE_CODE = "11"
LOGIN_TYPE_PHONE_PWD = "10"
SEND_MSG_TYPE_VERIFICATION_CODE = "1"
VERIFICATION_CODE_TYPE_LOGIN = "1"

# https://95598.csg.cn/js/chunk-49c87982.1.6.177.1667607288138.js
RESP_STA_QR_TIMEOUT = "00010001"


class CSGAPIError(Exception):
    """Generic API errors"""


class NotLoggedIn(Exception):
    """Not logged in or login expired (RESP_STA_NO_LOGIN)"""


class QrCodeExpired(Exception):
    """QR code has expired"""


def generate_qr_login_id():
    """
    Generate a unique id for qr code login
    word-by-word copied from js code
    """
    rand_str = f"{int(time.time()*1000)}{random.random()}"
    return md5(rand_str.encode()).hexdigest()


def encrypt_credential(password: str) -> str:
    """Use RSA+pubkey to encrypt password"""
    credential_cipher = PKCS1_v1_5.new(rsa_key)
    encrypted_pwd = credential_cipher.encrypt(password.encode("utf8"))
    return b64encode(encrypted_pwd).decode()


def encrypt_params(params: dict) -> str:
    """Decrypt response message using AES with KEY, IV"""
    json_cipher = AES.new(PARAM_KEY, AES.MODE_CBC, PARAM_IV)

    def pad(content: str) -> str:
        return content + (16 - len(content) % 16) * "\x00"

    json_str = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    encrypted = json_cipher.encrypt(pad(json_str).encode("utf8"))
    return b64encode(encrypted).decode()


def decrypt_params(encrypted: str) -> dict:
    """Encrypt request message using AES with KEY, IV"""
    json_cipher = AES.new(PARAM_KEY, AES.MODE_CBC, PARAM_IV)
    decrypted = json_cipher.decrypt(b64decode(encrypted))
    # remove padding
    params = json.loads(decrypted.decode().strip("\x00"))
    return params


class CSGElectrityAccount:
    """Represents one electricity account, identified by account number (缴费号)"""

    def __init__(
        self,
        account_number: str,
        area_code: AreaCode,
        customer_id: str,
        metering_point_id: str,
        address: str,
        user_name: str,
    ):

        # the parameters are independent for each electricity account

        # the 16-digit billing number, as a unique identifier, not used in api for now
        self.customer_number = account_number

        self.area_code = area_code

        # this may change on every login, alternative name in js code is `binding_id`
        self.customer_id = customer_id

        # in fact one account may have multiple metering points, however for individual users there should only be one
        self.metering_point_id = metering_point_id

        # for frontend display only
        self.address = address
        self.user_name = user_name


class CSGWebClient:
    """
    Implementation of APIs from browser web interface
    By default, the cookies will expire the moment the browser is closed (expires: session)
    But it's actually valid for a long time

    How to use:
    First call `CSGWebClient.authenticate`, this will authenticate the client using username and password. Then call `CSGWebClient.initialize`

    """

    def __init__(self):
        self._session: requests.Session = requests.Session()
        self._common_headers = {
            "Host": "95598.csg.cn",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://95598.csg.cn",
            "Referer": "https://95598.csg.cn/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
        }

        self.x_auth_token: str = ""
        self.accounts: dict[str:CSGElectrityAccount] = {}

    def restore(self, data: dict[str:str]):
        """
        Restore the session info to client object
        The validity of the session won't be checked
        """
        for k in [
            "x_auth_token",
            "accounts",
        ]:
            if not data.get(k):
                raise ValueError(f"missing parameter: {k}")
            setattr(self, k, data["k"])

        if not data.get("cookies"):
            raise ValueError("missing cookies")
        self._session.cookies.clear()
        self._session.cookies.update(data["cookies"])

    def dump(self) -> dict[str, Any]:
        """Dump the session to dict"""
        return {
            "x_auth_token": self.x_auth_token,
            "accounts": self.accounts,
            "cookies": self._session.cookies.get_dict(),
        }

    def authenticate(self, phone_no: str, password: str):
        """
        Authenticate the client using phone number and password
        Will set session parameters
        """
        x_auth_token = self.api_login_with_password(phone_no, password)
        self.set_authentication_params(x_auth_token, LoginType.LOGIN_TYPE_PWD)

    def set_authentication_params(self, x_auth_token: str, login_type: LoginType):
        """Set self.x_auth_token and client generated cookies"""
        self.x_auth_token = x_auth_token
        self._session.cookies.update(
            {
                "token": x_auth_token,
                "is-login": "true",
                SESSION_KEY_LOGIN_TYPE: login_type.value,
            }
        )

    def initialize(
        self,
    ):
        """
        Intialize the client
        Get needed parameters
        """

    def _make_request(
        self,
        path: str,
        payload: dict or None,
        with_auth: bool = True,
        method: str = "POST",
        custom_headers: dict = None,
    ):
        """
        Function to make the http request to api endpoints
        can automatically add authentication header(s)
        """
        _LOGGER.debug("_make_request: %s, %s, %s, %s", path, payload, with_auth, method)
        url = BASE_PATH + path
        headers = self._common_headers
        if custom_headers:
            for _k, _v in custom_headers:
                headers[_k] = _v
        if with_auth:
            headers["x-auth-token"] = self.x_auth_token
        if method == "POST":
            response = self._session.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                _LOGGER.error(
                    "API call %s returned status code %d", path, response.status_code
                )
                raise CSGAPIError(f"api call returned http {response.status_code}")
            response_data = response.json()
            _LOGGER.debug("_make_request: response: %s", response_data)

            # headers need to be returned since they may contain additional data
            return response.headers, response_data

        raise NotImplementedError()

    def _handle_unsuccessful_response(self, response_data: dict):
        """Handles sta=!RESP_STA_SUCCESS"""
        if response_data["sta"] == RESP_STA_NO_LOGIN:
            raise NotLoggedIn()
        raise CSGAPIError(
            f"Error {response_data['sta']}, message: {response_data['message']}"
        )

    def api_send_login_sms(self, phone_no: str):
        """Send SMS verification code to phone_no"""
        path = "center/sendMsg"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "phoneNumber": phone_no,
            "vcType": VERIFICATION_CODE_TYPE_LOGIN,
            "msgType": SEND_MSG_TYPE_VERIFICATION_CODE,
        }
        _, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return True
        self._handle_unsuccessful_response(resp_data)

    def api_login_with_sms_code(self, phone_no: str, code: str):
        """Login with phone number and SMS code"""
        path = "center/login"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "acctId": phone_no,
            "logonChan": LOGIN_CHANNEL_ONLINE_HALL,
            "credType": LOGIN_TYPE_PHONE_CODE,
            "code": code,
        }
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_header["x-auth-token"]
        self._handle_unsuccessful_response(resp_data)

    def api_login_with_password(self, phone_no: str, password: str):
        """Login with phone number and password"""
        path = "center/login"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "acctId": phone_no,
            "logonChan": LOGIN_CHANNEL_ONLINE_HALL,
            "credType": LOGIN_TYPE_PHONE_PWD,
            "credentials": encrypt_credential(password),
        }
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_header["x-auth-token"]
        self._handle_unsuccessful_response(resp_data)

    def api_create_login_qr_code(self, channel: str) -> str:
        """Create QR code to scan"""
        if channel not in ["app", "wechat", "alipay"]:
            raise ValueError(f'Channel "{channel}" is invalid')
        path = "center/createLoginQrcode"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "channel": channel,
            # not a typo, original js is like so
            "lgoinId": generate_qr_login_id(),
        }
        _, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            code_url = resp_data["data"]
            return code_url
        self._handle_unsuccessful_response(resp_data)

    def api_get_qr_login_update(self, login_id: str):
        """Get update about qr code (whether it has been scanned)"""
        path = "/center/getLoginInfo"
        payload = {"areaCode": AREACODE_FALLBACK, "loginId": login_id}
        resp_header, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            # login success
            self.x_auth_token = resp_header["x-auth-token"]
            return resp_header["x-auth-token"]
        elif resp_data["sta"] == RESP_STA_QR_TIMEOUT:
            # qr expired
            raise QrCodeExpired()
        else:
            # not scanned yet, just wait
            return False

    def api_get_user_info(self) -> dict:
        """Get account info"""
        path = "user/getUserInfo"
        _, resp_data = self._make_request(path, None)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_all_bound_ele_users(self) -> list:
        """List all bound electricity users under this account"""
        path = "eleCustNumber/queryBindEleUsers"
        _, resp_data = self._make_request(path, None)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            _LOGGER.debug("Total %d users under this account", len(resp_data["data"]))
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_day_electric_by_m_point(
        self,
        year: int,
        month: int,
        area_code: str,
        customer_id: str,
        metering_point_id: str,
    ) -> dict:
        """get usage(kWh) by day in the given month"""
        path = "charge/queryDayElectricByMPoint"
        payload = {
            "areaCode": area_code,
            "eleCustId": customer_id,
            "yearMonth": f"{year}{month:02d}",
            "meteringPointId": metering_point_id,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_account_surplus(self, area_code: str, customer_id: str):
        """Contains: balance and arrears"""
        path = "charge/queryUserAccountNumberSurplus"
        payload = {"areaCode": area_code, "eleCustId": customer_id}
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_fee_analyze_details(self, year: int, area_code: str, customer_id: str):
        """
        Contains: year total kWh, year total charge, kWh/charge by month in current year
        """
        path = "charge/getAnalyzeFeeDetails"
        payload = {
            "areaCode": area_code,
            "electricityBillYear": year,
            "eleCustId": customer_id,
            "meteringPointId": None,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_charges(self, area_code: str, customer_id: str, _type="0"):
        """Contains: balance and arrears, metering points"""
        path = "charge/queryCharges"
        payload = {
            "areaCode": area_code,
            "eleModels": [{"eleCustId": customer_id, "areaCode": area_code}],
            "type": _type,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def get_all_electricity_accounts(self) -> list[CSGElectrityAccount]:
        """Get all electricity accounts bound to currnt account"""
        result = []
        ele_user_resp_data = self.api_get_all_bound_ele_users()

        for item in ele_user_resp_data:

            charge_resp_data = self.api_query_charges(
                item["area_code"], item["bindingId"]
            )
            metering_point_id = charge_resp_data[0]["points"][0]["meteringPointId"]
            account = CSGElectrityAccount(
                item["eleCustNumber"],
                item["area_code"],
                item["bindingId"],
                metering_point_id,
                item["eleAddress"],
                item["userName"],
            )
            result.append(account)
        return result

    def get_month_daily_usage_detail(self, account_no: str) -> dict:
        """Get daily usage of current month"""
        dt_now = datetime.datetime.now()
        year, month = dt_now.year, dt_now.month
        account: CSGElectrityAccount = self.accounts[account_no]

        resp_data = self.api_query_day_electric_by_m_point(
            year,
            month,
            account.area_code,
            account.customer_id,
            account.metering_point_id,
        )
        month_total_kwh = resp_data["totalPower"]
        by_day = []
        for d_data in resp_data["result"]:
            by_day.append({"date": d_data["date"], "kwh": d_data["power"]})
        return {"month_total_kwh": month_total_kwh, "by_day": by_day}

    def get_balance_and_arrears(self, account_no: str) -> tuple[float, float]:
        """Get account balance and arrears"""
        account: CSGElectrityAccount = self.accounts[account_no]

        resp_data = self.api_query_account_surplus(
            account.area_code, account.customer_id
        )
        balance = resp_data[0]["balance"]
        arrears = resp_data[0]["arrears"]
        return balance, arrears

    def get_year_month_stats(self, account_no: str) -> dict:
        """Get year total kWh, year total charge, kWh/charge by month in current year"""
        account: CSGElectrityAccount = self.accounts[account_no]
        year = datetime.datetime.now().year
        resp_data = self.api_get_fee_analyze_details(
            year, account.area_code, account.customer_id
        )

        total_year_kwh = resp_data["totalBillingElectricity"]
        total_year_charge = resp_data["totalActualAmount"]
        by_month = []
        for m_data in resp_data["electricAndChargeList"]:
            by_month.append(
                {
                    "month": m_data["yearMonth"],
                    "charge": m_data["actualTotalAmount"],
                    "kwh": m_data["billingElectricity"],
                }
            )
        return {
            "year_total_charge": total_year_charge,
            "year_total_kwh": total_year_kwh,
            "by_month": by_month,
        }
