import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from dws_runtime import discover_tools, invoke_tool
from errors import ProgramError

_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
_USER_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


def _configuration(context: dict[str, Any]) -> tuple[str, str]:
    configuration = context["configuration"]
    return (
        configuration["public"].get("app_key", "").strip(),
        configuration["secret"].get("app_secret", "").strip(),
    )


def validate_configuration(context: dict[str, Any]) -> dict[str, Any]:
    app_key, app_secret = _configuration(context)
    if context["require_complete"] and (not app_key or not app_secret):
        raise ProgramError("bad_request", "请配置钉钉应用的 AppKey 和 AppSecret")
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    app_key, _ = _configuration(context)
    return {"identity": {"app_key": app_key, "edition": "dingtalk-cn"}}


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    app_key, _ = _configuration(context)
    query = urlencode(
        {
            "client_id": app_key,
            "redirect_uri": context["redirect_uri"],
            "response_type": "code",
            "scope": "openid corpid",
            "state": context["state"],
            "prompt": "consent",
        },
        quote_via=quote,
    )
    return {
        "type": "redirect",
        "authorize_url": f"https://login.dingtalk.com/oauth2/auth?{query}",
        "private_context": {},
    }


def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=12, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        raise ProgramError(
            "unavailable", "钉钉授权服务请求失败，请重新发起授权"
        ) from exc
    if response.status_code >= 400:
        code = (
            "authorization_required"
            if response.status_code in {400, 401}
            else "external_error"
        )
        raise ProgramError(code, f"钉钉授权服务返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", "钉钉授权服务未返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", "钉钉授权服务响应格式错误")
    return payload


def _credential(payload: dict[str, Any]) -> dict[str, Any]:
    access_token = payload.get("accessToken")
    refresh_token = payload.get("refreshToken")
    expires_in = payload.get("expireIn")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or type(expires_in) is not int
        or expires_in <= 0
    ):
        raise ProgramError("external_error", "钉钉令牌响应缺少凭据或有效期")
    return {
        "values": {"access_token": access_token, "refresh_token": refresh_token},
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat(),
    }


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    app_key, app_secret = _configuration(context)
    submission = context["submission"]
    if submission["type"] != "oauth_code":
        raise ProgramError("bad_request", "钉钉连接器需要 OAuth 授权码")
    tokens = _request_json(
        "POST",
        _TOKEN_URL,
        json={
            "clientId": app_key,
            "clientSecret": app_secret,
            "code": submission["code"],
            "grantType": "authorization_code",
        },
    )
    credential = _credential(tokens)
    user = _request_json(
        "GET",
        _USER_URL,
        headers={"x-acs-dingtalk-access-token": credential["values"]["access_token"]},
    )
    union_id, name = user.get("unionId"), user.get("nick")
    if (
        not isinstance(union_id, str)
        or not union_id
        or not isinstance(name, str)
        or not name
    ):
        raise ProgramError("external_error", "钉钉用户信息缺少 unionId 或 nick")
    avatar_url = user.get("avatarUrl")
    if not isinstance(avatar_url, str):
        avatar_url = None
    return {
        "external_account_id": union_id,
        "external_account_name": name,
        "avatar_url": avatar_url,
        "credential": credential,
        "granted_scopes": [],
        "public_metadata": {"corp_id": tokens.get("corpId")},
    }


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    app_key, app_secret = _configuration(context)
    tokens = _request_json(
        "POST",
        _TOKEN_URL,
        json={
            "clientId": app_key,
            "clientSecret": app_secret,
            "refreshToken": context["credential"]["values"]["refresh_token"],
            "grantType": "refresh_token",
        },
    )
    return {"credential": _credential(tokens)}


def launch_url(context: dict[str, Any]) -> dict[str, Any]:
    del context
    return {"url": "https://www.dingtalk.com/"}


_OPERATIONS = {
    "configuration_validate": validate_configuration,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "credential_refresh": credential_refresh,
    "launch_url": launch_url,
    "tools_discover": discover_tools,
    "tool_invoke": invoke_tool,
}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        handler = _OPERATIONS.get(request.get("operation"))
        if handler is None or not isinstance(request.get("context"), dict):
            raise ProgramError("bad_request", "不支持的连接器操作")
        result = handler(request["context"])
        response = {"protocol_version": 1, "ok": True, "result": result}
    except ProgramError as exc:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": False,
            },
        }
    except Exception:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": "external_error",
                "message": "钉钉连接器运行失败",
                "retryable": False,
            },
        }
    encoded = json.dumps(
        response, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(encoded.encode()) > 950_000:
        encoded = json.dumps(
            {
                "protocol_version": 1,
                "ok": False,
                "error": {
                    "code": "response_too_large",
                    "message": "结果超过 Poco 单次返回限制；请缩小查询范围。写操作可能已完成，请先查询状态，勿重复执行。",
                    "retryable": False,
                },
            },
            ensure_ascii=False,
        )
    print(encoded)


if __name__ == "__main__":
    main()
