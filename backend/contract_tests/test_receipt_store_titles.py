"""Store and ride headings retain their own printed text and image blocks."""
import pytest

from app.services.receipt_parse_service import parse_receipt_text


@pytest.mark.parametrize("raw,expected", [
    ("预计20:12送达\n闪购青禾咖啡（城西店）\n商家自配送\n实付20.00元", "青禾咖啡（城西店）"),
    ("商品费用\n槐树面馆>\n进商家粉丝群\n实付20.00元", "槐树面馆"),
    ("订单支付\n江南出行-经济型|陈师傅·测试车牌\n支付金额20.00元", "江南出行"),
])
def test_store_title_value_and_original_boxes_survive(raw, expected):
    blocks = [{"text": line, "box": [[0, i * 20], [400, i * 20], [400, i * 20 + 18], [0, i * 20 + 18]]}
              for i, line in enumerate(raw.splitlines())]
    parsed = parse_receipt_text(raw, "Asia/Shanghai", currency_code="CNY", minor_unit_exponent=2, evidence_blocks=blocks)
    assert parsed.merchant == expected
    candidate = next(item for item in parsed.candidates if item.field == "merchant" and item.value == expected)
    assert candidate.role == "merchant" and candidate.source == "store_context"
    assert any(raw[start:end] == expected for start, end in candidate.raw_spans)
    assert candidate.block_indices and any(expected in blocks[index]["text"] for index in candidate.block_indices)


@pytest.mark.parametrize("raw", [
    "支付成功\n商户：本次便利店\n支付奖励\n闪购领红包\n次日送达",
    "商户：本次便利店\n闪购优惠\n实付20.00元",
    "商户：本次便利店\n评论里说江南出行-经济型很舒服\n实付20.00元",
])
def test_advertising_or_unanchored_rides_do_not_create_store_titles(raw):
    parsed = parse_receipt_text(raw, currency_code="CNY", minor_unit_exponent=2)
    assert not any(item.source == "store_context" for item in parsed.candidates)
    assert parsed.merchant == "本次便利店"


def test_list_cap_does_not_turn_hidden_conflict_into_a_default():
    parsed = parse_receipt_text("\n".join(["商户：甲方商店"] * 9 + ["商户：乙方商店", "实付20.00元"]),
        currency_code="CNY", minor_unit_exponent=2)
    assert parsed.merchant is None
    assert next(item for item in parsed.decisions if item.field == "merchant").status == "ambiguous"
    assert len([item for item in parsed.candidates if item.field == "merchant"]) == 8
