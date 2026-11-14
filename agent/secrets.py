"""Keep the saved API key out of reach of a copied settings file.

On Windows the key is sealed with DPAPI (``CryptProtectData``), which ties
the ciphertext to the user account: the same bytes on another machine, or
under another account, decrypt to nothing. Elsewhere the key is base64 --
that is encoding, not protection, and the settings file is still created
owner-only, but nothing stronger is available without a dependency.

Settings written by an older version stored the key as a plain string;
:func:`unprotect` still reads those.
"""

from __future__ import annotations

import base64
import sys

WINDOWS = sys.platform.startswith("win")


def protect(text: str) -> dict[str, str]:
    """The value to store in the settings file for this key."""

    if not text:
        return {}

    if WINDOWS:
        sealed = _protect_windows(text.encode("utf-8"))

        if sealed is not None:
            return {
                "scheme": "dpapi",
                "data": base64.b64encode(sealed).decode("ascii"),
            }

    return {
        "scheme": "base64",
        "data": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    }


def unprotect(payload) -> str:
    """The key back, or an empty string when it cannot be read."""

    if isinstance(payload, str):
        # A settings file from before this module existed.
        return payload

    if not isinstance(payload, dict):
        return ""

    scheme = str(payload.get("scheme") or "")

    try:
        raw = base64.b64decode(str(payload.get("data") or ""))
    except Exception:
        return ""

    if scheme == "dpapi":
        opened = _unprotect_windows(raw)

        return opened.decode("utf-8", "replace") if opened else ""

    if scheme == "base64":
        return raw.decode("utf-8", "replace")

    return ""


# ----------------------------------------------------------------------
# Windows DPAPI, through ctypes so there is nothing to install
# ----------------------------------------------------------------------

if WINDOWS:  # pragma: no cover - exercised on the Windows runner only

    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def _blob(data: bytes) -> "_Blob":
        buffer = ctypes.create_string_buffer(data, len(data))

        return _Blob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
        )

    def _protect_windows(data: bytes) -> bytes | None:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        source = _blob(data)
        sealed = _Blob()

        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "office-agent",
            None,
            None,
            None,
            0,
            ctypes.byref(sealed),
        )

        if not ok:
            return None

        try:
            return ctypes.string_at(sealed.pbData, sealed.cbData)
        finally:
            kernel32.LocalFree(sealed.pbData)

    def _unprotect_windows(data: bytes) -> bytes | None:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        source = _blob(data)
        opened = _Blob()

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(opened),
        )

        if not ok:
            return None

        try:
            return ctypes.string_at(opened.pbData, opened.cbData)
        finally:
            kernel32.LocalFree(opened.pbData)

else:

    def _protect_windows(data: bytes) -> bytes | None:  # pragma: no cover
        return None

    def _unprotect_windows(data: bytes) -> bytes | None:  # pragma: no cover
        return None
