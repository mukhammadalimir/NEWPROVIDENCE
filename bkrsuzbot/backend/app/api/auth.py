"""Проверка Telegram Mini App initData на сервере.

Алгоритм — из официальной документации
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app :
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
где data_check_string — все поля, кроме hash, в виде key=value,
отсортированные по ключу и разделённые "\\n".
Фронтенд отправляет initData в заголовке:  Authorization: tma <initData>
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings, get_settings


class InitDataError(Exception):
    pass


@dataclass
class TgUser:
    id: int
    first_name: str = ""
    language_code: str | None = None


def verify_init_data(init_data: str, bot_token: str, max_age: int,
                     now: float | None = None) -> TgUser:
    if not init_data or not bot_token:
        raise InitDataError("empty")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", None)
    if not received:
        raise InitDataError("no hash")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("bad hash")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as e:
        raise InitDataError("bad auth_date") from e
    if max_age and (now or time.time()) - auth_date > max_age:
        raise InitDataError("expired")
    try:
        user = json.loads(pairs["user"])
        return TgUser(id=int(user["id"]), first_name=user.get("first_name", ""),
                      language_code=user.get("language_code"))
    except (KeyError, ValueError, TypeError) as e:
        raise InitDataError("no user") from e


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_dev_user: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> TgUser:
    if authorization and authorization.startswith("tma "):
        try:
            return verify_init_data(authorization[4:], settings.bot_token,
                                    settings.initdata_max_age)
        except InitDataError as e:
            raise HTTPException(401, {"code": "unauthorized", "reason": str(e)}) from e
    # Только для локальной разработки вне Telegram (APP_ENV=dev). В prod отключено.
    if settings.is_dev and settings.dev_auth_user_id and x_dev_user:
        return TgUser(id=settings.dev_auth_user_id, first_name="Dev")
    raise HTTPException(401, {"code": "unauthorized", "reason": "no init data"})


def admin_user(user: TgUser = Depends(current_user),
               settings: Settings = Depends(get_settings)) -> TgUser:
    if user.id not in settings.admin_ids:
        raise HTTPException(403, {"code": "forbidden"})
    return user
