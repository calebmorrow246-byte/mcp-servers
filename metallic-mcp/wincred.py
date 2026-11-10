"""Minimal Windows Credential Manager access (generic credentials) for the current user, via ctypes.

The Metallic token pair rotates on every renewal, so the server has to write the new pair back
itself; the launcher can't just pass it in once through environment variables. Secrets are stored as
UTF-16LE blobs, the same format the CredentialManager PowerShell module reads and writes.
"""

import ctypes
import sys
from ctypes import wintypes
from typing import Optional, Tuple

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("wincred requires Windows")

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_advapi = ctypes.WinDLL("advapi32", use_last_error=True)
_CredReadW = _advapi.CredReadW
_CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
_CredReadW.restype = wintypes.BOOL
_CredWriteW = _advapi.CredWriteW
_CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
_CredWriteW.restype = wintypes.BOOL
_CredFree = _advapi.CredFree
_CredFree.argtypes = [ctypes.c_void_p]
_CredFree.restype = None


def read_credential(target: str) -> Optional[Tuple[str, str]]:
    """Return (user, secret) for a generic credential, or None if it doesn't exist."""
    pcred = ctypes.POINTER(_CREDENTIALW)()
    if not _CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise OSError(err, f"CredRead failed for '{target}'")
    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize) if cred.CredentialBlobSize else b""
        return cred.UserName or "", blob.decode("utf-16-le")
    finally:
        _CredFree(pcred)


def write_credential(target: str, user: str, secret: str) -> None:
    """Create or replace a generic credential for the current user."""
    blob = secret.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.UserName = user
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    try:
        if not _CredWriteW(ctypes.byref(cred), 0):
            raise OSError(ctypes.get_last_error(), f"CredWrite failed for '{target}'")
    finally:
        ctypes.memset(buf, 0, len(blob))
