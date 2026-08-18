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
        metering_point_number: str | None = None,
        address: str | None = None,
        user_name: str | None = None,
    ) -> None:
        # the parameters are independent for each electricity account

        # the 16-digit billing number, as a unique identifier, not used in api for now
        self.account_number = account_number

        self.area_code = area_code

        # this may change on every login, alternative name in js code is `binding_id`
        self.ele_customer_id = ele_customer_id

        # in fact one account may have multiple metering points,
        # however for individual users there should only be one
        self.metering_point_id = metering_point_id
        self.metering_point_number = metering_point_number

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
            ATTR_METERING_POINT_NUMBER: self.metering_point_number,
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
        # ATTR_METERING_POINT_NUMBER is added in later version, skip check here
        # TODO: add ATTR_METERING_POINT_NUMBER to the check in the future
        account = CSGElectricityAccount(
            account_number=data[ATTR_ACCOUNT_NUMBER],
            area_code=data[ATTR_AREA_CODE],
            ele_customer_id=data[ATTR_ELE_CUSTOMER_ID],
            metering_point_id=data[ATTR_METERING_POINT_ID],
            metering_point_number=data.get(ATTR_METERING_POINT_NUMBER),
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
    First call one of the functions to login (see example code)
    Then call `CSGClient.initialize` *important
    To get all linked electricity accounts, call `get_all_electricity_accounts`
    Use the account objects to call the utility functions and wrapped api functions
    """

    def __init__(
        self,
        auth_token: str | None = None,
    ) -> None:
        self._session: requests.Session = requests.Session()
        self._common_headers = {
            "Host": "95598.csg.cn",
            "Content-Type": "application/json;charset=utf-8",
            "Origin": "file://",
            HEADER_X_AUTH_TOKEN: "",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko)",
            HEADER_CUST_NUMBER: "",
            "Accept-Language": "zh-CN,cn;q=0.9",
        }

        self.auth_token = auth_token

        # identifier, need to be set in initialize()
        self.customer_number = None

    # begin internal utility functions
    def _make_request(
        self,
        path: str,
        payload: dict | None,
        with_auth: bool = True,
        method: str = "POST",
        custom_headers: dict | None = None,
        base_path: str = BASE_PATH_APP,
    ):
        """
        Function to make the http request to api endpoints
        can automatically add authentication header(s)
        """
        _LOGGER.debug(
            "_make_request: %s, data=%s, auth=%s, method=%s",
            path,
            payload,
            with_auth,
            method,
        )
        url = base_path + path
        headers = copy(self._common_headers)
        if custom_headers:
            for _k, _v in custom_headers.items():
                headers[_k] = _v
        if with_auth:
            headers[HEADER_X_AUTH_TOKEN] = self.auth_token
            headers[HEADER_CUST_NUMBER] = self.customer_number
        if method == "POST":
            # timeout=(connect, read) to prevent hung requests from blocking
            # the executor thread forever (which deadlocks entry unload)
            response = self._session.post(
                url, json=payload, headers=headers, timeout=(10, 60)
            )
            if response.status_code != 200:
                _LOGGER.error(
                    "API call %s returned status code %d", path, response.status_code
                )
                raise CSGHTTPError(response.status_code)

            json_str = response.content.decode("utf-8", errors="ignore")
            json_str = json_str[json_str.find("{") : json_str.rfind("}") + 1]
            json_data = json.loads(json_str)
            response_data = json_data
            _LOGGER.debug(
                "_make_request: %s, response: %s",
                path,
                json.dumps(response_data, ensure_ascii=False),
            )

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
        """Send SMS verification code to phone_no
        Note this is not the function for login with SMS, it only requests to send the code
        """
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

    def api_create_login_qr_code(
        self, channel: QRCodeType, login_id: str | None = None
    ) -> (str, str):
        """Request API to create a QR code for login
        Returns login_id and link to QR code image
        """
        path = "center/createLoginQrcode"

        login_id = login_id or generate_qr_login_id()
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            "channel": channel,
            # NOTE: this spell error is intentional
            "lgoinId": login_id,
        }
        _, resp_data = self._make_request(
            path, payload, with_auth=False, base_path=BASE_PATH_WEB
        )
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return login_id, resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_get_qr_login_status(self, login_id: str) -> (bool, str):
        """Get login status of the QR code"""
        path = "center/getLoginInfo"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            # this one is the correct spelling
            "loginId": login_id,
        }
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, base_path=BASE_PATH_WEB
        )
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return True, resp_header[HEADER_X_AUTH_TOKEN]
        if resp_data[JSON_KEY_STA] == RESP_STA_QR_NOT_SCANNED:
            return False, ""
        self._handle_unsuccessful_response(path, resp_data)

    def api_login_with_sms_code(self, phone_no: str, sms_code: str):
        """Login with phone number and SMS code"""
        path = "center/login"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            JSON_KEY_ACCT_ID: phone_no,
            JSON_KEY_LOGON_CHAN: LOGON_CHANNEL_HANDHELD_HALL,
            JSON_KEY_CRED_TYPE: LOGIN_TYPE_PHONE_CODE,
            JSON_KEY_SMS_CODE: sms_code,
        }
        payload = {JSON_KEY_PARAM: encrypt_params(payload)}
        resp_header, resp_data = self._make_request(
            path, payload, with_auth=False, custom_headers={"need-crypto": "true"}
        )
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_header[HEADER_X_AUTH_TOKEN]
        self._handle_unsuccessful_response(path, resp_data)

    def api_login_with_password_and_sms_code(
        self, phone_no: str, password: str, sms_code: str
    ):
        """Login with phone number, SMS code and password"""
        path = "center/loginByPwdAndMsg"
        payload = {
            JSON_KEY_AREA_CODE: AREACODE_FALLBACK,
            JSON_KEY_ACCT_ID: phone_no,
            JSON_KEY_LOGON_CHAN: LOGON_CHANNEL_HANDHELD_HALL,
            JSON_KEY_CRED_TYPE: LOGIN_TYPE_PHONE_PWD_CODE,
            "credentials": encrypt_credential(password),
            JSON_KEY_SMS_CODE: sms_code,
            "checkPwd": True,
        }
        payload = {JSON_KEY_PARAM: encrypt_params(payload)}
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
        # custom_headers = {"funid": "100t002"}
        custom_headers = {}
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
        # custom_headers = {"funid": "100t002"}
        custom_headers = {}
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
        KNOWN BUG: this api call returns the daily cost data of year_month,
        but the ladder data will be this month's.
        this api call could take a long time to return (~30s)
        """
        path = "charge/queryDayElectricChargeByMPoint"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_YEAR_MONTH: f"{year}{month:02d}",
            JSON_KEY_METERING_POINT_ID: metering_point_id,
        }
        # custom_headers = {"funid": "100t002"}  # TODO: what does this do? region?
        custom_headers = {}
        _, resp_data = self._make_request(path, payload, custom_headers=custom_headers)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_day_electric_and_temperature(
        self,
        year: int,
        month: int,
        area_code: str,
        ele_customer_id: str,
        metering_point_id: str,
    ) -> dict:
        """get power in kWh, hi/lo temperature by day in the given month"""
        path = "charge/queryDayElectricAndTemperature"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_YEAR_MONTH: f"{year}{month:02d}",
            JSON_KEY_METERING_POINT_ID: metering_point_id,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_electricity_calender(
        self,
        year: int,
        month: int,
        area_code: str,
        ele_customer_id: str,
        metering_point_id: str,
        metering_point_number: str,
    ) -> dict:
        """get power in kWh, hi/lo/avg temperature by day in the given month"""
        path = "charge/queryElectricityCalendar"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_YEAR_MONTH: f"{year}{month:02d}",
            JSON_KEY_METERING_POINT_ID: metering_point_id,
            "deviceIdentif": metering_point_number,
        }
        _, resp_data = self._make_request(path, payload)
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

    def api_query_annual_electricity_tier_info(
        self, area_code: str, ele_customer_id: str, metering_point_id: str, year_month: tuple[int, int]
    ) -> dict:
        """Query annual electricity tier (ladder) pricing information

        Returns complete ladder tier information including:
        - Current tier and tariff
        - Yearly cumulative consumption
        - Remaining kWh to next tier
        - All tier definitions

        Args:
            area_code: Area code (e.g., "050100")
            ele_customer_id: Electricity customer ID
            metering_point_id: Metering point ID
            year_month: Tuple of (year, month) for the query
        """
        year, month = year_month
        path = "charge/queryAnnualElectricityTierInfo"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            JSON_KEY_ELE_CUST_ID: ele_customer_id,
            JSON_KEY_METERING_POINT_ID: metering_point_id,
            "yearMonth": f"{year}{month:02d}",
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_query_calendar_ladder_trip_stop(
        self, area_code: str, ele_cust_number: str
    ) -> dict:
        """Query ladder (tiered pricing) information from calendar

        Returns complete ladder tier information including:
        - Current ladder tier and tariff
        - Remaining kWh to next tier
        - Yearly ladder total consumption
        - All available ladder tiers with pricing
        """
        path = "ltsn/queryCalendarLadderTripStop"
        payload = {
            JSON_KEY_AREA_CODE: area_code,
            "eleCustNumber": ele_cust_number,
        }
        _, resp_data = self._make_request(path, payload)
        if resp_data[JSON_KEY_STA] == RESP_STA_SUCCESS:
            return resp_data[JSON_KEY_DATA]
        self._handle_unsuccessful_response(path, resp_data)

    def api_logout(self, logon_chan: str, cred_type: LoginType) -> None:
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
        for k in (ATTR_AUTH_TOKEN,):
            if not data.get(k):
                raise ValueError(f"missing parameter: {k}")
        client = CSGClient(
            auth_token=data[ATTR_AUTH_TOKEN],
        )
        return client

    def dump(self) -> dict[str, Any]:
        """Dump the session to dict"""
        return {
            ATTR_AUTH_TOKEN: self.auth_token,
        }

    def set_authentication_params(self, auth_token: str):
        """Set self.auth_token and client generated cookies"""
        self.auth_token = auth_token

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

    def logout(self, login_type: LoginType):
        """Logout and reset identifier, token etc."""
        self.api_logout(LOGON_CHANNEL_HANDHELD_HALL, login_type)
        self.auth_token = None
        self.customer_number = None

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
            metering_point_number = metering_point_data[0][
                JSON_KEY_METERING_POINT_NUMBER
            ]
            account = CSGElectricityAccount(
                account_number=item["eleCustNumber"],
                area_code=item[JSON_KEY_AREA_CODE],
                ele_customer_id=item["bindingId"],
                metering_point_id=metering_point_id,
                metering_point_number=metering_point_number,
                address=item["eleAddress"],
                user_name=item["userName"],
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
        """Get daily cost of current month

        Implements fallback to yearly stats when primary API fails due to server errors.
        """

        year, month = year_month

        # Try primary API first, fall back to yearly stats on API error
        try:
            resp_data = self.api_query_day_electric_charge_by_m_point(
                year,
                month,
                account.area_code,
                account.ele_customer_id,
                account.metering_point_id,
            )
        except CSGAPIError as api_err:
            _LOGGER.warning(
                "Primary month detail API failed: %s. Using fallback method.",
                api_err
            )
            return self._get_month_detail_from_year_stats(account, year_month)

        by_day = []
        for d_data in resp_data["result"]:
            charge = None
            if d_data.get("charge") is not None:
                charge = float(d_data["charge"])
            # Calculate daily cost from power and tariff if charge is not available
            elif d_data.get("power") is not None and resp_data.get("ladderEleTariff") is not None:
                power = float(d_data["power"])
                tariff = float(resp_data["ladderEleTariff"])
                charge = round(power * tariff, 2)

            by_day.append(
                {
                    WF_ATTR_DATE: d_data["date"],
                    WF_ATTR_CHARGE: charge,
                    WF_ATTR_KWH: float(d_data["power"]) if d_data.get("power") is not None else None,
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

        # Calculate cost from usage and tariff if cost is not available
        # Note: This is an approximation as tiered pricing may change during the month
        if month_total_cost is None and month_total_kwh is not None and current_tariff is not None:
            month_total_cost = round(month_total_kwh * current_tariff, 2)
            _LOGGER.debug(
                "Calculated month_total_cost from usage: %s kWh × %s = %s",
                month_total_kwh,
                current_tariff,
                month_total_cost,
            )
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

    def _get_month_detail_from_year_stats(
        self, account: CSGElectricityAccount, year_month: tuple[int, int]
    ) -> tuple[float | None, float | None, dict, list[dict[str, str | float]]]:
        """Fallback method to get month detail from yearly stats when primary API fails

        This is used when api_query_day_electric_charge_by_m_point fails with server errors.
        It extracts the current month data from the yearly stats' electricAndChargeList.

        For the current month (when bill is not ready yet):
        - Try to get usage from usage API
        - Calculate cost from usage × tier price
        - Calculate current tier and remaining kWh from yearly accumulation
        """
        from .const import LADDER_TIER_DEFINITIONS

        year, month = year_month
        now = datetime.datetime.now()
        is_current_month = (year == now.year and month == now.month)

        _LOGGER.warning(
            "Primary API failed, using fallback method for month %s-%s (is_current=%s)",
            year, month, is_current_month
        )

        resp_data = self.api_get_fee_analyze_details(
            year, account.area_code, account.ele_customer_id
        )

        month_str = f"{year}-{month:02d}"

        # Find current month data from the list
        month_total_cost = None
        month_total_kwh = None
        for m_data in resp_data["electricAndChargeList"]:
            if m_data[JSON_KEY_YEAR_MONTH] == month_str:
                month_total_cost = float(m_data["actualTotalAmount"])
                month_total_kwh = float(m_data["billingElectricity"])
                break

        # If current month and not in yearly stats yet, try to get usage and calculate
        if month_total_kwh is None and is_current_month:
            _LOGGER.info("Current month not in yearly stats, trying to get usage data")
            try:
                # Try to get usage from the usage API (this might still work)
                month_total_kwh, _ = self.get_month_daily_usage_detail(account, year_month)
            except Exception as e:
                _LOGGER.warning("Failed to get current month usage: %s", e)

        # Calculate tier info from yearly accumulation
        # Get total year kWh to determine current tier
        total_year_kwh = resp_data.get("totalBillingElectricity", 0)
        if total_year_kwh is not None:
            total_year_kwh = float(total_year_kwh)
        else:
            total_year_kwh = 0.0

        # Determine current tier based on yearly accumulation
        current_ladder = None
        current_ladder_tariff = None
        current_ladder_remaining_kwh = None

        # Find which tier we're in based on yearly accumulation
        for tier_num, tier_key in enumerate(["tier_1", "tier_2", "tier_3", "tier_4"], 1):
            tier = LADDER_TIER_DEFINITIONS[tier_key]
            range_min = tier["range_min"]
            range_max = tier["range_max"]
            price = tier["price"]

            if range_max is None:
                # Last tier (no upper limit)
                if total_year_kwh >= range_min:
                    current_ladder = tier_num
                    current_ladder_tariff = price
                    current_ladder_remaining_kwh = None  # No limit for last tier
            else:
                if range_min <= total_year_kwh <= range_max:
                    current_ladder = tier_num
                    current_ladder_tariff = price
                    current_ladder_remaining_kwh = range_max - total_year_kwh
                    break
                elif total_year_kwh < range_min:
                    # Haven't reached this tier yet, use previous tier
                    if tier_num > 1:
                        prev_tier = LADDER_TIER_DEFINITIONS[f"tier_{tier_num - 1}"]
                        current_ladder = tier_num - 1
                        current_ladder_tariff = prev_tier["price"]
                        prev_max = prev_tier["range_max"]
                        if prev_max is not None:
                            current_ladder_remaining_kwh = prev_max - total_year_kwh
                    break

        # Calculate cost if we have usage but no cost. Prefer the real
        # average unit price from settled bills: time-of-use accounts
        # (e.g. EV charging piles) cannot be estimated from the flat
        # tier tariff.
        if month_total_cost is None and month_total_kwh is not None:
            bill_cost = 0.0
            bill_kwh = 0.0
            for m_data in resp_data.get("electricAndChargeList", []):
                try:
                    bill_cost += float(m_data["actualTotalAmount"])
                    bill_kwh += float(m_data["billingElectricity"])
                except (KeyError, TypeError, ValueError):
                    continue
            est_price = (
                bill_cost / bill_kwh if bill_kwh > 0 else current_ladder_tariff
            )
            if est_price is not None:
                month_total_cost = round(month_total_kwh * est_price, 2)
                _LOGGER.info(
                    "Calculated month cost from usage: %s kWh × %s (avg) = %s CNY",
                    month_total_kwh, round(est_price, 4), month_total_cost,
                )

        ladder = {
            WF_ATTR_LADDER: current_ladder,
            WF_ATTR_LADDER_START_DATE: None,  # Not available in fallback
            WF_ATTR_LADDER_REMAINING_KWH: current_ladder_remaining_kwh,
            WF_ATTR_LADDER_TARIFF: current_ladder_tariff,
        }

        by_day = []  # Fallback doesn't provide daily data

        _LOGGER.info(
            "Fallback method retrieved: %s kWh, %s CNY for %s (tier %d, %.4f CNY/kWh, remaining: %s kWh)",
            month_total_kwh, month_total_cost, month_str,
            current_ladder, current_ladder_tariff, current_ladder_remaining_kwh
        )

        return month_total_cost, month_total_kwh, ladder, by_day

    def get_yesterday_kwh(self, account: CSGElectricityAccount) -> float:
        """Get power consumption(kwh) of yesterday"""
        resp_data = self.api_query_day_electric_by_m_point_yesterday(
            account.area_code, account.ele_customer_id
        )
        if resp_data.get("power") is not None:
            return float(resp_data["power"])
        return 0.0

    def get_yearly_ladder_info(
        self, account: CSGElectricityAccount, year: int
    ) -> dict:
        """Get yearly ladder (tiered pricing) cumulative consumption
        Returns dict with:
        - total_kwh: Yearly cumulative consumption for tiered pricing calculation
        """
        # Get year's total consumption from fee analyze
        total_year_charge, total_year_kwh, _ = self.get_year_month_stats(
            account, year
        )

        return {
            WF_ATTR_YEARLY_LADDER_TOTAL_KWH: total_year_kwh,
        }

    def get_calendar_ladder_info(
        self, account: CSGElectricityAccount, year_month: tuple[int, int]
    ) -> dict:
        """Get complete ladder (tiered pricing) information from annual tier info API

        This is a dedicated API that returns complete ladder tier information directly,
        including current tier, tariff, remaining kWh, and all available tiers.

        Returns dict with:
        - ladder: Current ladder tier (1-4)
        - tariff: Current ladder tariff (CNY/kWh)
        - remaining_kwh: Remaining kWh to next tier
        - start_date: Ladder period start date
        - end_date: Ladder period end date
        - yearly_ladder_total_kwh: Yearly cumulative consumption
        - all_tiers: List of all available tiers with pricing
        """
        import datetime

        resp_data = self.api_query_annual_electricity_tier_info(
            account.area_code,
            account.ele_customer_id,
            account.metering_point_id,
            year_month
        )

        # Parse current ladder name to extract tier number
        # E.g., "【电能替代】" → 1, "【居民阶梯一】" → 2
        current_gear_name = resp_data.get("currentGear", "")
        current_ladder = None

        # Map ladder names to tier numbers
        ladder_name_to_tier = {
            "电能替代": 1,
            "居民阶梯一": 2,
            "居民阶梯二": 3,
            "居民阶梯三": 4,
        }

        # Extract name from brackets
        for name, tier_num in ladder_name_to_tier.items():
            if name in current_gear_name:
                current_ladder = tier_num
                break

        # If current_ladder is still None, try to determine from ladderInfoList
        if current_ladder is None:
            total_electricity = float(resp_data.get("totalElectricityOfYear", 0))
            for i, tier_info in enumerate(resp_data.get("ladderInfoList", []), 1):
                threshold_bottom = int(tier_info.get("threshholdBottom", 0))
                threshold_top = int(tier_info.get("threshholdTop", 9999999))
                if threshold_bottom <= total_electricity <= threshold_top:
                    current_ladder = i
                    break

        # Parse ladder info list
        ladder_list = []
        for tier_info in resp_data.get("ladderInfoList", []):
            ladder_list.append({
                "name": tier_info.get("ladderName"),
                "price": float(tier_info.get("priceValue", 0)),
                "range_min": int(tier_info.get("threshholdBottom", 0)),
                "range_max": int(tier_info.get("threshholdTop", 0)),
            })

        ladder_info = {
            WF_ATTR_LADDER: current_ladder,
            WF_ATTR_LADDER_TARIFF: float(resp_data.get("currentElectricityPrice", 0)) if resp_data.get("currentElectricityPrice") else None,
            WF_ATTR_LADDER_REMAINING_KWH: float(resp_data.get("gearPowerLeft", 0)) if resp_data.get("gearPowerLeft") else None,
            WF_ATTR_LADDER_START_DATE: resp_data.get("startDate"),
            WF_ATTR_YEARLY_LADDER_TOTAL_KWH: float(resp_data.get("totalElectricityOfYear", 0)) if resp_data.get("totalElectricityOfYear") else None,
            # Additional fields
            "ladder_end_date": resp_data.get("endDate"),
            "current_ladder_name": current_gear_name.replace("【", "").replace("】", ""),
            "business_date": resp_data.get("businessDate"),
            "all_tiers": ladder_list,
        }

        _LOGGER.info(
            "Annual tier info API returned: tier=%s (%s), tariff=%s, remaining=%s kWh, yearly_total=%s kWh",
            ladder_info[WF_ATTR_LADDER],
            ladder_info["current_ladder_name"],
            ladder_info[WF_ATTR_LADDER_TARIFF],
            ladder_info[WF_ATTR_LADDER_REMAINING_KWH],
            ladder_info[WF_ATTR_YEARLY_LADDER_TOTAL_KWH],
        )

        return ladder_info

    # end high-level api wrappers
