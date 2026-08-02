"""Checked money formatting for the browser reports surface."""

from app.money_contract import projection_sum_to_int, projection_values_average_to_int
from app.routes.web_common import _amount_yuan


def money(value: object, label: str) -> int:
    return projection_sum_to_int(value, label=f"web_reports.{label}")


def percent(value: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    rounded = (value * 100 + maximum // 2) // maximum
    return max(2, min(100, rounded))


def _category_comparison_max(rows: list[dict]) -> int:
    return max(
        [
            max(
                money(row["amount_cents"], "category_current"),
                money(row["previous_amount_cents"], "category_previous"),
                money(row["year_over_year_amount_cents"], "category_yoy"),
            )
            for row in rows
        ]
        or [0]
    )


def category_comparison_view(
    rows: list[dict],
    *,
    currency_code: str,
) -> list[dict]:
    maximum = _category_comparison_max(rows)
    return [
        {
            "category": row["category"],
            "amount_yuan": _amount_yuan(money(row["amount_cents"], "category_current"), currency_code),
            "previous_amount_yuan": _amount_yuan(
                money(row["previous_amount_cents"], "category_previous"),
                currency_code,
            ),
            "delta_amount_yuan": _amount_yuan(money(row["delta_amount_cents"], "category_delta"), currency_code),
            "year_over_year_amount_yuan": _amount_yuan(
                money(row["year_over_year_amount_cents"], "category_yoy"),
                currency_code,
            ),
            "year_over_year_delta_amount_yuan": _amount_yuan(
                money(row["year_over_year_delta_amount_cents"], "category_yoy_delta"),
                currency_code,
            ),
            "amount_cents": money(row["amount_cents"], "category_current"),
            "previous_amount_cents": money(row["previous_amount_cents"], "category_previous"),
            "delta_amount_cents": money(row["delta_amount_cents"], "category_delta"),
            "year_over_year_amount_cents": money(row["year_over_year_amount_cents"], "category_yoy"),
            "year_over_year_delta_amount_cents": money(row["year_over_year_delta_amount_cents"], "category_yoy_delta"),
            "count": int(row["count"]),
            "previous_count": int(row["previous_count"]),
            "delta_count": int(row["delta_count"]),
            "year_over_year_count": int(row["year_over_year_count"]),
            "year_over_year_delta_count": int(row["year_over_year_delta_count"]),
            "current_percent": percent(money(row["amount_cents"], "category_current"), maximum),
            "previous_percent": percent(money(row["previous_amount_cents"], "category_previous"), maximum),
            "year_over_year_percent": percent(money(row["year_over_year_amount_cents"], "category_yoy"), maximum),
        }
        for row in rows
    ]


def six_month_average_amount_yuan(
    rows: list[dict],
    *,
    currency_code: str,
) -> str:
    average = projection_values_average_to_int(
        (row["amount_cents"] for row in rows),
        label="web_reports.six_month_average",
    )
    return _amount_yuan(average, currency_code)


__all__ = [
    "category_comparison_view",
    "money",
    "percent",
    "six_month_average_amount_yuan",
]
