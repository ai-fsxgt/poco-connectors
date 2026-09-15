from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, quote_plus, urlencode

import httpx

_RESOURCE_URL = "https://mcp.canva.cn/mcp"
_ISSUER = "https://mcp.canva.cn"
_AUTHORIZE_URL = f"{_ISSUER}/authorize"
_TOKEN_URL = f"{_ISSUER}/token"
_REGISTRATION_URL = f"{_ISSUER}/register"
_SCOPES = (
    "design:meta:read",
    "design:content:read",
    "design:content:write",
    "folder:read",
    "folder:write",
    "brandtemplate:content:read",
    "brandtemplate:meta:read",
    "comment:read",
    "comment:write",
    "asset:read",
    "asset:write",
    "brandkit:read",
)


class ProgramError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:2000]
        self.retryable = retryable


def _configuration(context: dict[str, Any]) -> str:
    configuration = context.get("configuration")
    if not isinstance(configuration, dict):
        raise ProgramError("bad_request", "可画连接器配置格式无效")
    public = configuration.get("public")
    if not isinstance(public, dict):
        raise ProgramError("bad_request", "可画连接器公开配置格式无效")
    endpoint = public.get("endpoint")
    return endpoint.strip() if isinstance(endpoint, str) else ""


def _validate_endpoint(endpoint: str, *, require_complete: bool = True) -> None:
    if not endpoint:
        if require_complete:
            raise ProgramError("bad_request", "请配置可画 MCP 服务地址")
        return
    if endpoint != _RESOURCE_URL:
        raise ProgramError("bad_request", f"可画 MCP 服务地址必须为 {_RESOURCE_URL}")


def configuration_validate(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    _validate_endpoint(
        endpoint,
        require_complete=bool(context.get("require_complete")),
    )
    return {}


def authorization_identity(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    return {
        "identity": {
            "issuer": _ISSUER,
            "resource": endpoint,
            "registration": "dynamic",
            "scopes": sorted(_SCOPES),
        }
    }


def _request_json(
    url: str,
    action: str,
    *,
    json_body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    auth: httpx.BasicAuth | None = None,
) -> dict[str, Any]:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20, connect=8),
            follow_redirects=False,
        ) as client:
            response = client.post(url, json=json_body, data=form, auth=auth)
    except httpx.RequestError as exc:
        raise ProgramError(
            "unavailable",
            f"可画 OAuth {action}服务连接失败，请稍后重试",
            retryable=True,
        ) from exc
    if response.status_code == 429:
        raise ProgramError(
            "rate_limited",
            f"可画 OAuth {action}请求过于频繁，请稍后重试",
            retryable=True,
        )
    if response.status_code >= 500:
        raise ProgramError(
            "unavailable",
            f"可画 OAuth {action}服务暂时不可用",
            retryable=True,
        )
    if response.status_code >= 400:
        upstream_code = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                upstream_code = str(payload.get("error") or "")
        except ValueError:
            pass
        detail = f"（{upstream_code}）" if upstream_code else ""
        code = (
            "authorization_required"
            if action in {"换取令牌", "刷新令牌"}
            else "external_error"
        )
        raise ProgramError(code, f"可画 OAuth {action}失败{detail}")
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProgramError(
            "external_error", f"可画 OAuth {action}返回了无效 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProgramError("external_error", f"可画 OAuth {action}响应格式错误")
    return payload


def _register_client(redirect_uri: str) -> tuple[str, str]:
    payload = _request_json(
        _REGISTRATION_URL,
        "客户端注册",
        json_body={
            "client_name": "Poco Canva Connector",
            "redirect_uris": [redirect_uri],
            "response_types": ["code"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "client_secret_basic",
            "scope": " ".join(_SCOPES),
        },
    )
    client_id = payload.get("client_id")
    client_secret = payload.get("client_secret")
    auth_method = payload.get("token_endpoint_auth_method")
    redirect_uris = payload.get("redirect_uris")
    if (
        not isinstance(client_id, str)
        or not client_id
        or not isinstance(client_secret, str)
        or not client_secret
        or auth_method != "client_secret_basic"
        or not isinstance(redirect_uris, list)
        or redirect_uri not in redirect_uris
    ):
        raise ProgramError("external_error", "可画 OAuth 客户端注册响应无效")
    return client_id, client_secret


def authorization_begin(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    _validate_endpoint(endpoint)
    redirect_uri = context.get("redirect_uri")
    state = context.get("state")
    code_challenge = context.get("code_challenge")
    if not all(
        isinstance(value, str) and value
        for value in (redirect_uri, state, code_challenge)
    ):
        raise ProgramError("bad_request", "可画 OAuth 授权上下文无效")
    client_id, client_secret = _register_client(redirect_uri)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(_SCOPES),
            "resource": endpoint,
        },
        quote_via=quote,
    )
    return {
        "type": "redirect",
        "authorize_url": f"{_AUTHORIZE_URL}?{query}",
        "private_context": {
            "client_id": client_id,
            "client_secret": client_secret,
        },
    }


def _oauth_client(context: dict[str, Any]) -> tuple[str, str]:
    private_context = context.get("private_context")
    if not isinstance(private_context, dict) or set(private_context) != {
        "client_id",
        "client_secret",
    }:
        raise ProgramError("bad_request", "可画 OAuth 客户端上下文无效")
    client_id = private_context.get("client_id")
    client_secret = private_context.get("client_secret")
    if (
        not isinstance(client_id, str)
        or not client_id
        or not isinstance(client_secret, str)
        or not client_secret
    ):
        raise ProgramError("bad_request", "可画 OAuth 客户端凭据无效")
    return client_id, client_secret


def _client_auth(client_id: str, client_secret: str) -> httpx.BasicAuth:
    return httpx.BasicAuth(
        quote_plus(client_id, safe=""),
        quote_plus(client_secret, safe=""),
    )


def _token_request(
    form: dict[str, str],
    *,
    client_id: str,
    client_secret: str,
    action: str,
) -> dict[str, Any]:
    return _request_json(
        _TOKEN_URL,
        action,
        form=form,
        auth=_client_auth(client_id, client_secret),
    )


def _token_credential(
    payload: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    previous_refresh_token: str | None = None,
) -> dict[str, Any]:
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    refresh_token = payload.get("refresh_token") or previous_refresh_token
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(token_type, str)
        or token_type.lower() != "bearer"
        or not isinstance(refresh_token, str)
        or not refresh_token
    ):
        raise ProgramError("external_error", "可画 OAuth 令牌响应缺少必要字段")
    values = {
        "access_token": access_token,
        "token_type": token_type,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "issuer": _ISSUER,
        "token_url": _TOKEN_URL,
        "resource": _RESOURCE_URL,
    }
    credential: dict[str, Any] = {"values": values}
    expires_in = payload.get("expires_in")
    if expires_in is not None:
        if type(expires_in) is not int or expires_in <= 0:
            raise ProgramError("external_error", "可画 OAuth 令牌有效期无效")
        credential["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
    return credential


def _granted_scopes(payload: dict[str, Any]) -> list[str]:
    scope = payload.get("scope")
    if not isinstance(scope, str):
        return sorted(_SCOPES)
    granted = sorted(set(scope.split()))
    missing = set(_SCOPES) - set(granted)
    if missing:
        raise ProgramError("insufficient_scope", "可画账号未授予连接器所需权限")
    return granted


def authorization_complete(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    _validate_endpoint(endpoint)
    client_id, client_secret = _oauth_client(context)
    submission = context.get("submission")
    if not isinstance(submission, dict) or submission.get("type") != "oauth_code":
        raise ProgramError("bad_request", "可画连接器需要 OAuth 授权码")
    code = submission.get("code")
    redirect_uri = submission.get("redirect_uri")
    code_verifier = submission.get("code_verifier")
    if not all(
        isinstance(value, str) and value
        for value in (code, redirect_uri, code_verifier)
    ):
        raise ProgramError("bad_request", "可画 OAuth 回调参数无效")
    token = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "resource": endpoint,
        },
        client_id=client_id,
        client_secret=client_secret,
        action="换取令牌",
    )
    return {
        "credential": _token_credential(
            token,
            client_id=client_id,
            client_secret=client_secret,
        ),
        "granted_scopes": _granted_scopes(token),
        "public_metadata": {"issuer": _ISSUER, "resource": endpoint},
    }


