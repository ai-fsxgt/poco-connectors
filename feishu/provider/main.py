import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from errors import ProgramError
from lark_runtime import discover_tools, invoke_tool

OPEN_API = "https://open.feishu.cn"
OAUTH_AUTHORIZE = OPEN_API + "/open-apis/authen/v1/authorize"
OAUTH_TOKEN = OPEN_API + "/open-apis/authen/v2/oauth/token"
OAUTH_REVOKE = "https://accounts.feishu.cn/oauth/v1/revoke"
USER_INFO = OPEN_API + "/open-apis/authen/v1/user_info"


def _config(context: dict[str, Any]) -> tuple[str, str]:
    configuration = context.get("configuration", {})
    public = configuration.get("public", {})
    secret = configuration.get("secret", {})
    return str(public.get("app_id", "")).strip(), str(secret.get("app_secret", "")).strip()


def _request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        raise ProgramError("unavailable", "飞书授权服务请求失败，请稍后重试") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError("external_error", "飞书授权服务未返回有效 JSON") from exc
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise ProgramError("authorization_required" if response.status_code in {400, 401} else "external_error", f"飞书授权服务返回 HTTP {response.status_code}")
    if payload.get("code", 0) not in (0, "0"):
        raise ProgramError("authorization_required", str(payload.get("msg") or "飞书授权失败"))
    return payload


def _credential(data: dict[str, Any]) -> dict[str, Any]:
    access = data.get("access_token") or data.get("data", {}).get("access_token")
    refresh = data.get("refresh_token") or data.get("data", {}).get("refresh_token")
    expires = data.get("expires_in") or data.get("data", {}).get("expires_in")
    refresh_expires = data.get("refresh_token_expires_in") or data.get("data", {}).get("refresh_token_expires_in")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or type(expires) is not int or expires <= 0:
        raise ProgramError("external_error", "飞书令牌响应缺少凭据或有效期")
    result = {"values": {"access_token": access, "refresh_token": refresh}, "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat()}
    if type(refresh_expires) is int and refresh_expires > 0:
        result["refresh_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=refresh_expires)).isoformat()
    return result


def validate_configuration(context: dict[str, Any]) -> dict[str, Any]:
    app_id, secret = _config(context)
    if context.get("require_complete") and (not app_id or not secret):
        raise ProgramError("bad_request", "请配置飞书应用的 App ID 和 App Secret")
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    app_id, _ = _config(context)
    return {"identity": {"app_id": app_id, "brand": "feishu"}}


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    app_id, _ = _config(context)
    params = {"app_id": app_id, "redirect_uri": context["redirect_uri"], "response_type": "code", "state": context["state"]}
    if context.get("code_challenge"):
        params.update({"code_challenge": context["code_challenge"], "code_challenge_method": "S256"})
    query = urlencode(params)
    return {"type": "redirect", "authorize_url": f"{OAUTH_AUTHORIZE}?{query}", "private_context": {}}


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    app_id, secret = _config(context)
    submission = context.get("submission", {})
    if submission.get("type") != "oauth_code":
        raise ProgramError("bad_request", "飞书连接器需要 OAuth 授权码")
    token_request = {"grant_type": "authorization_code", "client_id": app_id, "client_secret": secret, "code": submission.get("code", "")}
    redirect_uri = submission.get("redirect_uri", context.get("redirect_uri", ""))
    if redirect_uri:
        token_request["redirect_uri"] = redirect_uri
    if submission.get("code_verifier"):
        token_request["code_verifier"] = submission["code_verifier"]
    payload = _request("POST", OAUTH_TOKEN, json=token_request)
    data = payload.get("data", payload)
    credential = _credential(data)
    user = _request("GET", USER_INFO, headers={"Authorization": f"Bearer {credential['values']['access_token']}"}).get("data", {})
    user_id = user.get("open_id") or user.get("user_id") or user.get("union_id")
    name = user.get("name") or user.get("en_name") or user_id
    if not isinstance(user_id, str) or not user_id or not isinstance(name, str) or not name:
        raise ProgramError("external_error", "飞书用户信息缺少有效身份")
    return {"external_account_id": user_id, "external_account_name": name, "avatar_url": user.get("avatar_url"), "credential": credential, "granted_scopes": data.get("scope", "").split() if isinstance(data.get("scope"), str) else [], "public_metadata": {"tenant_brand": "feishu"}}


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    app_id, secret = _config(context)
    credential = context.get("credential", {})
    values = credential.get("values", {}) if isinstance(credential, dict) else {}
    refresh = values.get("refresh_token") if isinstance(values, dict) else None
    if not isinstance(refresh, str) or not refresh:
        raise ProgramError("authorization_required", "飞书刷新令牌不可用，请重新授权")
    payload = _request("POST", OAUTH_TOKEN, json={"grant_type": "refresh_token", "client_id": app_id, "client_secret": secret, "refresh_token": refresh})
    return {"credential": _credential(payload.get("data", payload))}


def credential_revoke(context: dict[str, Any]) -> dict[str, Any]:
    credential = context.get("credential", {})
    values = credential.get("values", {}) if isinstance(credential, dict) else {}
    token = values.get("access_token") if isinstance(values, dict) else None
    if not isinstance(token, str) or not token:
        return {}
    _request("POST", OAUTH_REVOKE, data={"token": token, "token_type_hint": "access_token"})
    return {}


def launch_url(_: dict[str, Any]) -> dict[str, Any]:
    return {"url": "https://www.feishu.cn/"}


OPERATIONS = {"configuration_validate": validate_configuration, "authorization_identity": authorization_identity, "authorization_begin": authorization_begin, "authorization_complete": authorization_complete, "credential_refresh": credential_refresh, "credential_revoke": credential_revoke, "launch_url": launch_url, "tools_discover": discover_tools, "tool_invoke": invoke_tool}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        handler = OPERATIONS.get(request.get("operation"))
        if handler is None or not isinstance(request.get("context"), dict):
            raise ProgramError("bad_request", "不支持的连接器操作")
        response = {"protocol_version": 1, "ok": True, "result": handler(request["context"])}
    except ProgramError as exc:
        response = {"protocol_version": 1, "ok": False, "error": {"code": exc.code, "message": exc.message, "retryable": False}}
    except Exception:
        response = {"protocol_version": 1, "ok": False, "error": {"code": "external_error", "message": "飞书连接器运行失败", "retryable": False}}
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > 950_000:
        encoded = json.dumps({"protocol_version": 1, "ok": False, "error": {"code": "response_too_large", "message": "飞书连接器响应超过 Poco 单次返回限制", "retryable": False}}, ensure_ascii=False)
    print(encoded)


if __name__ == "__main__":
    main()
