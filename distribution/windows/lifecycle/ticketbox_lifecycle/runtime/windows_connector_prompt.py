"""Finite native confirmation and masked Token input inside the elevated helper."""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes

from ticketbox_lifecycle.connector_schema import ConnectorRequest
from ticketbox_lifecycle.errors import LifecycleError

INPUT_SECONDS = 120
_EDIT = 100


def _wide(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\0\0"


def _item(style: int, x: int, y: int, width: int, height: int, identifier: int, atom: int, text: str) -> bytes:
    return struct.pack("<LLhhhhH", style, 0, x, y, width, height, identifier) + struct.pack("<HH", 0xFFFF, atom) + _wide(text) + b"\0\0"


def _template(message: str, secret: bool) -> bytes:
    visible = 0x50000000
    items = [_item(visible, 12, 12, 282, 62, 101, 0x82, message)]
    if secret:
        items.append(_item(visible | 0x8100A0, 12, 78, 282, 18, _EDIT, 0x81, ""))
    items.extend((_item(visible | 0x10001, 158, 106, 64, 20, 1, 0x80, "确认"),
        _item(visible | 0x10000, 230, 106, 64, 20, 2, 0x80, "取消")))
    raw = struct.pack("<LLHhhhh", 0x80C80880, 0, len(items), 0, 0, 306, 138)
    raw += b"\0\0\0\0" + _wide("小票夹 · 受管公网接入")
    for item in items:
        raw += b"\0" * (-len(raw) % 4) + item
    return raw


def _api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.DialogBoxIndirectParamW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p, wintypes.HWND, callback, wintypes.LPARAM)
    user.DialogBoxIndirectParamW.restype = ctypes.c_ssize_t
    user.GetDlgItem.argtypes = (wintypes.HWND, ctypes.c_int)
    user.GetDlgItem.restype = wintypes.HWND
    user.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.GetDlgItemTextW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LPWSTR, ctypes.c_int)
    user.GetDlgItemTextW.restype = wintypes.UINT
    user.SetDlgItemTextW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LPCWSTR)
    user.SetDlgItemTextW.restype = wintypes.BOOL
    user.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
    user.SetTimer.restype = ctypes.c_size_t
    user.EndDialog.argtypes = (wintypes.HWND, ctypes.c_ssize_t)
    user.EndDialog.restype = wintypes.BOOL
    user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user.ShowWindow.restype = wintypes.BOOL
    return user, callback


def confirm_native(request: ConnectorRequest, *, needs_token: bool) -> str | None:
    action = {"configure": "设置公网连接", "reconnect": "重新连接", "remove": "移除本机连接",
        "set_enabled": "开启公网" if request.desired_enabled else "暂停公网"}[request.action]
    intent = "完成后开启公网。" if request.desired_enabled else "完成后保持公网关闭。"
    message = f"{action}。{intent}\n本地账本继续可用。\n"
    message += ("请粘贴在 Cloudflare 创建的此电脑专用 Tunnel Token。凭据保存在本机受保护位置，不会在管理界面显示。"
        if needs_token else "本机移除不会撤销远端 Token；外部共享连接需在云端另行处理。")
    message += "\n此窗口在 2 分钟后取消。"
    user, callback_type = _api()
    captured: list[str] = []

    def dialog(hwnd, event, word, _parameter):
        if event == 0x110:
            if needs_token:
                user.SendMessageW(user.GetDlgItem(hwnd, _EDIT), 0xC5, 16384, 0)
            if not user.SetTimer(hwnd, 1, INPUT_SECONDS * 1000, None):
                user.EndDialog(hwnd, 2)
                return 1
            # Consume the helper's SW_HIDE startup setting before DialogBox
            # shows the input window; its console must remain hidden.
            user.ShowWindow(hwnd, 1)
            return 1
        if event in {0x10, 0x113}:
            user.EndDialog(hwnd, 2)
            return 1
        if event == 0x111 and word & 0xFFFF in {1, 2}:
            accepted = word & 0xFFFF == 1
            if accepted and needs_token:
                buffer = ctypes.create_unicode_buffer(16385)
                user.GetDlgItemTextW(hwnd, _EDIT, buffer, len(buffer))
                captured.append(buffer.value)
                ctypes.memset(ctypes.addressof(buffer), 0, ctypes.sizeof(buffer))
                user.SetDlgItemTextW(hwnd, _EDIT, "")
            user.EndDialog(hwnd, 1 if accepted else 2)
            return 1
        return 0

    template = ctypes.create_string_buffer(_template(message, needs_token))
    callback = callback_type(dialog)
    result = user.DialogBoxIndirectParamW(None, template, None, callback, 0)
    if result != 1:
        raise LifecycleError("connector_input_cancelled", "native confirmation cancelled or timed out; no new host changes")
    return captured.pop() if needs_token else None
