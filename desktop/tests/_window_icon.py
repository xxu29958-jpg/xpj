"""Read what Windows shows for a real top-level window: its taskbar icon and the screen.

Test-only and dependency-free (ctypes + zlib), so the Windows Edge gate can compare the
Manager window's actual icon with the packaged ICO and keep PNG evidence.
"""

from __future__ import annotations

import ctypes
import struct
import zlib
from ctypes import wintypes
from pathlib import Path

_WM_GETICON = 0x007F
_ICON_BIG = 1
_ICON_SMALL2 = 2
_GCLP_HICON = -14
_SMTO_ABORTIFHUNG = 0x0002
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_GW_OWNER = 4
_SRCCOPY = 0x00CC0020


class _IconInfo(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _Bitmap(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.SendMessageTimeoutW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    )
    user32.GetClassLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetClassLongPtrW.restype = ctypes.c_size_t
    user32.GetIconInfo.argtypes = (wintypes.HICON, ctypes.POINTER(_IconInfo))
    user32.LoadImageW.argtypes = (
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT,
    )
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.DestroyIcon.argtypes = (wintypes.HICON,)
    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    gdi32.GetObjectW.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p)
    gdi32.GetDIBits.argtypes = (
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    )
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = (
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD,
    )
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    return user32, gdi32, callback


def top_level_windows(process_id: int) -> list[int]:
    """Visible, unowned windows of one process: the ones that get a taskbar button."""
    user32, _gdi32, callback = _api()
    found: list[int] = []

    def observe(handle: int, _param: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(handle) and not user32.GetWindow(handle, _GW_OWNER):
            found.append(handle)
        return True

    user32.EnumWindows(callback(observe), 0)
    return found


def _bitmap_rgba(gdi32, user32, bitmap: int, width: int, height: int) -> bytes:
    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    buffer = ctypes.create_string_buffer(width * height * 4)
    screen = user32.GetDC(None)
    try:
        if gdi32.GetDIBits(screen, bitmap, 0, height, buffer, ctypes.byref(header), 0) != height:
            raise OSError("GetDIBits failed")
    finally:
        user32.ReleaseDC(None, screen)
    bgra = buffer.raw
    rgba = bytearray(len(bgra))
    rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = bgra[2::4], bgra[1::4], bgra[0::4], bgra[3::4]
    if not any(rgba[3::4]):
        # Icons without an alpha channel are fully opaque where drawn.
        rgba[3::4] = b"\xff" * (width * height)
    return bytes(rgba)


def icon_rgba(icon: int) -> tuple[int, int, bytes]:
    user32, gdi32, _callback = _api()
    info = _IconInfo()
    if not user32.GetIconInfo(icon, ctypes.byref(info)):
        raise OSError("GetIconInfo failed")
    try:
        bitmap = _Bitmap()
        gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(_Bitmap), ctypes.byref(bitmap))
        return bitmap.bmWidth, bitmap.bmHeight, _bitmap_rgba(gdi32, user32, info.hbmColor, bitmap.bmWidth, bitmap.bmHeight)
    finally:
        for handle in (info.hbmColor, info.hbmMask):
            if handle:
                gdi32.DeleteObject(handle)


def window_icon(window: int) -> tuple[int, int, bytes] | None:
    """The icon Windows uses for the window's taskbar button, as RGBA."""
    user32, _gdi32, _callback = _api()
    for kind in (_ICON_BIG, _ICON_SMALL2):
        result = ctypes.c_size_t()
        if user32.SendMessageTimeoutW(window, _WM_GETICON, kind, 0, _SMTO_ABORTIFHUNG, 1000, ctypes.byref(result)) and result.value:
            return icon_rgba(result.value)
    class_icon = user32.GetClassLongPtrW(window, _GCLP_HICON)
    return icon_rgba(class_icon) if class_icon else None


def file_icon(path: Path, size: int) -> tuple[int, int, bytes]:
    """The frame Windows itself picks from an .ico at one size."""
    user32, _gdi32, _callback = _api()
    icon = user32.LoadImageW(None, str(path), _IMAGE_ICON, size, size, _LR_LOADFROMFILE)
    if not icon:
        raise OSError(f"LoadImageW failed for {path}")
    try:
        return icon_rgba(icon)
    finally:
        user32.DestroyIcon(icon)


def screen_rgba() -> tuple[int, int, bytes]:
    user32, gdi32, _callback = _api()
    width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        gdi32.BitBlt(memory, 0, 0, width, height, screen, 0, 0, _SRCCOPY)
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)
    try:
        rgba = bytearray(_bitmap_rgba(gdi32, user32, bitmap, width, height))
    finally:
        gdi32.DeleteObject(bitmap)
    rgba[3::4] = b"\xff" * (width * height)
    return width, height, bytes(rgba)


def thumbnail(width: int, height: int, rgba: bytes, cells: int = 8) -> list[tuple[float, float, float]]:
    """Average each cell over a neutral grey backdrop; tolerant to resampling, strict on artwork."""
    sums = [[0.0, 0.0, 0.0, 0] for _ in range(cells * cells)]
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 4
            alpha = rgba[offset + 3] / 255
            cell = sums[(y * cells // height) * cells + x * cells // width]
            for channel in range(3):
                cell[channel] += rgba[offset + channel] * alpha + 128 * (1 - alpha)
            cell[3] += 1
    return [(r / n, g / n, b / n) for r, g, b, n in sums]


def difference(left: list[tuple[float, float, float]], right: list[tuple[float, float, float]]) -> float:
    return sum(abs(a - b) for one, two in zip(left, right, strict=True) for a, b in zip(one, two, strict=True)) / (
        3 * len(left)
    )


def png(width: int, height: int, rgba: bytes) -> bytes:
    rows = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
