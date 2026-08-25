"""Shared helpers for BaoStock login/session recovery."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


_AUTH_ERROR_CODES = {"401", "403"}
_AUTH_ERROR_HINTS = ("未登录", "登录", "forbidden", "unauthorized", "not logged", "permission")


def is_auth_error(error_code: object, error_msg: object) -> bool:
    code = str(error_code).strip()
    msg = str(error_msg).lower()
    if code in _AUTH_ERROR_CODES:
        return True
    return any(hint in msg for hint in _AUTH_ERROR_HINTS)


def ensure_login(bs_module: Any, attempts: int = 3, pause_seconds: float = 0.5) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = bs_module.login()
        except Exception as exc:
            last_error = exc
        else:
            if str(response.error_code) == "0":
                return
            if not is_auth_error(response.error_code, response.error_msg):
                raise RuntimeError(
                    f"BaoStock login failed: {response.error_code} {response.error_msg}"
                )
            last_error = RuntimeError(
                f"BaoStock login failed: {response.error_code} {response.error_msg}"
            )
        if attempt < attempts:
            time.sleep(pause_seconds * attempt)
        continue
    if last_error is None:
        raise RuntimeError("BaoStock login failed")
    raise RuntimeError(f"BaoStock login failed after {attempts} attempts: {last_error}") from last_error


def relogin(bs_module: Any) -> None:
    try:
        bs_module.logout()
    except Exception:
        pass
    ensure_login(bs_module, attempts=2)


def query_with_relogin[T](
    bs_module: Any,
    request: Callable[[], T],
    *,
    description: str,
    attempts: int = 2,
    pause_seconds: float = 0.5,
) -> T:
    for attempt in range(1, attempts + 1):
        response = request()
        if str(getattr(response, "error_code", "0")) == "0":
            return response

        if attempt < attempts and is_auth_error(
            getattr(response, "error_code", ""),
            getattr(response, "error_msg", ""),
        ):
            relogin(bs_module)
            time.sleep(pause_seconds * attempt)
            continue
        return response

    raise RuntimeError(f"{description} failed after {attempts} attempts")
