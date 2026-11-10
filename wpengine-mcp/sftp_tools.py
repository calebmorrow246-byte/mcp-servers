"""Read-only SFTP troubleshooting helpers against WPEngine installs.

Each WPEngine install has its own SFTP login (host <install>.sftp.wpengine.com:2222). Credentials
are shared, dedicated service accounts (not personal ones), stored in Windows Credential Manager as
generic credentials named 'WPEngine SFTP <install-name>', fetched on demand per call rather than
preloaded, since the set of installs can grow independently of a server restart.

wp-config.php holds the WordPress DB password and auth keys in plaintext, so it is never returned by
read_file/grep_files regardless of the path given — it's excluded by filename, not by directory.
"""

import ctypes
import hashlib
import posixpath
import re
import stat
from ctypes import wintypes
from dataclasses import dataclass

import paramiko

SFTP_PORT = 2222
_INSTALL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_READ_BYTES = 256 * 1024
_MAX_GREP_FILES = 300
_MAX_GREP_MATCHES = 200
_BLOCKED_FILENAMES = {"wp-config.php"}


class WPEngineSftpError(Exception):
    pass


def _validate_install(install: str) -> str:
    install = (install or "").strip().lower()
    if not _INSTALL_RE.fullmatch(install):
        raise WPEngineSftpError(f"Invalid install name: {install!r}")
    return install


@dataclass
class _Credential:
    username: str
    password: str


class _CREDENTIAL(ctypes.Structure):
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


_CRED_TYPE_GENERIC = 1
_ERROR_NOT_FOUND = 1168


def _get_credential(install: str) -> _Credential:
    """Fetch the generic credential 'WPEngine SFTP <install>' for the current user (svc-mcp when
    hosted) straight from Windows Credential Manager via CredReadW.

    Read in-process rather than through a PowerShell subprocess: the CredentialManager module is
    only installed for PowerShell 7 on mcp-host, so a powershell.exe (5.1) lookup always failed.
    """
    target = f"WPEngine SFTP {install}"
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    pcred = ctypes.POINTER(_CREDENTIAL)()
    if not advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            raise WPEngineSftpError(f"No SFTP credential configured for install '{install}' (target: '{target}')")
        raise WPEngineSftpError(f"Could not read credential for '{install}' (Win32 error {err})")
    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        username = cred.UserName or ""
        password = blob.decode("utf-16-le")
    finally:
        advapi32.CredFree(pcred)
    if not username or not password:
        raise WPEngineSftpError(f"Malformed credential for install '{install}'")
    return _Credential(username=username, password=password)


class _SftpSession:
    """Short-lived SFTP connection for one tool call; always closed on exit."""

    def __init__(self, install: str):
        self.install = _validate_install(install)
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def __enter__(self) -> paramiko.SFTPClient:
        cred = _get_credential(self.install)
        host = f"{self.install}.sftp.wpengine.com"
        try:
            self._transport = paramiko.Transport((host, SFTP_PORT))
            self._transport.connect(username=cred.username, password=cred.password)
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        except paramiko.AuthenticationException as exc:
            self._close()
            raise WPEngineSftpError(f"SFTP authentication failed for install '{self.install}'") from exc
        except Exception as exc:
            self._close()
            raise WPEngineSftpError(f"Could not connect to {host}:{SFTP_PORT}: {exc}") from exc
        return self._sftp

    def __exit__(self, *_exc) -> None:
        self._close()

    def _close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
        if self._transport is not None:
            self._transport.close()


def _is_blocked(remote_path: str) -> bool:
    # Normalize first so 'wp-config.php/', './x/../wp-config.php' or 'WP-Config.php' can't slip past
    filename = posixpath.basename(posixpath.normpath(remote_path.replace("\\", "/"))).lower()
    return filename in _BLOCKED_FILENAMES


