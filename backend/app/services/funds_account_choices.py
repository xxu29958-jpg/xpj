"""Account shortcuts only: a provider name never supplies financial facts or rates."""

ACCOUNT_CHOICES = (
    {"key": "cash", "name": "现金", "kind": "cash", "institution": ""},
    {"key": "debit_card", "name": "储蓄卡", "kind": "bank", "institution": ""},
    {"key": "credit_card", "name": "信用卡", "kind": "credit", "institution": ""},
    {"key": "alipay", "name": "支付宝余额", "kind": "wallet", "institution": "支付宝"},
    {"key": "wechat", "name": "微信零钱", "kind": "wallet", "institution": "微信支付"},
    {"key": "prepaid", "name": "储值账户", "kind": "wallet", "institution": ""},
    {"key": "ecny", "name": "数字人民币钱包", "kind": "wallet", "institution": ""},
    {"key": "huabei", "name": "花呗", "kind": "credit", "institution": "支付宝"},
    {"key": "baitiao", "name": "京东白条", "kind": "credit", "institution": "京东金融"},
    {"key": "meituan", "name": "美团月付", "kind": "credit", "institution": "美团"},
    {"key": "douyin", "name": "抖音月付", "kind": "credit", "institution": "抖音"},
    {"key": "fenfu", "name": "微信分付", "kind": "credit", "institution": "微信支付"},
    {"key": "other_credit", "name": "其他信用账户", "kind": "credit", "institution": ""},
)
