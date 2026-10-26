"""Per-user Windows DPAPI storage for optional API-key persistence."""

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Saved keys require Windows DPAPI.")
    source = ctypes.create_string_buffer(data)
    input_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if decrypt:
        ok = function(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob))
    else:
        ok = function(ctypes.byref(input_blob), "Forge API key", None, None, None, 0, ctypes.byref(output_blob))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def vault_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise OSError("LOCALAPPDATA is unavailable; keys cannot be saved.")
    return Path(base) / "Forge" / "keys.dpapi.json"


def load_key(provider: str) -> str:
    path = vault_path()
    if not path.exists():
        return ""
    record = json.loads(path.read_text(encoding="utf-8"))
    value = record.get(provider)
    if not isinstance(value, str):
        return ""
    return _crypt(bytes.fromhex(value), True).decode("utf-8")


def save_key(provider: str, key: str) -> None:
    path = vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if key:
        record[provider] = _crypt(key.encode("utf-8"), False).hex()
    else:
        record.pop(provider, None)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.replace(path)
