"""外观本地偏好合同：bootstrap 与 theme.js 共享同一 TicketboxAppearance owner。

``appearance-bootstrap.js`` 是 strict-CSP 下唯一合法的 anti-FOUC 形态（无 defer
外部脚本），也是 ``ui-texture`` / ``ui-accent`` 的 storage key、合法值与默认值的
唯一声明者；运行时 ``theme.js`` 只经同一合同读/写/应用。本测试用 Node vm 执行
真实脚本（假 document/localStorage），字面钉住三件事：显式 flat/plum 被还原、
非法存储值 fail-closed 不写属性、theme.js 的 current/apply 与合同读写同一份存储。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_NODE_CONTRACT = r"""
const fs = require("fs");
const vm = require("vm");

function makeContext(preset, brandAttrs) {{
  const store = Object.assign({{}}, preset);
  const attrs = {{}};
  const brand = {{
    attrs: Object.assign({{}}, brandAttrs),
    getAttribute: (name) => brand.attrs[name] || null,
    setAttribute: (name, value) => {{ brand.attrs[name] = String(value); }},
  }};
  const localStorage = {{
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => {{ store[key] = String(value); }},
  }};
  const document = {{
    documentElement: {{
      setAttribute: (name, value) => {{ attrs[name] = String(value); }},
      getAttribute: (name) => (name in attrs ? attrs[name] : null),
    }},
    querySelectorAll: (selector) => selector.startsWith(".brand-mark-img") ? [brand] : [],
  }};
  const window = {{ localStorage }};
  const context = {{ window, document, localStorage }};
  vm.runInNewContext(fs.readFileSync(__BOOTSTRAP__, "utf8"), context);
  return {{ store, attrs, brand, context }};
}}

const result = {{}};

// 1) 外部 bootstrap: 显式 flat + plum 还原到 <html data-*>。
const restored = makeContext({{ "ui-texture": "flat", "ui-accent": "plum" }});
result.restored = {{
  texture: restored.attrs["data-texture"] || null,
  accent: restored.attrs["data-accent"] || null,
}};

// 2) 非法存储值 fail-closed: 不写属性, 合同读取回落默认。
const invalid = makeContext({{ "ui-texture": "neon", "ui-accent": "blue" }});
result.failClosed = {{
  texture: invalid.attrs["data-texture"] || null,
  accent: invalid.attrs["data-accent"] || null,
  readTexture: invalid.context.window.TicketboxAppearance.read("texture"),
  readAccent: invalid.context.window.TicketboxAppearance.read("accent"),
}};

// 3) theme.js 经同一合同读写: current 读到 bootstrap 同一份存储, apply 落同一
//    key, 非法写入持久化回落值, 合同读得到 theme 写的结果。
const shared = makeContext({{ "ui-texture": "flat", "ui-accent": "plum" }});
vm.runInNewContext(fs.readFileSync(__THEME__, "utf8"), shared.context);
const app = shared.context.window.TicketboxWeb;
const prefs = shared.context.window.TicketboxAppearance;
const before = app.currentTextureMode();
app.applyTextureMode("fiber");
app.applyAccentMode("ochre");
app.applyAccentMode("blue");
result.shared = {{
  before,
  storedTexture: shared.store["ui-texture"] || null,
  appliedTexture: shared.attrs["data-texture"] || null,
  storedAccent: shared.store["ui-accent"] || null,
  appliedAccent: shared.attrs["data-accent"] || null,
  contractReadTexture: prefs.read("texture"),
}};

// 4) 主题切换只采用受信任的产品资产路径；DOM data-* 被篡改也不能成为 src。
const branded = makeContext({{}}, {{
  src: "/static/web/product/brand/brand-mark.png",
  "data-src-paper": "javascript:paper",
  "data-src-midnight": "javascript:midnight",
}});
vm.runInNewContext(fs.readFileSync(__THEME__, "utf8"), branded.context);
branded.context.window.TicketboxWeb.applyThemeMode("midnight");
result.brand = {{ src: branded.brand.attrs.src }};
process.stdout.write(JSON.stringify(result));
"""


def _contract_script(bootstrap: Path, theme: Path) -> str:
    return (
        _NODE_CONTRACT.replace("__BOOTSTRAP__", json.dumps(str(bootstrap)))
        .replace("__THEME__", json.dumps(str(theme)))
        .replace("{{", "{")
        .replace("}}", "}")
    )


def test_appearance_bootstrap_and_theme_share_one_preference_contract() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for the appearance preference contract")
    static_web = Path(__file__).resolve().parents[1] / "app" / "static" / "web"
    script = _contract_script(
        static_web / "appearance-bootstrap.js",
        static_web / "desktop" / "theme.js",
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "restored": {"texture": "flat", "accent": "plum"},
        "failClosed": {
            "texture": None,
            "accent": None,
            "readTexture": "fiber",
            "readAccent": "evergreen",
        },
        "shared": {
            "before": "flat",
            "storedTexture": "fiber",
            "appliedTexture": "fiber",
            "storedAccent": "evergreen",
            "appliedAccent": "evergreen",
            "contractReadTexture": "fiber",
        },
        "brand": {
            "src": "/static/web/product/brand/brand-mark-midnight.png",
        },
    }