def _check_target(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    """Refuse blocked files, including when reached through a symlink with an innocent name."""
    if _is_blocked(remote_path):
        raise WPEngineSftpError(f"Refusing to access '{remote_path}': contains WordPress DB credentials/auth keys")
    try:
        resolved = sftp.normalize(remote_path)
    except OSError:
        return  # nonexistent path; the caller's own stat/open reports it
    if _is_blocked(resolved):
        raise WPEngineSftpError(f"Refusing to access '{remote_path}': resolves to a blocked file")


def list_files(install: str, path: str = "wp-content") -> dict:
    with _SftpSession(install) as sftp:
        entries = []
        for attr in sftp.listdir_attr(path):
            entries.append({
                "name": attr.filename,
                "size": attr.st_size,
                "mtime": attr.st_mtime,
                "is_dir": bool(attr.st_mode and (attr.st_mode & 0o040000)),
            })
        return {"install": install, "path": path, "entries": entries}


def read_file(install: str, path: str, max_bytes: int = _MAX_READ_BYTES) -> dict:
    if _is_blocked(path):
        raise WPEngineSftpError(f"Refusing to read '{path}': contains WordPress DB credentials/auth keys")
    with _SftpSession(install) as sftp:
        _check_target(sftp, path)
        attr = sftp.stat(path)
        truncated = attr.st_size > max_bytes
        with sftp.open(path, "r") as f:
            data = f.read(max_bytes)
        text = data.decode("utf-8", errors="replace")
        return {"install": install, "path": path, "size": attr.st_size, "truncated": truncated, "content": text}


def tail_log(install: str, path: str = "wp-content/debug.log", lines: int = 200) -> dict:
    if _is_blocked(path):
        raise WPEngineSftpError(f"Refusing to read '{path}'")
    lines = max(1, min(lines, 2000))
    with _SftpSession(install) as sftp:
        _check_target(sftp, path)
        attr = sftp.stat(path)
        # Read from the tail of the file in a bounded chunk, then keep the last N lines.
        chunk_size = min(attr.st_size, 512 * 1024)
        with sftp.open(path, "r") as f:
            f.seek(max(0, attr.st_size - chunk_size))
            data = f.read(chunk_size)
        text = data.decode("utf-8", errors="replace")
        tail_lines = text.splitlines()[-lines:]
        return {"install": install, "path": path, "size": attr.st_size, "lines": tail_lines}


def hash_file(install: str, path: str) -> dict:
    if _is_blocked(path):
        raise WPEngineSftpError(f"Refusing to hash '{path}'")
    with _SftpSession(install) as sftp:
        _check_target(sftp, path)
        attr = sftp.stat(path)
        digest = hashlib.sha256()
        with sftp.open(path, "rb") as f:
            f.set_pipelined(True)
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return {"install": install, "path": path, "size": attr.st_size, "mtime": attr.st_mtime, "sha256": digest.hexdigest()}


def find_recent_files(install: str, path: str = "wp-content", hours: int = 24, max_results: int = 500) -> dict:
    cutoff_seconds = hours * 3600
    results: list[dict] = []

    def walk(sftp: paramiko.SFTPClient, base: str, newest_mtime_seen: list[float]) -> None:
        if len(results) >= max_results:
            return
        try:
            entries = sftp.listdir_attr(base)
        except OSError:
            return
        for attr in entries:
            if len(results) >= max_results:
                return
            full = f"{base}/{attr.filename}"
            is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
            if is_dir:
                walk(sftp, full, newest_mtime_seen)
            else:
                if newest_mtime_seen[0] - attr.st_mtime <= cutoff_seconds:
                    results.append({"path": full, "size": attr.st_size, "mtime": attr.st_mtime})

    with _SftpSession(install) as sftp:
        # Anchor "now" to the newest mtime under the tree rather than the local clock, in case of
        # clock skew between this host and WPEngine's SFTP backend.
        anchor = [0.0]

        def find_max(base: str) -> None:
            try:
                entries = sftp.listdir_attr(base)
            except OSError:
                return
            for attr in entries:
                is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
                anchor[0] = max(anchor[0], attr.st_mtime)
                if is_dir:
                    find_max(f"{base}/{attr.filename}")

        find_max(path)
        walk(sftp, path, anchor)
        results.sort(key=lambda r: r["mtime"], reverse=True)
        return {"install": install, "path": path, "hours": hours, "count": len(results), "files": results}


def grep_files(
    install: str,
    pattern: str,
    path: str = "wp-content",
    max_files: int = _MAX_GREP_FILES,
    max_file_bytes: int = _MAX_READ_BYTES,
) -> dict:
    regex = re.compile(pattern)
    matches: list[dict] = []
    scanned = [0]

    def walk(sftp: paramiko.SFTPClient, base: str) -> None:
        if scanned[0] >= max_files or len(matches) >= _MAX_GREP_MATCHES:
            return
        try:
            entries = sftp.listdir_attr(base)
        except OSError:
            return
        for attr in entries:
            if scanned[0] >= max_files or len(matches) >= _MAX_GREP_MATCHES:
                return
            full = f"{base}/{attr.filename}"
            is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
            if is_dir:
                walk(sftp, full)
                continue
            # listdir_attr is lstat-based: skip symlinks so a link can't smuggle in wp-config.php
            if _is_blocked(full) or (attr.st_mode and stat.S_ISLNK(attr.st_mode)):
                continue
            scanned[0] += 1
            try:
                with sftp.open(full, "r") as f:
                    text = f.read(max_file_bytes).decode("utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append({"path": full, "line": lineno, "text": line.strip()[:300]})
                    if len(matches) >= _MAX_GREP_MATCHES:
                        break

    with _SftpSession(install) as sftp:
        walk(sftp, path)
        return {
            "install": install,
            "path": path,
            "pattern": pattern,
            "files_scanned": scanned[0],
            "truncated": scanned[0] >= max_files or len(matches) >= _MAX_GREP_MATCHES,
            "matches": matches,
        }


_PLUGIN_HEADER_RE = re.compile(rb"^\s*\*?\s*Version:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def list_plugins_themes(install: str) -> dict:
    with _SftpSession(install) as sftp:
        plugins = _list_versioned(sftp, "wp-content/plugins")
        themes = _list_versioned(sftp, "wp-content/themes")
        return {"install": install, "plugins": plugins, "themes": themes}


def _list_versioned(sftp: paramiko.SFTPClient, base: str) -> list[dict]:
    out = []
    try:
        entries = sftp.listdir_attr(base)
    except OSError:
        return out
    for attr in entries:
        is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
        if not is_dir:
            continue
        version = _read_version_header(sftp, f"{base}/{attr.filename}")
        out.append({"name": attr.filename, "version": version})
    return out


def _read_version_header(sftp: paramiko.SFTPClient, dir_path: str) -> str | None:
    """Look for a 'Version: x.y.z' header in style.css (themes) or the plugin's top-level PHP files."""
    candidates = ["style.css"]
    try:
        for attr in sftp.listdir_attr(dir_path):
            if attr.filename.lower().endswith(".php"):
                candidates.append(attr.filename)
    except OSError:
        return None
    for name in candidates:
        try:
            with sftp.open(f"{dir_path}/{name}", "rb") as f:
                head = f.read(8192)
            match = _PLUGIN_HEADER_RE.search(head)
            if match:
                return match.group(1).decode("utf-8", errors="replace")
        except OSError:
            continue
    return None
