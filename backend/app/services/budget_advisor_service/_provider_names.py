"""Single source for budget-advisor provider names."""

from __future__ import annotations

EMPTY_PROVIDER_NAMES = frozenset({"", "empty"})
MOCK_PROVIDER_NAMES = frozenset({"mock"})
EMPTY_PROVIDER_NAME = "empty"
MOCK_PROVIDER_NAME = "mock"
OPENAI_COMPAT_PROVIDER_NAME = "openai_compat"
OPENAI_COMPAT_PROVIDER_NAMES = frozenset(
    {
        "openai_compat",
        "openai-compat",
        "openai_compatible",
        "openai-compatible",
        "openai",
        "deepseek",
        "deepseek-chat",
        "siliconflow",
        "silicon-flow",
        "silicon_flow",
        "together",
        "groq",
    }
)
LIVE_PROVIDER_NAMES = OPENAI_COMPAT_PROVIDER_NAMES
KNOWN_PROVIDER_NAMES = EMPTY_PROVIDER_NAMES | MOCK_PROVIDER_NAMES | OPENAI_COMPAT_PROVIDER_NAMES


def normalize_provider_name(value: str | None) -> str:
    return (value or "empty").strip().lower()


def clean_provider_name(value: str | None) -> str:
    return normalize_provider_name(value)


def canonical_provider_name(value: str | None) -> str:
    name = clean_provider_name(value)
    if name in EMPTY_PROVIDER_NAMES:
        return EMPTY_PROVIDER_NAME
    if name in OPENAI_COMPAT_PROVIDER_NAMES:
        return OPENAI_COMPAT_PROVIDER_NAME
    return name


def is_known_provider(value: str | None) -> bool:
    return clean_provider_name(value) in KNOWN_PROVIDER_NAMES
