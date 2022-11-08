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
import datetime
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

DEFAULT_AREA_CODE = {
    "gz": "080000",  # Guangzhou
    "sz": "090000",  # Shenzhen
    "gd": "030000",  # Rest of Guangdong
    "gx": "040000",  # Guangxi
    "yn": "050000",  # Yunnan
    "guiz": "060000",  # Guizhou
    "hn": "070000",  # Hainan
}
AREACODE_FALLBACK = DEFAULT_AREA_CODE["gd"]


# https://95598.csg.cn/js/chunk-31aec193.1.6.177.1667607288138.js
CREDENTIAL_PUBKEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD1RJE6GBKJlFQvTU6g0ws9R+qXFccKl4i1Rf4KVR8Rh3XtlBtvBxEyTxnVT294RVvYz6THzHGQwREnlgdkjZyGBf7tmV2CgwaHF+ttvupuzOmRVQ/difIJtXKM+SM0aCOqBk0fFaLiHrZlZS4qI2/rBQN8VBoVKfGinVMM+USswwIDAQAB"
rsa_key = RSA.import_key(b64decode(CREDENTIAL_PUBKEY))
LONGIN_TYPE_PHONE_CODE = "11"
LONGIN_TYPE_PHONE_PWD = "10"
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


class CSGWebClient:
    """
    Implementation of APIs from browser web interface
    By default, the cookies will expire the moment the browser is closed (expires: session)
    But it's actually valid for a long time

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
        self.x_auth_token = ""
        self.area_code = AREACODE_FALLBACK
        self.customer_id = None  # this may change on every login
        self.customer_number = None  # the 16-digit billing number on the bills
        self.metering_point_id = None

    def restore(self, data: dict[str:str]):
        """Restore the session info to client object"""

    def dump(self) -> dict[str, str]:
        """Dump the session to dict"""

    def authenticate(self, phone_no, password):
        """
        Authenticate the client using phone number and password
        Will set session parameters
        """

    def set_authentication_params(self, x_auth_token):
        """Set self.x_auth_token and client generated cookies"""

    def initialize(self, phone_no, password, elec_account_index=0):
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
    ):
        """
        Function to make the http request to api endpoints
        can automatically add authentication header(s)
        """
        _LOGGER.debug("_make_request: %s, %s, %s, %s", path, payload, with_auth, method)
        url = BASE_PATH + path
        headers = self._common_headers
        if with_auth:
            headers["x-auth-token"] = self.x_auth_token
        if method == "POST":
            response = self._session.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                _LOGGER.error(
                    "API call %s returned status code %d", path, response.status_code
                )
                raise CSGAPIError()
            response_data = response.json()
            _LOGGER.debug("_make_request: response: %s", response_data)

            # session validility is handled here
            if response_data["sta"] == RESP_STA_NO_LOGIN:
                _LOGGER.warning("Login expired while calling api: %s", path)
                raise NotLoggedIn()

            # headers need to be returned since they may contain additional data
            return response.headers, response_data

        raise NotImplementedError()

    def _handle_unsuccessful_response(self, response_data: dict):
        """Handles sta=!RESP_STA_SUCCESS"""
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
        raise CSGAPIError()

    def api_login_with_sms_code(self, phone_no: str, code: str):
        """Login with phone number and SMS code"""
        path = "center/login"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "acctId": phone_no,
            "logonChan": LOGIN_CHANNEL_ONLINE_HALL,
            "credType": LONGIN_TYPE_PHONE_CODE,
            "code": code,
        }
        resp_header, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_header["x-auth-token"]
        raise CSGAPIError()

    def api_login_with_password(self, phone_no: str, password: str):
        """Login with phone number and password"""
        path = "center/login"
        payload = {
            "areaCode": AREACODE_FALLBACK,
            "acctId": phone_no,
            "logonChan": LOGIN_CHANNEL_ONLINE_HALL,
            "credType": LONGIN_TYPE_PHONE_PWD,
            "credentials": encrypt_credential(password),
        }
        resp_header, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_header["x-auth-token"]
        raise CSGAPIError()

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
        raise CSGAPIError()

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

    def api_get_month_daily_usage(self, year: int, month: int) -> dict:
        """get usage(kWh) by day in the given month"""
        path = "charge/queryDayElectricByMPoint"
        payload = {
            "areaCode": self.area_code,
            "eleCustId": self.customer_id,
            "yearMonth": f"{year}{month:02d}",
            "meteringPointId": self.metering_point_id,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_account_surplus(self):
        """Contains: balance and arrears"""
        path = "charge/queryUserAccountNumberSurplus"
        payload = {"areaCode": self.area_code, "eleCustId": self.customer_id}
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_fee_analyze_details(self, year: int):
        """
        Contains: year total kWh, year total charge, kWh/charge by month in current year
        """
        path = "charge/getAnalyzeFeeDetails"
        payload = {
            "areaCode": self.area_code,
            "electricityBillYear": year,
            "eleCustId": self.customer_id,
            "meteringPointId": None,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def get_month_daily_usage_detail(self) -> dict:
        """Get daily usage of current month"""
        dt_now = datetime.datetime.now()
        year, month = dt_now.year, dt_now.month

        resp_data = self.api_get_month_daily_usage(year, month)
        month_total_kwh = resp_data["totalPower"]
        by_day = []
        for d_data in resp_data["result"]:
            by_day.append({"date": d_data["date"], "kwh": d_data["power"]})
        return {"month_total_kwh": month_total_kwh, "by_day": by_day}

    def get_balance_and_arrears(self) -> tuple[float, float]:
        """Get account balance and arrears"""
        resp_data = self.api_query_account_surplus()
        balance = resp_data[0]["balance"]
        arrears = resp_data[0]["arrears"]
        return balance, arrears

    def get_year_month_stats(self) -> dict:
        """Get year total kWh, year total charge, kWh/charge by month in current year"""
        year = datetime.datetime.now().year
        resp_data = self.api_get_fee_analyze_details(year)

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
