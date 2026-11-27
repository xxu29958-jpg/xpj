"""Managed Windows Start Menu shortcut updates via native COM."""

from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.adapters.windows_known_folders import KnownFolderError, known_folder_path
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components, require_windows
from ticketbox_lifecycle.schemas import InstallRequest

MANAGER_APP_ID = "Ticketbox.Manager"
_FOLDERID_COMMON_PROGRAMS = UUID("0139d44e-6afe-49f2-8690-3dafcae6ffb8")
_CLSID_SHELL_LINK = UUID("00021401-0000-0000-c000-000000000046")
_IID_ISHELL_LINK_W = UUID("000214f9-0000-0000-c000-000000000046")
_IID_IPERSIST_FILE = UUID("0000010b-0000-0000-c000-000000000046")
_IID_IPROPERTY_STORE = UUID("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
_FMTID_APP_USER_MODEL = UUID("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")
_PID_APP_USER_MODEL_ID = 5
_VT_LPWSTR = 31
_CLSCTX_INPROC_SERVER = 1
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = 0x80010106
_STGM_READ = 0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: UUID) -> _GUID:
        return cls.from_buffer_copy(value.bytes_le)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
        ("wReserved2", ctypes.c_uint16),
        ("wReserved3", ctypes.c_uint16),
        ("pwszVal", ctypes.c_void_p),
        ("_pad", ctypes.c_uint64),
    ]


def _vtable_call(com_ptr: ctypes.c_void_p, index: int, restype: object, *argtypes: object):
    vtable = ctypes.cast(com_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtable[index])


def _com_release(com_ptr: ctypes.c_void_p | None) -> None:
    if com_ptr and com_ptr.value:
        _vtable_call(com_ptr, 2, ctypes.c_ulong)(com_ptr)


def _check_hr(hr: int, *, message: str, require_s_ok: bool = False) -> None:
    if (require_s_ok and hr != 0) or hr < 0:
        raise LifecycleError(
            "shortcut_update_failed",
            f"{message} (HRESULT=0x{hr & 0xFFFFFFFF:08x})",
        )


def _query_interface(com_ptr: ctypes.c_void_p, iid: UUID, *, message: str) -> ctypes.c_void_p:
    target = ctypes.c_void_p()
    guid = _GUID.from_uuid(iid)
    hr = _vtable_call(com_ptr, 0, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
        com_ptr,
        ctypes.byref(guid),
        ctypes.byref(target),
    )
    _check_hr(hr, message=message, require_s_ok=True)
    return target


def _create_shell_link() -> ctypes.c_void_p:
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    clsid = _GUID.from_uuid(_CLSID_SHELL_LINK)
    iid = _GUID.from_uuid(_IID_ISHELL_LINK_W)
    shell_link = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(clsid),
        None,
        _CLSCTX_INPROC_SERVER,
        ctypes.byref(iid),
        ctypes.byref(shell_link),
    )
    _check_hr(hr, message="CoCreateInstance(IShellLinkW) failed", require_s_ok=True)
    return shell_link


def _co_initialize() -> bool:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_long
    hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if (hr & 0xFFFFFFFF) == _RPC_E_CHANGED_MODE:
        return False
    _check_hr(hr, message="CoInitializeEx failed")
    return True


def _norm_path(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(value)))


def _verify_saved_shortcut(
    path: Path,
    *,
    target_path: Path,
    working_dir: Path,
    icon_path: Path,
    app_user_model_id: str,
) -> None:
    observed = read_shortcut(path)
    if (
        _norm_path(str(observed["target"])) != _norm_path(target_path)
        or _norm_path(str(observed["working_dir"])) != _norm_path(working_dir)
        or _norm_path(str(observed["icon"])) != _norm_path(icon_path)
        or observed.get("icon_index") != 0
        or observed["app_user_model_id"] != app_user_model_id
    ):
        raise LifecycleError(
            "shortcut_update_failed",
            "saved Start Menu shortcut failed post-save readback verification",
        )


