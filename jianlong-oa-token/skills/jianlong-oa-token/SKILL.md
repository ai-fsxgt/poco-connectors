---
name: jianlong-oa-token
description: "调用建龙 OA 系统接口前获取登录凭证。触发场景：访问建龙 OA、OA 接口、OA 待办或审批数据，OA 接口返回 401、未登录、登录已过期或 token 失效，需要 OA 访问令牌，查询本人 OA 工号。"
description_zh: "调用建龙 OA 系统接口前获取登录凭证。触发场景：访问建龙 OA、OA 接口、OA 待办或审批数据，OA 接口返回 401、未登录、登录已过期或 token 失效，需要 OA 访问令牌，查询本人 OA 工号。"
description_en: "Get the login credential before calling Jianlong OA APIs, including when an OA API returns 401 or not logged in, or the user's OA employee number is needed."
version: "1.1.0"
---

# 建龙 OA 凭证

- 访问建龙 OA 接口需要当前员工的登录凭证。不要向用户索要 token、账号或密码，用连接器工具 `get_oa_token` 换取，它以当前发消息员工的身份登录。
- 请求 OA 接口时按接口要求携带凭证；接口未说明时使用请求头 `Authorization: <token_type> <access_token>`。
- 凭证在 `expire_at` 之前可以复用；OA 接口返回 401 或凭证过期时重新调用 `get_oa_token`。
- 群聊中每条消息的发送人可能不同，凭证只属于当条消息的发送人，不要把别人的凭证用于当前发送人。
- 换取失败时把错误原样告诉用户，不要尝试其他身份或登录方式。
- 不要在回复中展示 access_token 原文。
