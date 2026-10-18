"""Read-only Windows process identity primitives for lifecycle control.

No environment, process memory, model credential or issuer token is inspected.
The caller may reuse ``identity_from_handle`` on its held termination handle.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import re


class WindowsIdentityError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_GROUPS_ONE(ctypes.Structure):
    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", SID_AND_ATTRIBUTES * 1)]


def winapi():
    if os.name != "nt":
        raise WindowsIdentityError("WINDOWS_IDENTITY_REQUIRED")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    return kernel, security


def _token_data(security, token, kind):
    required = wintypes.DWORD()
    succeeded = security.GetTokenInformation(token, kind, None, 0, ctypes.byref(required))
    if succeeded or ctypes.get_last_error() != 122 or not 4 <= required.value <= 65536:
        raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
    buffer = ctypes.create_string_buffer(required.value)
    if not security.GetTokenInformation(token, kind, buffer, len(buffer), ctypes.byref(required)):
        raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
    return buffer


def _sid_string(kernel, security, sid):
    converted = wintypes.LPWSTR()
    if not sid or not security.ConvertSidToStringSidW(sid, ctypes.byref(converted)):
        raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
    try:
        result = converted.value
        if not result or not re.fullmatch(r"S-1-\d+(?:-\d+)+", result):
            raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
        return result
    finally:
        kernel.LocalFree(ctypes.cast(converted, ctypes.c_void_p))


def security_from_handle(handle):
    """Query the primary token associated with this exact process handle."""
    kernel, security = winapi()
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
    try:
        user_data = _token_data(security, token, 1)  # TokenUser
        groups_data = _token_data(security, token, 28)  # TokenLogonSid
        session_data = _token_data(security, token, 12)  # TokenSessionId
        if len(user_data) < ctypes.sizeof(SID_AND_ATTRIBUTES) or len(groups_data) < ctypes.sizeof(TOKEN_GROUPS_ONE):
            raise WindowsIdentityError("WINDOWS_TOKEN_UNVERIFIED")
        user = SID_AND_ATTRIBUTES.from_buffer(user_data)
        groups = TOKEN_GROUPS_ONE.from_buffer(groups_data)
        if groups.GroupCount != 1 or groups.Groups[0].Attributes & 0xC0000000 != 0xC0000000:
            raise WindowsIdentityError("WINDOWS_LOGON_ID_REQUIRED")
        logon_sid = _sid_string(kernel, security, groups.Groups[0].Sid)
        if not re.fullmatch(r"S-1-5-5-\d+-\d+", logon_sid):
            raise WindowsIdentityError("WINDOWS_LOGON_ID_REQUIRED")
        return {"user_sid": _sid_string(kernel, security, user.Sid), "logon_sid": logon_sid,
                "session_id": wintypes.DWORD.from_buffer(session_data).value}
    finally:
        kernel.CloseHandle(token)


@contextmanager
def query_process(pid):
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    kernel, _ = winapi()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    try:
        yield handle
    finally:
        kernel.CloseHandle(handle)


def identity_from_handle(handle):
    """PID, raw FILETIME, image and token identity from one held OS handle."""
    kernel, _ = winapi()
    if kernel.WaitForSingleObject(handle, 0) != 258:
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    size = wintypes.DWORD(32768)
    image = ctypes.create_unicode_buffer(size.value)
    if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    pid = kernel.GetProcessId(handle)
    if not pid:
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    result = {"pid": int(pid), "created": (created.dwHighDateTime << 32) | created.dwLowDateTime,
              "executable": image.value, **security_from_handle(handle)}
    if kernel.WaitForSingleObject(handle, 0) != 258:
        raise WindowsIdentityError("WINDOWS_PROCESS_UNVERIFIED")
    return result


def process_identity(pid):
    with query_process(pid) as handle:
        return identity_from_handle(handle)


def process_security(pid):
    identity = process_identity(pid)
    return {key: identity[key] for key in ("user_sid", "logon_sid", "session_id")}


def same_identity(expected, actual):
    keys = ("pid", "created", "user_sid", "logon_sid", "session_id")
    return (isinstance(expected, dict) and isinstance(actual, dict)
            and all(key in expected and expected[key] == actual.get(key) for key in keys)
            and isinstance(expected.get("executable"), str) and isinstance(actual.get("executable"), str)
            and os.path.normcase(expected["executable"]) == os.path.normcase(actual["executable"]))