def write_shortcut(
    shortcut_path: Path,
    *,
    target_path: Path,
    working_dir: Path,
    icon_path: Path,
    app_user_model_id: str = MANAGER_APP_ID,
) -> None:
    require_windows()
    reject_reparse_components(shortcut_path)
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    should_uninit = _co_initialize()
    tmp_path: Path | None = None
    shell_link = prop_store = persist_file = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=shortcut_path.stem,
            suffix=".lnk.tmp",
            dir=str(shortcut_path.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        shell_link = _create_shell_link()
        _check_hr(
            _vtable_call(shell_link, 20, ctypes.c_long, ctypes.c_wchar_p)(shell_link, str(target_path)),
            message="IShellLinkW.SetPath failed",
            require_s_ok=True,
        )
        _check_hr(
            _vtable_call(shell_link, 9, ctypes.c_long, ctypes.c_wchar_p)(shell_link, str(working_dir)),
            message="IShellLinkW.SetWorkingDirectory failed",
            require_s_ok=True,
        )
        _check_hr(
            _vtable_call(shell_link, 17, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(
                shell_link,
                str(icon_path),
                0,
            ),
            message="IShellLinkW.SetIconLocation failed",
            require_s_ok=True,
        )
        prop_store = _query_interface(shell_link, _IID_IPROPERTY_STORE, message="QueryInterface(IPropertyStore) failed")
        pkey = _PROPERTYKEY(_GUID.from_uuid(_FMTID_APP_USER_MODEL), _PID_APP_USER_MODEL_ID)
        value_buf = ctypes.create_unicode_buffer(app_user_model_id)
        propvar = _PROPVARIANT()
        propvar.vt = _VT_LPWSTR
        propvar.pwszVal = ctypes.cast(value_buf, ctypes.c_void_p).value
        _check_hr(
            _vtable_call(
                prop_store,
                6,
                ctypes.c_long,
                ctypes.POINTER(_PROPERTYKEY),
                ctypes.POINTER(_PROPVARIANT),
            )(prop_store, ctypes.byref(pkey), ctypes.byref(propvar)),
            message="IPropertyStore.SetValue(AppUserModelID) failed",
            require_s_ok=True,
        )
        _check_hr(
            _vtable_call(prop_store, 7, ctypes.c_long)(prop_store),
            message="IPropertyStore.Commit failed",
            require_s_ok=True,
        )
        persist_file = _query_interface(shell_link, _IID_IPERSIST_FILE, message="QueryInterface(IPersistFile) failed")
        _check_hr(
            _vtable_call(persist_file, 6, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(
                persist_file,
                str(tmp_path),
                1,
            ),
            message="IPersistFile.Save failed",
            require_s_ok=True,
        )
        _com_release(persist_file)
        persist_file = None
        _com_release(prop_store)
        prop_store = None
        _com_release(shell_link)
        shell_link = None
        _verify_saved_shortcut(
            tmp_path,
            target_path=target_path,
            working_dir=working_dir,
            icon_path=icon_path,
            app_user_model_id=app_user_model_id,
        )
        os.replace(tmp_path, shortcut_path)
    finally:
        _com_release(persist_file)
        _com_release(prop_store)
        _com_release(shell_link)
        if should_uninit:
            ctypes.windll.ole32.CoUninitialize()
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def read_shortcut(shortcut_path: Path) -> dict[str, object]:
    require_windows()
    should_uninit = _co_initialize()
    shell_link = prop_store = persist_file = None
    try:
        shell_link = _create_shell_link()
        persist_file = _query_interface(shell_link, _IID_IPERSIST_FILE, message="QueryInterface(IPersistFile) failed")
        _check_hr(
            _vtable_call(persist_file, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_uint32)(
                persist_file,
                str(shortcut_path),
                _STGM_READ,
            ),
            message="IPersistFile.Load failed",
            require_s_ok=True,
        )
        target_buf = ctypes.create_unicode_buffer(1024)
        _check_hr(
            _vtable_call(
                shell_link,
                3,
                ctypes.c_long,
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_uint32,
            )(shell_link, target_buf, len(target_buf), None, 0),
            message="IShellLinkW.GetPath failed",
            require_s_ok=True,
        )
        work_buf = ctypes.create_unicode_buffer(1024)
        _check_hr(
            _vtable_call(shell_link, 8, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)(
                shell_link,
                work_buf,
                len(work_buf),
            ),
            message="IShellLinkW.GetWorkingDirectory failed",
            require_s_ok=True,
        )
        icon_buf = ctypes.create_unicode_buffer(1024)
        icon_idx = ctypes.c_int()
        _check_hr(
            _vtable_call(
                shell_link,
                16,
                ctypes.c_long,
                ctypes.c_wchar_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            )(shell_link, icon_buf, len(icon_buf), ctypes.byref(icon_idx)),
            message="IShellLinkW.GetIconLocation failed",
            require_s_ok=True,
        )
        prop_store = _query_interface(shell_link, _IID_IPROPERTY_STORE, message="QueryInterface(IPropertyStore) failed")
        pkey = _PROPERTYKEY(_GUID.from_uuid(_FMTID_APP_USER_MODEL), _PID_APP_USER_MODEL_ID)
        propvar = _PROPVARIANT()
        _check_hr(
            _vtable_call(
                prop_store,
                5,
                ctypes.c_long,
                ctypes.POINTER(_PROPERTYKEY),
                ctypes.POINTER(_PROPVARIANT),
            )(prop_store, ctypes.byref(pkey), ctypes.byref(propvar)),
            message="IPropertyStore.GetValue failed",
            require_s_ok=True,
        )
        app_id = ""
        try:
            if propvar.vt == _VT_LPWSTR and propvar.pwszVal:
                app_id = ctypes.wstring_at(propvar.pwszVal)
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(propvar))
        return {
            "target": target_buf.value,
            "working_dir": work_buf.value,
            "icon": icon_buf.value,
            "icon_index": int(icon_idx.value),
            "app_user_model_id": app_id,
        }
    finally:
        _com_release(persist_file)
        _com_release(prop_store)
        _com_release(shell_link)
        if should_uninit:
            ctypes.windll.ole32.CoUninitialize()


def update_manager_start_menu_shortcut(
    request: InstallRequest,
    *,
    programs_root: Path | None = None,
) -> Path:
    if programs_root is None:
        try:
            programs_root = known_folder_path(_FOLDERID_COMMON_PROGRAMS)
        except KnownFolderError as exc:
            raise LifecycleError(
                "shortcut_update_failed",
                f"cannot resolve Windows Common Programs folder: {exc.code}",
            ) from exc
    app_dir = Path(request.app_dir)
    manager_dir = app_dir / "releases" / request.target_release_id / "manager"
    shortcut_path = programs_root / "小票夹" / "管理小票夹.lnk"
    write_shortcut(
        shortcut_path,
        target_path=manager_dir / "ticketbox-manager.exe",
        working_dir=manager_dir,
        icon_path=app_dir / "ticketbox.ico",
        app_user_model_id=MANAGER_APP_ID,
    )
    return shortcut_path


def remove_manager_start_menu_shortcut(*, programs_root: Path | None = None) -> bool:
    if programs_root is None:
        try:
            programs_root = known_folder_path(_FOLDERID_COMMON_PROGRAMS)
        except KnownFolderError as exc:
            raise LifecycleError(
                "shortcut_remove_failed",
                f"cannot resolve Windows Common Programs folder: {exc.code}",
            ) from exc
    folder = programs_root / "小票夹"
    shortcut_path = folder / "管理小票夹.lnk"
    reject_reparse_components(shortcut_path)
    removed = False
    if shortcut_path.is_file():
        shortcut_path.unlink()
        removed = True
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return removed
