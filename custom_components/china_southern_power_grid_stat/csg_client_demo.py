# pylint: disable-all
import datetime
import json
import os
import sys
import time

from csg_client import (
    LOGIN_TYPE_TO_QR_CODE_TYPE,
    CSGClient,
    CSGElectricityAccount,
    LoginType,
)

QR_SCAN_TIMEOUT = 300

# set this to False to use saved session
FRESH_LOGIN = False

# replace with your own credentials
USERNAME = "" or os.getenv("CSG_USERNAME")
PASSWORD = "" or os.getenv("CSG_PASSWORD")

if __name__ == "__main__":
    if not os.path.isfile("session.json"):
        if not FRESH_LOGIN:
            print("错误：未找到保存的登录态，需要将FRESH_LOGIN设为True")
            sys.exit(1)

    if FRESH_LOGIN:
        print(
            "请选择登录方式：\n1. 手机号+短信验证码\n2. 手机号+短信验证码+密码\n3. 扫码登录"
        )
        login_type = None
        selection = input().strip()
        if selection == "1":
            login_type = LoginType.LOGIN_TYPE_SMS
        elif selection == "2":
            login_type = LoginType.LOGIN_TYPE_PWD_AND_SMS
        elif selection == "3":
            print("请选择扫码登录方式：\n1. 南网APP\n2. 微信\n3. 支付宝")
            qr_selection = input()
            if qr_selection == "1":
                login_type = LoginType.LOGIN_TYPE_CSG_QR
            elif qr_selection == "2":
                login_type = LoginType.LOGIN_TYPE_WX_QR
            elif qr_selection == "3":
                login_type = LoginType.LOGIN_TYPE_ALI_QR
        if login_type is None:
            print("无效选择，请重试")
            sys.exit(1)
        client = CSGClient()

        if login_type in [LoginType.LOGIN_TYPE_SMS, LoginType.LOGIN_TYPE_PWD_AND_SMS]:
            if not USERNAME or (
                login_type == LoginType.LOGIN_TYPE_PWD_AND_SMS and not PASSWORD
            ):
                print("错误：请填写用户名和密码，或在环境变量中设置")
                sys.exit(1)
            client.api_send_login_sms(USERNAME)
            print("验证码已发送，请输入验证码：")
            code = input().strip()
            if login_type == LoginType.LOGIN_TYPE_SMS:
                auth_token = client.api_login_with_sms_code(USERNAME, code)
            else:
                auth_token = client.api_login_with_password_and_sms_code(
                    USERNAME, PASSWORD, code
                )

        elif login_type in [
            LoginType.LOGIN_TYPE_CSG_QR,
            LoginType.LOGIN_TYPE_WX_QR,
            LoginType.LOGIN_TYPE_ALI_QR,
        ]:
            login_id, qr_url = client.api_create_login_qr_code(
                channel=LOGIN_TYPE_TO_QR_CODE_TYPE[login_type]
            )
            print(f"请打开链接扫码登录：{qr_url}")
            start_time = time.time()
            while time.time() - start_time < QR_SCAN_TIMEOUT:
                ok, auth_token = client.api_get_qr_login_status(login_id)
                if ok:
                    print("扫码成功！")
                    break
                time.sleep(1)
            else:
                print("扫码超时，请重试")
                sys.exit(1)
        else:
            raise NotImplementedError(f"未知的登录类型: {login_type}")

        print("登录成功！")
        client.set_authentication_params(auth_token)

    else:
        with open("session.json", encoding="utf-8") as f:
            session_data = json.load(f)
        client = CSGClient.load(session_data)

    client.initialize()

    session = client.dump()
    with open("session.json", "w", encoding="utf-8") as f:
        json.dump(session, f)
    print("登录态已保存到session.json")

    # calling utility functions

    print("验证登录状态:", client.verify_login())

    print("用户信息:", client.api_get_user_info())

    accounts = client.get_all_electricity_accounts()
    print(f"共{len(accounts)}个绑定的电费账户")

    print("电费账户列表:")
    for i, account in enumerate(accounts):
        print(
            f"{i + 1}. {account.account_number}, {account.address}, {account.user_name}"
        )
    print("\n")

    account: CSGElectricityAccount = accounts[0]
    print(
        f"选取第一个账户: {account.account_number}, {account.address}, {account.user_name}"
    )

    input("按回车获取余额和欠费")
    bal, arr = client.get_balance_and_arrears(account)
    print(f"账户 {account.account_number}, 余额: {bal}, 欠费: {arr}")
    input("按回车获取当前月份每日用电数据")
    (
        month_total_cost,
        month_total_kwh,
        ladder,
        by_day,
    ) = client.get_month_daily_cost_detail(
        account, (datetime.datetime.now().year, datetime.datetime.now().month)
    )
    print(
        f"账户 {account.account_number}, 当月总电费: {month_total_cost}, 当月总电量: {month_total_kwh}kWh, 当前阶梯: {ladder}, 每日数据: {by_day}"
    )
