# -*- coding: utf-8 -*-
"""
Implementations of CSG's Web API
this library is synchronous - since the updates are not frequent (12h+)
and each update only contains a few requests
"""
from __future__ import annotations

import json
import logging
import random
import time
from base64 import b64decode, b64encode
from copy import copy
from hashlib import md5
from typing import Any

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA

from .const import *

_LOGGER = logging.getLogger(__name__)


class CSGAPIError(Exception):
    """Generic API errors"""

    def __init__(self, sta: str, msg: str) -> None:
        """sta: status code, msg: message"""
        Exception.__init__(self)
        self.sta = sta
        self.msg = msg

    def __str__(self):
        return f"<CSGAPIError sta={self.sta} message={self.msg}>"


class CSGHTTPError(Exception):
    """Unexpected HTTP status code (!=200)"""

    def __init__(self, code: int) -> None:
        Exception.__init__(self)
        self.status_code = code

    def __str__(self) -> str:
        return f"<CSGHTTPError code={self.status_code}>"


class InvalidCredentials(CSGAPIError):
    """Wrong username+password combination (RESP_STA_LOGIN_WRONG_CREDENTIAL)"""

    def __str__(self):
        return f"<CSGInvalidCredentials sta={self.sta} message={self.msg}>"


class NotLoggedIn(CSGAPIError):
    """Not logged in or login expired (RESP_STA_NO_LOGIN)"""

    def __str__(self):
        return f"<CSGNotLoggedIn sta={self.sta} message={self.msg}>"


class QrCodeExpired(Exception):
    """QR code has expired"""


def generate_qr_login_id():
    """
    Generate a unique id for qr code login
    word-by-word copied from js code
    """
    rand_str = f"{int(time.time() * 1000)}{random.random()}"
    return md5(rand_str.encode()).hexdigest()


def encrypt_credential(password: str) -> str:
    """Use RSA+pubkey to encrypt password"""
    rsa_key = RSA.import_key(b64decode(CREDENTIAL_PUBKEY))
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


class CSGElectricityAccount:
    """Represents one electricity account, identified by account number (缴费号)"""

    def __init__(
        self,
        account_number: str | None = None,
        area_code: str | None = None,
        ele_customer_id: str | None = None,
        metering_point_id: str | None = None,
        address: str | None = None,
        user_name: str | None = None,
    ) -> None:
        # the parameters are independent for each electricity account

        # the 16-digit billing number, as a unique identifier, not used in api for now
        self.account_number = account_number

        self.area_code = area_code

        # this may change on every login, alternative name in js code is `binding_id`
        self.ele_customer_id = ele_customer_id

        # in fact one account may have multiple metering points, however for individual users there should only be one
        self.metering_point_id = metering_point_id

        # for frontend display only
        self.address = address
        self.user_name = user_name

    def dump(self) -> dict[str, str]:
        """serialize this object"""
        return {
            ATTR_ACCOUNT_NUMBER: self.account_number,
            ATTR_AREA_CODE: self.area_code,
            ATTR_ELE_CUSTOMER_ID: self.ele_customer_id,
            ATTR_METERING_POINT_ID: self.metering_point_id,
            ATTR_ADDRESS: self.address,
            ATTR_USER_NAME: self.user_name,
        }

    @staticmethod
    def load(data: dict) -> CSGElectricityAccount:
        """deserialize this object"""
        for k in (
            ATTR_ACCOUNT_NUMBER,
            ATTR_AREA_CODE,
            ATTR_ELE_CUSTOMER_ID,
            ATTR_METERING_POINT_ID,
            ATTR_ADDRESS,
            ATTR_USER_NAME,
        ):
            if k not in data:
                raise ValueError(f"Missing key {k}")
        account = CSGElectricityAccount(
            account_number=data[ATTR_ACCOUNT_NUMBER],
            area_code=data[ATTR_AREA_CODE],
            ele_customer_id=data[ATTR_ELE_CUSTOMER_ID],
            metering_point_id=data[ATTR_METERING_POINT_ID],
            address=data[ATTR_ADDRESS],
            user_name=data[ATTR_USER_NAME],
        )
        return account


