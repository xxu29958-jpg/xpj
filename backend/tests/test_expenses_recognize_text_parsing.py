from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from api_contract_helpers import (
    upload_png,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import DuplicateIgnore, Expense
from app.services.duplicate_service import _remember_duplicate_ignore
from app.services.expense_service import confirm_expense, reject_expense, retry_expense_ocr
from app.services.ocr_service import MockOcrProvider, OcrResult, apply_ocr_result, retry_ocr
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT


def test_recognize_text_extracts_receipt_fields(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "中国建设银行",
            "交易提醒",
            "交易时间：2026年5月4日 16:23:25",
            "交易类型：支出（尾号 0436 账户）",
            "交易金额：18.51（人民币）",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_text"] == raw_text
    assert payload["amount_cents"] == 1851
    assert payload["merchant"] == "中国建设银行"
    assert payload["category"] == "其他"
    assert payload["expense_time"] == "2026-05-04T08:23:25Z"
    assert payload["confidence"] >= 0.8


def test_recognize_text_prefers_transaction_time_over_other_times(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "商品详情：超级咸蛋黄狮子头+泡椒脆笋鸭丝单人套餐",
            "中国建设银行",
            "交易提醒",
            "交易时间：",
            "2026年5月4日16:23:25",
            "交易金额：",
            "18.51(人民币)",
            "京东快递",
            "来电时间：",
            "2026-05-04 06:49:50",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1851
    assert payload["merchant"] == "中国建设银行"
    assert payload["expense_time"] == "2026-05-04T08:23:25Z"


def test_recognize_text_prefers_alipay_primary_amount_and_title_merchant(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-17.89",
            "交易成功",
            "订单金额",
            "18.00",
            "碰一下立减",
            "-0.11",
            "支付时间",
            "2026-05-0521:38:13",
            "付款方式",
            "花呗",
            "商品说明",
            "重庆巴南区珠江城店",
            "收单机构",
            "招商银行股份有限公司",
            "清算机构",
            "中国银联股份有限公司",
            "收款方全称",
            "巴南区财进宁食品经营部（个体工商户）",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1789
    assert payload["merchant"] == "好想来零食乐园"
    assert payload["category"] == "餐饮"
    assert payload["expense_time"] == "2026-05-05T13:38:13Z"


def test_recognize_text_ignores_alipay_success_page_ads_for_merchant(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "支付成功",
            "￥7.50",
            "获得森林能量",
            "20g",
            "罗森便利店",
            "￥ 7.50",
            "交易方式",
            "花呗",
            "抢到下笔立减0.18元红包",
            "去查看",
            "立即领取",
            "高德",
            "写真实评价，领10元打车红包",
            "评价本店>",
            "扫街榜",
            "券后￥0.01",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 750
    assert payload["merchant"] == "罗森便利店"
    assert payload["category"] == "餐饮"


def test_recognize_text_alipay_success_body_ignores_navigation_title(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "07:55",
            "l 4G 13",
            "支",
            "回首页",
            "支付成功",
            "￥ 21.82",
            "获得森林能量",
            "20g",
            "乐尔乐特价批发超市",
            "￥ 22.00",
            "碰一下立减",
            "-￥ 0.18",
            "交易方式",
            "花呗",
            "本店特价限时抢购",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 2182
    assert payload["merchant"] == "乐尔乐特价批发超市"
    assert payload["category"] == "购物"


def test_recognize_text_wechat_payment_line_merchant_candidate(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "微信支付",
            "Q",
            "Jack",
            "使用建设银行储蓄卡支付",
            "¥5.00",
            "交易状态",
            "支付成功，对方已收款",
            "查看账单详情",
            "商家名片",
            "星期二07:19",
            "松针小笼包",
            "使用建设银行储蓄卡(0436)支付",
            "¥10.00",
            "账单详情>",
            "我的账单",
            "支付服务",
            "摇优惠",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 500
    assert payload["merchant"] == "Jack"
    assert payload["category"] == "其他"


def test_recognize_text_ignores_status_bar_numbers_and_destination_text(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "花溪工业园区",
            "高德地图",
            "21:15",
            ".·5G",
            "91",
            "好想来零食乐园（重庆巴南区珠江城店）",
            "订单支付",
            "鲸志出行-经济型|余师傅·渝AA77599",
            "物品遗失打电话",
            "11.73元",
            "费用说明）",
            "起步价",
            "11.73元",
            "高德打车",
            "高德打车聚合平台由北京易行出行旅游有限公司运营并提供服务",
            "已开启免密支付，将于05月06日21:17自动扣款",
            "11.73元",
            "共计",
            "确认支付",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1173
    assert payload["merchant"] == "高德"
    assert payload["category"] == "交通"
