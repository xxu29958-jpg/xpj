from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

OWNER_EXPENSES: list[dict[str, Any]] = [
    {
        "amount_cents": 29800,
        "merchant": "真香年费",
        "category": "AI订阅",
        "expense_time": "2026-05-03T10:00:00Z",
        "value_score": 5,
        "regret_score": 1,
    },
    {
        "amount_cents": 1200,
        "merchant": "真香小吃",
        "category": "餐饮",
        "expense_time": "2026-05-04T10:00:00Z",
        "value_score": 5,
        "regret_score": 2,
    },
    {
        "amount_cents": 8800,
        "merchant": "后悔桌搭",
        "category": "数码",
        "expense_time": "2026-05-05T10:00:00Z",
        "value_score": 1,
        "regret_score": 5,
    },
    {
        "amount_cents": 3900,
        "merchant": "后悔游戏",
        "category": "娱乐",
        "expense_time": "2026-05-06T10:00:00Z",
        "value_score": 2,
        "regret_score": 5,
    },
    {
        "amount_cents": 999,
        "merchant": "未评分账单",
        "category": "生活",
        "expense_time": "2026-05-07T10:00:00Z",
    },
    {
        "amount_cents": 19900,
        "merchant": "上月真香",
        "category": "生活",
        "expense_time": "2026-04-30T10:00:00Z",
        "value_score": 5,
        "regret_score": 5,
    },
]

GRAY_EXPENSE: dict[str, Any] = {
    "amount_cents": 99999,
    "merchant": "灰度账本真香",
    "category": "数码",
    "expense_time": "2026-05-08T10:00:00Z",
    "value_score": 5,
    "regret_score": 5,
}


def test_lifestyle_stats_returns_value_and_regret_rankings(
    client: TestClient, *, identity
) -> None:
    for payload in OWNER_EXPENSES:
        _post_manual_expense(client, identity.app_headers, payload)
    _post_manual_expense(client, identity.gray_app_headers, GRAY_EXPENSE)

    payload = _get_lifestyle_stats(client, identity.app_headers)
    assert [item["merchant"] for item in payload["best_value_expenses"]] == [
        "真香年费",
        "真香小吃",
        "后悔游戏",
        "后悔桌搭",
    ]
    assert [item["value_score"] for item in payload["best_value_expenses"]] == [
        5,
        5,
        2,
        1,
    ]
    assert [item["merchant"] for item in payload["most_regretted_expenses"]] == [
        "后悔桌搭",
        "后悔游戏",
        "真香小吃",
        "真香年费",
    ]
    assert [item["regret_score"] for item in payload["most_regretted_expenses"]] == [
        5,
        5,
        2,
        1,
    ]

    gray_payload = _get_lifestyle_stats(client, identity.gray_app_headers)
    assert [item["merchant"] for item in gray_payload["best_value_expenses"]] == [
        "灰度账本真香"
    ]
    assert [item["merchant"] for item in gray_payload["most_regretted_expenses"]] == [
        "灰度账本真香"
    ]


def _post_manual_expense(
    client: TestClient, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    response = client.post("/api/expenses/manual", headers=headers, json=payload)
    assert response.status_code == 200, response.json()


def _get_lifestyle_stats(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(
        "/api/stats/lifestyle?month=2026-05&timezone=UTC",
        headers=headers,
    )
    assert response.status_code == 200, response.json()
    return response.json()
