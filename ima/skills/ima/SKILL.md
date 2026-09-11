---
name: ima
description: |
  使用 IMA OpenAPI 管理用户的私人笔记和知识库。当用户提到 IMA、知识库、资料库、笔记、
  备忘录、记事、知识搜索、上传文件或保存个人资料时使用此 Skill。
homepage: https://ima.qq.com
---

# IMA

通过 IMA 连接器操作用户已授权的私人笔记和知识库。POCO 负责保存 Client ID 和 API Key，
Skill 不读取、展示或要求用户再次提供凭据。

## 必须遵守的规则

1. 笔记写入前必须确认 `content` 等文本可以编码为合法 UTF-8。
2. 上传文件时保留原始文件内容，`title` 必须等于原始文件名（含扩展名）；不擅自改名、翻译或截断。
3. 不支持视频、Bilibili/YouTube 视频 URL 和 `file://` URL；直接说明只能使用 IMA 客户端处理。
4. 文件上传前必须先检查文件类型、大小和目标知识库中的同名文件。
5. 笔记内容属于用户隐私。群聊中只展示标题和摘要，不主动展示正文。
6. `append_doc`、`import_doc`、`add_knowledge`、`import_urls` 和 `upload_file` 会改变用户数据，必须经过连接器确认；写入失败后不要盲目重试。

## 模块路由

| 用户意图 | 模块 | 首选工具 |
| --- | --- | --- |
| 搜索、浏览、读取、创建或追加笔记 | `notes` | `search_note`、`list_note`、`get_doc_content`、`import_doc`、`append_doc` |
| 浏览、搜索或获取知识库 | `knowledge-base` | `search_knowledge_base`、`get_knowledge_base`、`get_knowledge_list`、`search_knowledge` |
| 上传文件、导入网页、关联笔记 | `knowledge-base` | `upload_file`、`import_urls`、`add_knowledge` |
| 查看或读取知识库原文 | `knowledge-base` | `get_media_info`、`fetch_media_content` |

需要执行模块操作时，先阅读对应目录的 `SKILL.md` 和 `references/api.md`。

## 容易混淆的场景

- “把这段内容添加到知识库里的笔记”是追加已有笔记，先在 `notes` 中找到 `note_id`，再调用 `append_doc`。
- “把这篇笔记添加到知识库”是知识库关联操作，调用 `add_knowledge`，不是 `append_doc`。
- “新建一篇笔记”调用 `import_doc`；“追加到某篇已有笔记”调用 `append_doc`。
- “帮我记一下”“保存为笔记”等没有明确新建或追加时，先询问用户意图。
- 用户没有指定目标知识库时，先调用 `get_addable_knowledge_base_list`，让用户选择，不要猜测。

## 跨模块任务

- “把知识库内容记到笔记”：先阅读并调用知识库工具获取内容，再阅读并调用笔记工具创建或追加。
- “查看知识库里的笔记原文”：先调用 `get_media_info`；当媒体类型为笔记时，再调用 `get_doc_content`。
- “把笔记添加到知识库”：先搜索笔记拿到 `note_id` 和标题，再调用 `add_knowledge`。

## 凭据与网络范围

连接器表单要求用户填写 IMA 开放平台的 **Client ID** 和 **API Key**。Provider 只向官方
`https://ima.qq.com` 发送这两个请求头：

- `ima-openapi-clientid`
- `ima-openapi-apikey`

文件上传时，Provider 只使用 IMA 返回的短时 COS 凭据访问 `*.myqcloud.com`，不会把 Client ID
或 API Key 发送给 COS，也不会将凭据写入文件、日志或 Skill。