def _credential_values(context: dict[str, Any]) -> dict[str, str]:
    credential = context.get("credential")
    if not isinstance(credential, dict):
        raise ProgramError("authorization_required", "可画 OAuth 凭据不存在")
    values = credential.get("values")
    if not isinstance(values, dict):
        raise ProgramError("authorization_required", "可画 OAuth 凭据格式无效")
    result: dict[str, str] = {}
    for key in ("access_token", "refresh_token", "client_id", "client_secret"):
        value = values.get(key)
        if not isinstance(value, str) or not value:
            raise ProgramError("authorization_required", "可画 OAuth 凭据不完整")
        result[key] = value
    return result


def credential_refresh(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    _validate_endpoint(endpoint)
    values = _credential_values(context)
    token = _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": values["refresh_token"],
            "resource": endpoint,
        },
        client_id=values["client_id"],
        client_secret=values["client_secret"],
        action="刷新令牌",
    )
    return {
        "credential": _token_credential(
            token,
            client_id=values["client_id"],
            client_secret=values["client_secret"],
            previous_refresh_token=values["refresh_token"],
        ),
        "granted_scopes": _granted_scopes(token) if "scope" in token else None,
    }


def credential_revoke(context: dict[str, Any]) -> dict[str, Any]:
    endpoint = _configuration(context)
    _validate_endpoint(endpoint)
    values = _credential_values(context)
    _request_json(
        _TOKEN_URL,
        "撤销令牌",
        form={"token": values["refresh_token"]},
        auth=_client_auth(values["client_id"], values["client_secret"]),
    )
    return {}


_OPERATIONS = {
    "configuration_validate": configuration_validate,
    "authorization_identity": authorization_identity,
    "authorization_begin": authorization_begin,
    "authorization_complete": authorization_complete,
    "credential_refresh": credential_refresh,
    "credential_revoke": credential_revoke,
}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("protocol_version") != 1:
            raise ProgramError("bad_request", "连接器协议版本错误")
        operation = request.get("operation")
        context = request.get("context")
        handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
        if handler is None or not isinstance(context, dict):
            raise ProgramError("bad_request", "连接器操作不受支持")
        response = {"protocol_version": 1, "ok": True, "result": handler(context)}
    except ProgramError as exc:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            },
        }
    except Exception:
        response = {
            "protocol_version": 1,
            "ok": False,
            "error": {
                "code": "external_error",
                "message": "可画连接器程序执行失败",
                "retryable": False,
            },
        }
    json.dump(
        response,
        sys.stdout,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


if __name__ == "__main__":
    main()