class CSGClient:
    """
    Implementation of APIs from CSG iOS app interface.
    Parameters and consts are from web app js, however, these interfaces are virtually the same

    Do not call any functions starts with _api unless you are certain about what you're doing

    How to use:
    First call `CSGWebClient.authenticate`, this will authenticate the client using username and password.
    Then call `CSGWebClient.initialize`
    To get all linked electricity accounts, call `get_all_electricity_accounts`
    Use the account objects to call the utility functions and wrapped api functions
    """

    def __init__(
        self,
        auth_token: str | None = None,
        login_type: LoginType | None = None,
    ) -> None:
        self._session: requests.Session = requests.Session()
        self._common_headers = {
            "Host": "95598.csg.cn",
            "Content-Type": "application/json;charset=utf-8",
            "Origin": "file://",
            "x-auth-token": "",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko)",
            "custNumber": "",
            "Accept-Language": "zh-CN,cn;q=0.9",
        }

        self.auth_token = auth_token or ""
        self.login_type = login_type or LoginType.LOGIN_TYPE_PWD

        # identifier, need to be set in initialize()
        self.customer_number = ""

    # begin internal utility functions
    def _make_request(
        self,
        path: str,
        payload: dict | None,
        with_auth: bool = True,
        method: str = "POST",
        custom_headers: dict | None = None,
    ):
        """
        Function to make the http request to api endpoints
        can automatically add authentication header(s)
        """
        _LOGGER.debug("_make_request: %s, %s, %s, %s", path, payload, with_auth, method)
        url = BASE_PATH_APP + path
        headers = copy(self._common_headers)
        if custom_headers:
            for _k, _v in custom_headers.items():
                headers[_k] = _v
        if with_auth:
            headers[HEADER_X_AUTH_TOKEN] = self.auth_token
            headers[HEADER_CUST_NUMBER] = self.customer_number
        if method == "POST":
            response = self._session.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                _LOGGER.error(
                    "API call %s returned status code %d", path, response.status_code
                )
                raise CSGHTTPError(response.status_code)
            response_data = response.json()
            _LOGGER.debug("_make_request: response: %s", json.dumps(response_data))

            # headers need to be returned since they may contain additional data
            return response.headers, response_data

        raise NotImplementedError()

    def _handle_unsuccessful_response(self, response_data: dict):
        """Handles sta=!RESP_STA_SUCCESS"""
        _LOGGER.debug(
            "Account %s had a unsuccessful response %s",
            self.customer_number,
            response_data,
        )
        if response_data["sta"] == RESP_STA_NO_LOGIN:
            raise NotLoggedIn(response_data["sta"], response_data.get("message"))
        raise CSGAPIError(response_data["sta"], response_data.get("message"))

    # end internal utility functions

    # begin raw api functions
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
            "logonChan": LOGON_CHANNEL_HANDHELD_HALL,
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
            "logonChan": LOGON_CHANNEL_HANDHELD_HALL,
            "credType": LOGIN_TYPE_PHONE_PWD,
            "credentials": encrypt_credential(password),
        }
        payload = {"param": encrypt_params(payload)}
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_header["x-auth-token"]
        if resp_data["sta"] == RESP_STA_LOGIN_WRONG_CREDENTIAL:
            raise InvalidCredentials(resp_data["sta"], resp_data.get("message"))
        self._handle_unsuccessful_response(resp_data)

    def api_query_authentication_result(self) -> dict[str, Any]:
        """Contains custNumber, used to verify login"""
        path = "user/queryAuthenticationResult"
        payload = None
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_user_info(self) -> dict[str, Any]:
        """Get account info"""
        path = "user/getUserInfo"
        payload = None
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_all_linked_electricity_accounts(self) -> list[dict[str, Any]]:
        """List all linked electricity accounts under this account"""
        path = "eleCustNumber/queryBindEleUsers"
        _, resp_data = self._make_request(path, {})
        if resp_data["sta"] == RESP_STA_SUCCESS:
            _LOGGER.debug("Total %d users under this account", len(resp_data["data"]))
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_metering_point(
        self,
        area_code: str,
        ele_customer_id: str,
    ) -> dict:
        """Get metering point id"""
        path = "charge/queryMeteringPoint"
        payload = {
            "areaCode": area_code,
            "eleCustNumberList": [
                {"eleCustId": ele_customer_id, "areaCode": area_code}
            ],
        }
        custom_headers = {"funid": "100t002"}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_day_electric_by_m_point(
        self,
        year: int,
        month: int,
        area_code: str,
        ele_customer_id: str,
        metering_point_id: str,
    ) -> dict:
        """get usage(kWh) by day in the given month"""
        path = "charge/queryDayElectricByMPoint"
        payload = {
            "areaCode": area_code,
            "eleCustId": ele_customer_id,
            "yearMonth": f"{year}{month:02d}",
            "meteringPointId": metering_point_id,
        }
        custom_headers = {"funid": "100t002"}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_account_surplus(self, area_code: str, ele_customer_id: str):
        """Contains: balance and arrears"""
        path = "charge/queryUserAccountNumberSurplus"
        payload = {"areaCode": area_code, "eleCustId": ele_customer_id}
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_get_fee_analyze_details(
        self, year: int, area_code: str, ele_customer_id: str
    ):
        """
        Contains: year total kWh, year total charge, kWh/charge by month in current year
        """
        path = "charge/getAnalyzeFeeDetails"
        payload = {
            "areaCode": area_code,
            "electricityBillYear": year,
            "eleCustId": ele_customer_id,
            "meteringPointId": None,  # this is set to null in api
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_day_electric_by_m_point_yesterday(
        self,
        area_code: str,
        ele_customer_id: str,
    ) -> dict:
        """Contains: power consumption(kWh) of yesterday"""
        path = "charge/queryDayElectricByMPointYesterday"
        payload = {"eleCustId": ele_customer_id, "areaCode": area_code}
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_query_charges(self, area_code: str, ele_customer_id: str, _type="0"):
        """Contains: balance and arrears, metering points"""
        path = "charge/queryCharges"
        payload = {
            "areaCode": area_code,
            "eleModels": [{"eleCustId": ele_customer_id, "areaCode": area_code}],
            "type": _type,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    def api_logout(self, logon_chan: str, cred_type) -> None:
        """logout"""
        path = "center/logout"
        payload = {"logonChan": logon_chan, "credType": cred_type}
        _, resp_data = self._make_request(path, payload)
        if resp_data["sta"] == RESP_STA_SUCCESS:
            return resp_data["data"]
        self._handle_unsuccessful_response(resp_data)

    # end raw api functions

    # begin utility functions
    @staticmethod
    def load(data: dict[str, str]) -> CSGClient:
        """
        Restore the session info to client object
        The validity of the session won't be checked
        `initialize()` needs to be called for the client to be usable
        """
        for k in (ATTR_AUTH_TOKEN, ATTR_LOGIN_TYPE):
            if not data.get(k):
                raise ValueError(f"missing parameter: {k}")
        client = CSGClient(
            auth_token=data[ATTR_AUTH_TOKEN],
            login_type=LoginType(data[ATTR_LOGIN_TYPE]),
        )
        return client

    def dump(self) -> dict[str, Any]:
        """Dump the session to dict"""
        return {
            ATTR_AUTH_TOKEN: self.auth_token,
            ATTR_LOGIN_TYPE: self.login_type.value,
        }

    def set_authentication_params(self, auth_token: str, login_type: LoginType):
        """Set self.auth_token and client generated cookies"""
        self.auth_token = auth_token
        self.login_type = login_type

    def authenticate(self, phone_no: str, password: str):
        """
        Authenticate the client using phone number and password
        Will set session parameters
        """
        auth_token = self.api_login_with_password(phone_no, password)
        self.set_authentication_params(auth_token, LoginType.LOGIN_TYPE_PWD)

    def initialize(self):
        """Initialize the client"""
        resp_data = self.api_get_user_info()
        self.customer_number = resp_data["custNumber"]

    def verify_login(self) -> bool:
        """Verify validity of the session"""
        try:
            self.api_query_authentication_result()
        except NotLoggedIn:
            return False
        return True

    def logout(self):
        """Logout and reset identifier, token etc."""
        self.api_logout(LOGON_CHANNEL_HANDHELD_HALL, self.login_type.value)
        self.auth_token = ""
        self.login_type = LoginType.LOGIN_TYPE_PWD
        self.customer_number = ""

    # end utility functions

    # begin high-level api wrappers

    def get_all_electricity_accounts(self) -> list[CSGElectricityAccount]:
        """Get all electricity accounts linked to current account"""
        result = []
        ele_user_resp_data = self.api_get_all_linked_electricity_accounts()

        for item in ele_user_resp_data:
            metering_point_data = self.api_get_metering_point(
                item["areaCode"], item["bindingId"]
            )
            metering_point_id = metering_point_data[0]["meteringPointId"]
            account = CSGElectricityAccount(
                item["eleCustNumber"],
                item["areaCode"],
                item["bindingId"],
                metering_point_id,
                item["eleAddress"],
                item["userName"],
            )
            result.append(account)
        return result

    def get_month_daily_usage_detail(
        self, account: CSGElectricityAccount, year_month: tuple[int, int]
    ) -> tuple[float, list[dict[str, str | float]]]:
        """Get daily usage of current month"""

        year, month = year_month

        resp_data = self.api_query_day_electric_by_m_point(
            year,
            month,
            account.area_code,
            account.ele_customer_id,
            account.metering_point_id,
        )
        month_total_kwh = float(resp_data["totalPower"])
        by_day = []
        for d_data in resp_data["result"]:
            by_day.append({"date": d_data["date"], "kwh": float(d_data["power"])})
        return month_total_kwh, by_day

    def get_balance_and_arrears(
        self, account: CSGElectricityAccount
    ) -> tuple[float, float]:
        """Get account balance and arrears"""

        resp_data = self.api_query_account_surplus(
            account.area_code, account.ele_customer_id
        )
        balance = resp_data[0]["balance"]
        arrears = resp_data[0]["arrears"]
        return float(balance), float(arrears)

    def get_year_month_stats(
        self, account: CSGElectricityAccount, year
    ) -> tuple[float, float, list[dict[str, str | float]]]:
        """Get year total kWh, year total charge, kWh/charge by month in current year"""

        resp_data = self.api_get_fee_analyze_details(
            year, account.area_code, account.ele_customer_id
        )

        total_year_kwh = resp_data["totalBillingElectricity"]
        total_year_charge = resp_data["totalActualAmount"]
        by_month = []
        for m_data in resp_data["electricAndChargeList"]:
            by_month.append(
                {
                    "month": m_data["yearMonth"],
                    "charge": float(m_data["actualTotalAmount"]),
                    "kwh": float(m_data["billingElectricity"]),
                }
            )
        return float(total_year_charge), float(total_year_kwh), by_month

    def get_yesterday_kwh(self, account: CSGElectricityAccount) -> float:
        """Get power consumption(kwh) of yesterday"""
        resp_data = self.api_query_day_electric_by_m_point_yesterday(
            account.area_code, account.ele_customer_id
        )
        return float(resp_data["power"])

    # end high-level api wrappers
