# -*- coding: utf-8 -*-
"""
Implementations of CSG's Web API
this library is synchronous - since the updates are not frequent (12h+)
and each update only contains a few requests
"""
from __future__ import annotations

import datetime
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

    def __init__(self, sta: str, msg: str | None = None) -> None:
        """sta: status code, msg: message"""
        Exception.__init__(self)
        self.sta = sta
        self.msg = msg

    def __str__(self):
        return f"<CSGAPIError sta={self.sta} message={self.msg}>"


class CSGHTTPError(CSGAPIError):
    """Unexpected HTTP status code (!=200)"""

    def __init__(self, code: int) -> None:
        CSGAPIError.__init__(self, sta=f"HTTP{code}")
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
            HEADER_X_AUTH_TOKEN: "",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko)",
            HEADER_CUST_NUMBER: "",
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
            
            json_str = response.content.decode('utf-8', errors='ignore')
            json_str = json_str[json_str.find('{'):json_str.rfind('}')+1]
            json_data = json.loads(json_str)
            response_data = json_data
            _LOGGER.debug("_make_request: response: %s", json.dumps(response_data))

            # headers need to be returned since they may contain additional data
            return response.headers, response_data

        raise NotImplementedError()

    def _handle_unsuccessful_response(self, api_path: str, response_data: dict):
        """Handles sta=!RESP_STA_SUCCESS"""
        _LOGGER.debug(
            "Account customer number: %s, unsuccessful response while calling %s: %s",
            self.customer_number,
            api_path,
            response_data,
        )

        if response_data[JSON_KEY_STA] == RESP_STA_NO_LOGIN:
            raise NotLoggedIn(
                response_data[JSON_KEY_STA], response_data.get(JSON_KEY_MESSAGE)
            )
        raise CSGAPIError(
            response_data[JSON_KEY_STA], response_data.get(JSON_KEY_MESSAGE)
        )

    # end internal utility functions

    # begin raw api functions
    def api_send_login_sms(self, phone_no: str):
        """Send SMS verification code to phone_no"""
        path = "center/sendMsg"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            "phoneNumber": phone_no,
            "vcType": VERIFICATION_CODE_TYPE_LOGIN,
            "msgType": SEND_MSG_TYPE_VERIFICATION_CODE,
        }
        _, resp_data = self._make_request(path, payload, with_auth=False)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return True
        self._handle_unsuccessful_response(path, resp_data)

    def api_login_with_sms_code(self, phone_no: str, code: str):
        """Login with phone number and SMS code"""
        path = "center/login"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            JSON_KEY_ACCT_ID: phone_no,
            JSON_KEY_LOGON_CHAN: LOGON_CHANNEL_HANDHELD_HALL,
            JSON_KEY_CRED_TYPE: LOGIN_TYPE_PHONE_CODE,
            "code": code,
        }
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_header[HEADER_X_AUTH_TOKEN]
        self._handle_unsuccessful_response(path, resp_data)

    def api_login_with_password(self, phone_no: str, password: str, code: str):
        """Login with phone number and password"""
        path = "center/loginByPwdAndMsg"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            JSON_KEY_ACCT_ID: phone_no,
            JSON_KEY_LOGON_CHAN: LOGON_CHANNEL_HANDHELD_HALL,
            JSON_KEY_CRED_TYPE: LOGIN_TYPE_PHONE_PWD,
            "credentials": encrypt_credential(password),
            "code": code,
            "checkPwd": True
        }
        payload = {"param": encrypt_params(payload)}
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_header[HEADER_X_AUTH_TOKEN]
        if resp_data[JSON_KEY_STA] == RESP_STA_LOGIN_WRONG_CREDENTIAL:
            raise InvalidCredentials(
                resp_data[JSON_KEY_STA], resp_data.get(JSON_KEY_MESSAGE)
            )
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_authentication_result(self) -> dict[str, Any]:
        """Contains custNumber, used to verify login"""
        path = "user/queryAuthenticationResult"
        payload = None
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_get_user_info(self) -> dict[str, Any]:
        """Get account info"""
        path = "user/getUserInfo"
        payload = None
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_get_all_linked_electricity_accounts(self) -> list[dict[str, Any]]:
        """List all linked electricity accounts under this account"""
        path = "eleCustNumber/queryBindEleUsers"
        _, resp_data = self._make_request(path, {})
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            _LOGGER.debug(
                "Total %d users under this account", len(resp_data[JSON_KEY_DATA])
            )
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_get_metering_point(
        self,
        area_code: str,
        ele_customer_id: str,
    ) -> dict:
        """Get metering point id"""
        path = "charge/queryMeteringPoint"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            "eleCustNumberList": [
                {JSON_KEY_ELE_CUST_ID: ele_customer_id, JSON_KEY_AREA_CODE: area_code}
            ],
        }
        custom_headers = {"funid": "100t002"}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

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
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_YEAR_MONTH: f"{year}{month:02d}",
            JSON_KEY_METERING_POINT_ID: metering_point_id,
        }
        custom_headers = {"funid": "100t002"}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_day_electric_charge_by_m_point(
        self,
        year: int,
        month: int,
        area_code: str,
        ele_customer_id: str,
        metering_point_id: str,
    ) -> dict:
        """get charge by day in the given month
        KNOWN BUG: this api call returns the daily cost data of year_month, but the ladder data will be this month's
        this api call could take a long time to return (~30s)
        """
        path = "charge/queryDayElectricChargeByMPoint"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_YEAR_MONTH: f"{year}{month:02d}",
            JSON_KEY_METERING_POINT_ID: metering_point_id,
        }
        custom_headers = {"funid": "100t002"}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_account_surplus(self, area_code: str, ele_customer_id: str):
        """Contains: balance and arrears"""
        path = "charge/queryUserAccountNumberSurplus"
        payload = {JSON_KEY_AREA_CODE: area_code, JSON_KEY_ELE_CUST_ID: ele_customer_id}
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_get_fee_analyze_details(
        self, year: int, area_code: str, ele_customer_id: str
    ):
        """
        Contains: year total kWh, year total charge, kWh/charge by month in current year
        """
        path = "charge/getAnalyzeFeeDetails"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            "electricityBillYear": year,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_METERING_POINT_ID: None,  # this is set to null in api
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_day_electric_by_m_point_yesterday(
        self,
        area_code: str,
        ele_customer_id: str,
    ) -> dict:
        """Contains: power consumption(kWh) of yesterday"""
        path = "charge/queryDayElectricByMPointYesterday"
        payload = {JSON_KEY_ELE_CUST_ID: ele_customer_id, JSON_KEY_AREA_CODE: area_code}
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_charges(self, area_code: str, ele_customer_id: str, _type="0"):
        """Contains: balance and arrears, metering points"""
        path = "charge/queryCharges"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            "eleModels": [
                {JSON_KEY_ELE_CUST_ID: ele_customer_id, JSON_KEY_AREA_CODE: area_code}
            ],
            "type": _type,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_logout(self, logon_chan: str, cred_type) -> None:
        """logout"""
        path = "center/logout"
        payload = {JSON_KEY_LOGON_CHAN: logon_chan, JSON_KEY_CRED_TYPE: cred_type}
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

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

    def authenticate(self, phone_no: str, password: str, code: str):
        """
        Authenticate the client using phone number and password
        Will set session parameters
        """
        auth_token = self.api_login_with_password(phone_no, password, code)
        self.set_authentication_params(auth_token, LoginType.LOGIN_TYPE_PWD)

    def initialize(self):
        """Initialize the client"""
        resp_data = self.api_get_user_info()
        self.customer_number = resp_data[JSON_KEY_CUST_NUMBER]

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
                item[JSON_KEY_AREA_CODE], item["bindingId"]
            )
            metering_point_id = metering_point_data[0][JSON_KEY_METERING_POINT_ID]
            account = CSGElectricityAccount(
                item["eleCustNumber"],
                item[JSON_KEY_AREA_CODE],
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
            by_day.append(
                {WF_ATTR_DATE: d_data["date"], WF_ATTR_KWH: float(d_data["power"])}
            )
        return month_total_kwh, by_day

    def get_month_daily_cost_detail(
        self, account: CSGElectricityAccount, year_month: tuple[int, int]
    ) -> tuple[float | None, float | None, dict, list[dict[str, str | float]]]:
        """Get daily cost of current month"""

        year, month = year_month

        resp_data = self.api_query_day_electric_charge_by_m_point(
            year,
            month,
            account.area_code,
            account.ele_customer_id,
            account.metering_point_id,
        )

        by_day = []
        for d_data in resp_data["result"]:
            by_day.append(
                {
                    WF_ATTR_DATE: d_data["date"],
                    WF_ATTR_CHARGE: float(d_data["charge"]),
                    WF_ATTR_KWH: float(d_data["power"]),
                }
            )

        # sometimes the data by day is present, but the total amount and ladder are not

        if resp_data["totalElectricity"] is not None:
            month_total_cost = float(resp_data["totalElectricity"])
        else:
            month_total_cost = None

        if resp_data["totalPower"] is not None:
            month_total_kwh = float(resp_data["totalPower"])
        else:
            month_total_kwh = None

        # sometimes the ladder info is null, handle that
        if resp_data["ladderEle"] is not None:
            current_ladder = int(resp_data["ladderEle"])
        else:
            current_ladder = None
        # "2023-05-01 00:00:00.0"
        if resp_data["ladderEleStartDate"] is not None:
            current_ladder_start_date = datetime.datetime.strptime(
                resp_data["ladderEleStartDate"], "%Y-%m-%d %H:%M:%S.%f"
            )
        else:
            current_ladder_start_date = None
        if resp_data["ladderEleSurplus"] is not None:
            current_ladder_remaining_kwh = float(resp_data["ladderEleSurplus"])
        else:
            current_ladder_remaining_kwh = None
        if resp_data["ladderEleTariff"] is not None:
            current_tariff = float(resp_data["ladderEleTariff"])
        else:
            current_tariff = None
        # TODO what will happen to `current_ladder_remaining_kwh` when it's the last ladder?
        ladder = {
            WF_ATTR_LADDER: current_ladder,
            WF_ATTR_LADDER_START_DATE: current_ladder_start_date,
            WF_ATTR_LADDER_REMAINING_KWH: current_ladder_remaining_kwh,
            WF_ATTR_LADDER_TARIFF: current_tariff,
        }

        return month_total_cost, month_total_kwh, ladder, by_day

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
                    WF_ATTR_MONTH: m_data[JSON_KEY_YEAR_MONTH],
                    WF_ATTR_CHARGE: float(m_data["actualTotalAmount"]),
                    WF_ATTR_KWH: float(m_data["billingElectricity"]),
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

