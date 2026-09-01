"""Typed confirmed stream (refund/chargeback/reversal) Web row contracts."""

from __future__ import annotations

from html.parser import HTMLParser

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem, manual_confirmed


class _ConfirmedStreamProbe(HTMLParser):
    """Per-row structural capture for the typed confirmed stream.

    typed stream 行合同 (Refund/Chargeback/Reversal 纵向片): expense root 行保留
    选择槽 (input.row-check) 与金额槽; refund/chargeback 是带入账符号金额的金额行
    (.lrow-amt--inflow); reversal 是无金额槽事件行; offset 行一律没有批量
    checkbox, 整行链接到 numeric root 的事实详情。
    """

    _VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []
        self.day_counts: list[str] = []
        self.day_sums: list[str] = []
        self._row: dict | None = None
        self._row_depth = 0
        self._capture: list[str] | None = None
        self._capture_kind = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if self._row is not None:
            if tag == "input" and "row-check" in classes:
                self._row["checkbox"] = True
            if tag == "a" and "timeline-row-detail" in classes:
                self._row["href"] = attr.get("href") or ""
            if tag == "div" and "lrow-amt" in classes:
                self._row["amt"] = True
                self._row["amt_inflow"] = "lrow-amt--inflow" in classes
            if tag == "span" and "lrow-lineage" in classes:
                self._capture = []
                self._capture_kind = "chip"
            if tag not in self._VOID:
                self._row_depth += 1
            return
        if tag == "div" and "timeline-row" in classes and "lrow" in classes:
            self._row = {
                "checkbox": False,
                "href": "",
                "amt": False,
                "amt_inflow": False,
                "chips": [],
                "text": [],
            }
            self._row_depth = 1
            return
        if tag == "span" and "lday-s" in classes:
            self._capture = []
            self._capture_kind = "day_sum"
        elif tag == "span" and "lday-n" in classes:
            self._capture = []
            self._capture_kind = "day_count"

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture.append(data)
        if self._row is not None and data.strip():
            self._row["text"].append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture is not None:
            value = "".join(self._capture).strip()
            kind = self._capture_kind
            self._capture = None
            self._capture_kind = ""
            if kind == "chip" and self._row is not None:
                self._row["chips"].append(value)
            elif kind == "day_sum":
                self.day_sums.append(value)
            elif kind == "day_count":
                self.day_counts.append(value)
        if self._row is not None and tag not in self._VOID:
            self._row_depth -= 1
            if self._row_depth == 0:
                # 金额的小数位是独立 span (.d), 节点间不补空格, 让
                # "+¥30" + ".00" 断言为 "+¥30.00"。
                self._row["text"] = "".join(self._row["text"])
                self.rows.append(self._row)
                self._row = None


def _create_offset(
    web_client: TestClient,
    identity,
    expense: dict,
    *,
    kind: str,
    accounting_date: str,
    amount_cents: int | None = None,
) -> dict:
    payload: dict[str, object] = {
        "kind": kind,
        "accounting_date": accounting_date,
        "reason": f"登记{kind}",
        "expected_row_version": expense["row_version"],
    }
    if amount_cents is not None:
        payload["original_amount_minor"] = amount_cents
    response = web_client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_typed_stream(web_client: TestClient, identity) -> dict:
    """固定样本: 夏日酒店 ¥120 (05-04, 退款 ¥30 + 拒付 ¥10 在 05-05 → 部分退回),
    重复记账 ¥80 (05-04, 冲销事件在 05-06 → 已冲销)。"""
    root = manual_confirmed(web_client, identity, merchant="夏日酒店", amount_cents=12000)
    reversed_root = manual_confirmed(web_client, identity, merchant="重复记账", amount_cents=8000)
    refund = _create_offset(
        web_client, identity, root,
        kind="refund", accounting_date="2026-05-05", amount_cents=3000,
    )
    _create_offset(
        web_client, identity, refund["root"],
        kind="chargeback", accounting_date="2026-05-05", amount_cents=1000,
    )
    _create_offset(
        web_client, identity, reversed_root,
        kind="reversal", accounting_date="2026-05-06",
    )
    return {"root": root, "reversed_root": reversed_root}


def _probe_confirmed(web_client: TestClient) -> _ConfirmedStreamProbe:
    resp = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05")
    assert resp.status_code == 200, resp.text
    probe = _ConfirmedStreamProbe()
    probe.feed(resp.text)
    probe.close()
    return probe


def _identified_rows(probe: _ConfirmedStreamProbe) -> dict:
    roots = [row for row in probe.rows if row["checkbox"]]
    offsets = [row for row in probe.rows if not row["checkbox"]]
    return {
        "refund": next(row for row in offsets if "退款" in row["text"]),
        "chargeback": next(row for row in offsets if "拒付" in row["text"]),
        "reversal": next(row for row in offsets if "冲销" in row["text"]),
        "root": next(row for row in roots if "夏日酒店" in row["text"]),
        "reversed_root": next(row for row in roots if "重复记账" in row["text"]),
    }


def test_web_confirmed_stream_renders_typed_rows(web_client: TestClient, *, identity) -> None:
    """四种行形态: refund/chargeback 是 + 号入账金额行 (不伪装成消费扣款),
    reversal 是无金额槽事件行 (金额只进引用文案), root 行保留 gross 金额槽
    与 lineage chip; offset 行整行链接 numeric root 事实详情。"""
    ids = _seed_typed_stream(web_client, identity)
    rows = _identified_rows(_probe_confirmed(web_client))
    for row, root_id in (
        (rows["refund"], ids["root"]["id"]),
        (rows["chargeback"], ids["root"]["id"]),
        (rows["reversal"], ids["reversed_root"]["id"]),
    ):
        assert row["href"].startswith(f"/web/expenses/{root_id}/edit?")
    assert rows["refund"]["amt"] and rows["refund"]["amt_inflow"]
    assert "+¥30.00" in rows["refund"]["text"]
    assert rows["chargeback"]["amt"] and rows["chargeback"]["amt_inflow"]
    assert "+¥10.00" in rows["chargeback"]["text"]
    assert not rows["reversal"]["amt"]
    assert "¥80.00" in rows["reversal"]["text"]
    assert rows["root"]["amt"] and "¥120.00" in rows["root"]["text"]
    assert rows["reversed_root"]["amt"] and "¥80.00" in rows["reversed_root"]["text"]
    assert rows["root"]["chips"] == ["部分退回"]
    assert rows["reversed_root"]["chips"] == ["已冲销"]


def test_web_confirmed_stream_sums_and_selection(web_client: TestClient, *, identity) -> None:
    """日合计只加 server-owned stream_amount_cents (reversal 与 reversed root
    计 0, refund/chargeback 负向), 批量选择槽只长在 expense root 行。"""
    _seed_typed_stream(web_client, identity)
    probe = _probe_confirmed(web_client)
    assert len(probe.rows) == 5
    assert len([row for row in probe.rows if row["checkbox"]]) == 2
    assert len([row for row in probe.rows if not row["checkbox"]]) == 3
    # stream_date desc: 05-06 冲销事件 = ¥0.00; 05-05 退款/拒付 = -¥40.00;
    # 05-04 两个 root (reversed 计 0) = ¥120.00, 不是 gross 之和 ¥200.00。
    assert probe.day_counts == ["1 笔", "2 笔", "2 笔"]
    assert probe.day_sums == ["¥0.00", "-¥40.00", "¥120.00"]
