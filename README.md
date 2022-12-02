# China Southern Power Grid Statistics

# 南方电网电费数据HA集成

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/cubicpill/china_southern_power_grid_stat)](https://github.com/CubicPill/china_southern_power_grid_stat/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## 支持功能

- ✅支持南方电网覆盖范围内的电费数据查询（广东、广西、云南、贵州、海南）
- ✅支持使用手机号和密码登陆，支持登录态失效之后自动重新登陆
- ✅支持多个南网账户（每个账户一个集成），支持单个账户下的多个缴费号
- ✅数据自动抓取和更新（默认间隔4小时，可配置）
- ✅全程GUI配置，无需编辑yaml进行配置（暂不支持yaml配置）

可接入如下数据：

- 当前余额和欠费
- 昨日用电量
- 最新一日用电量（每日用电量最新数据）
- 本年度总用电量和总电费（非实时，更新到上个月）
- 本年度内每月用电量和电费（非实时，更新到上个月）
- 上年度总用电量和总电费
- 上年度每月用电量和电费
- 当月累计用电量（非实时，有2天左右的延迟）
- 当月内每日用电量（非实时，有2天左右的延迟）
- 上月累计用电量
- 上月每日用电量

❌**不支持**阶梯电费设置、峰谷电价设置和电费计算（本插件只进行数据抓取和转换，不进行任何计算），
暂时也没有支持计划（南网暂时没有统一的API），如有需求，建议单独创建对应的电价实体。

## 使用方法

使用[HACS](https://hacs.xyz/)添加 Custom repositories
或[手动下载安装](https://github.com/CubicPill/china_southern_power_grid_stat/releases)

注意：本集成需求`Home Assistant`最低版本为`2022.8`。

### 配置界面

使用手机号和密码登陆

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/setup_login.png" alt="" style="width: 400px;">

配置界面

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/setup_add_account.png" alt="" style="width: 400px;">

添加缴费号

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/setup_select_account.png" alt="" style="width: 400px;">

传感器列表

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/sensors.png" alt="" style="width: 400px;">

传感器额外参数（每月用量、每日用量）

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/sensor_attr.png" alt="" style="width: 400px;">

参数设置

<img src="https://raw.githubusercontent.com/CubicPill/china_southern_power_grid_stat/master/img/setup_params.png" alt="" style="width: 400px;">

### 数据更新策略

由于上月数据和去年数据在生成之后一般不会发生变化，因此对于上月累计用电量、上月每日用电量、上年度累计用电量、上年度每月用电量，数据更新间隔将会与一般更新间隔有所不同。
具体更新策略如下：

对于上月数据，在每月前5天（1~5日）将会跟随一般更新间隔更新（默认为4小时），其余时间将会停止更新，但数据依然可用。

对于去年数据，在每年一月的前5天（1月1日~1月5日）将会每天更新（在每天第一次触发更新时更新），其余时间将会停止更新，但数据依然可用。

如果需要强制刷新数据，重载集成即可。

## 一些技术细节

### 登陆接口加密原理

登录接口的请求数据和返回数据都经过加密，其中请求数据经过两层加密：整个请求数据的`AES`加密和密码字段的`RSA`
公钥加密（密钥、公钥具体值见代码）。

加密前的请求数据结构如下：

```json5
{
  "areaCode": "xxx",
  "acctId": "xxx",
  "logonChan": "xxx",
  "credType": "xxx",
  "credentials": "xxx"  // <- encrypted with RSA
}
```

返回数据同样经过`AES`加密，密钥与请求数据相同。但返回值其中暂时不包含有用信息，验证状态码正常后可以直接忽略内容。

### Web端接口和App端接口

对于南网API相关信息的提取主要通过Web端的抓包和JS代码获取。
之后因为登录态有效期问题，对App端抓包进行比对后切换到App端API。
经过验证，Web端（网上营业厅）和App端（南网在线）的API接口基本相同，差别主要在于：

|              | Web                      | App        |
|--------------|--------------------------|------------|
| API路径        | ucs/ma/wt/               | ucs/ma/zt/ |
| 支持登陆方式       | 手机号+密码/验证码，南网在线/微信/支付宝扫码 | 手机号+密码/验证码 |
| token有效期     | 几小时                      | 较长         |
| Cookies      | token包含在cookies中         | 无cookies   |
| 敏感信息（姓名、地址等） | 部分信息用“*”隐去               | 有明文全文      |

另外在HTTP请求头上有细微的差别（如：UA），但实际上对于请求的返回结果没有影响。

### API 实现库

本项目代码中的[`csg_client/__init__.py`](https://github.com/CubicPill/china_southern_power_grid_stat/blob/master/custom_components/china_southern_power_grid_stat/csg_client/__init__.py)
是对南网在线API的实现，可以独立于此项目单独使用。

样例代码如下：

```python
from csg_client import CSGElectricityAccount, CSGClient, InvalidCredentials
import json
import os

# set this to False to use saved session
FRESH_LOGIN = True

# replace with your own credentials
USERNAME = "your_username"
PASSWORD = "your_password"

if not os.path.isfile("session.json"):
    if not FRESH_LOGIN:
        print("Error: no session file found, fresh login required")
        exit(1)

if FRESH_LOGIN:
    client = CSGClient()
    try:
        client.authenticate(USERNAME, PASSWORD)
        print('Login success!')
    except InvalidCredentials:
        print("Wrong username and password combination!")
        exit(1)
else:
    with open("session.json") as f:
        session_data = json.load(f)
    client = CSGClient.load(session_data)

client.initialize()

session = client.dump()
with open("session.json", "w") as f:
    json.dump(session, f)
print("Session dumped to session.json")

# calling utility functions

print("Verify login:", client.verify_login())

accounts = client.get_all_electricity_accounts()
print(f"{len(accounts)} electricity accounts linked to this account")

print(f"Account list:")
for i, account in enumerate(accounts):
    print(f"{i + 1}. {account.account_number}, {account.address}, {account.user_name}")
print('\n')

account: CSGElectricityAccount = accounts[0]
print(f"Selecting account: {account.account_number}, {account.address}, {account.user_name}")

bal, arr = client.get_balance_and_arrears(account)
print(f"Account: {account.account_number}, balance: {bal}, arrears: {arr}")

```

## 代码和功能设计参考

感谢[瀚思彼岸](https://bbs.hassbian.com/)论坛以下帖子作者的辛苦付出，排名不分先后

- [不折腾，超简单接入电费数据](https://bbs.hassbian.com/thread-18474-1-1.html)
- [北京电费查询加强版](https://bbs.hassbian.com/thread-13820-1-1.html)
- [电费插件（Node-Red流）-广东南方电网](https://bbs.hassbian.com/thread-17830-1-1.html)
- [【抄作业】电费插件(NR流)-南网](https://bbs.hassbian.com/thread-18122-1-1.html)

自定义集成教程参考：[Building a Home Assistant Custom Component Part 1: Project Structure and Basics](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)






