---
name: ima-knowledge-base
description: 使用 IMA 连接器浏览、搜索、上传和导入知识库内容，并读取资料原文。用户提到知识库、资料库、上传文件或网页收藏时使用。
---

# IMA 知识库

API 参考见 [references/api.md](references/api.md)。所有请求由连接器 Provider 发送。

## 工具决策

| 用户意图 | 工具 | 关键参数 |
| --- | --- | --- |
| 获取知识库详情 | `get_knowledge_base` | `ids`（1-20 个） |
| 搜索知识库名称 | `search_knowledge_base` | `query`、`cursor`、`limit` |
| 查看可写入的知识库 | `get_addable_knowledge_base_list` | `cursor`、`limit` |
| 浏览文件和文件夹 | `get_knowledge_list` | `knowledge_base_id`、`cursor`、`limit`、`folder_id?` |
| 搜索知识库内容 | `search_knowledge` | `query`、`knowledge_base_id`、`cursor` |
| 检查文件名重复 | `check_repeated_names` | `params`、`knowledge_base_id` |
| 添加网页或微信文章 | `import_urls` | `urls`、`knowledge_base_id`、`folder_id?` |
| 将笔记关联到知识库 | `add_knowledge` | `note_id`、`title`、`knowledge_base_id` |
| 上传本地文件 | `upload_file` | `file_path`、`knowledge_base_id`、`folder_id?` |
| 获取媒体访问信息 | `get_media_info` | `media_id` |
| 读取媒体原文 | `fetch_media_content` | `media_id` |

## 选择目标知识库

- 用户明确给出知识库名称时，先调用 `search_knowledge_base`，找到唯一目标后再获取详情或执行操作。
- 用户只说“添加到知识库”而没有指定目标时，调用 `get_addable_knowledge_base_list`，展示名称让用户选择，不能猜测。
- `get_knowledge_list` 返回的文件夹也是知识条目；需要进入文件夹时，将结果中的文件夹 ID 作为 `folder_id`。
- 根目录省略 `folder_id`，不要把 `knowledge_base_id` 当作普通文件夹 ID 传入。

## 查询流程

1. 用 `search_knowledge_base` 定位知识库名称，必要时用 `get_knowledge_base` 获取描述和推荐问题。
2. 用 `get_knowledge_list` 浏览文件夹，或用 `search_knowledge` 按关键词搜索。
3. 需要原文时先调用 `get_media_info`；可访问的媒体再调用 `fetch_media_content`。
4. 所有列表和搜索都要检查 `is_end`，用 `next_cursor` 继续分页。

## 文件上传安全门

`upload_file` 会在 Provider 内执行以下步骤，任一步失败都会停止：

1. 根据扩展名检查类型和大小；不支持视频、Bilibili/YouTube URL、`file://` 和未知文件类型。
2. 调用重名检查；发现同名文件时停止并提示用户。用户确认保留副本后，重新调用并设置 `duplicate_policy="append_timestamp"`，Provider 会追加时间戳，同时保证标题和文件名一致；取消则不再调用。
3. 调用 IMA `create_media` 获取短时 COS 凭据。
4. 使用临时凭据上传原始二进制内容。
5. 调用 `add_knowledge` 完成入库。上传失败时不要继续提交，也不要自动重试。

支持的文件类型和上限：

| 类型 | media_type | 上限 |
| --- | ---: | ---: |
| PDF、Word、PPT、音频 | 1/3/4/15 | 200 MB |
| Excel、TXT、Xmind、Markdown、HTML | 5/13/14/7/20 | 10 MB |
| 图片 | 9 | 30 MB |
| EPUB | 21 | 50 MB |

上传文件的标题必须等于原始文件名（含扩展名），不得自行翻译或改名。上传过程不得转码或修改文件内容。

## 添加网页和笔记

- 添加普通网页或微信公众号文章使用 `import_urls`，一次 1-10 个 URL；指定文件夹时传 `folder_id`。
- 不支持的视频页面和本地 `file://` URL 直接拒绝，并提示使用 IMA 桌面端。
- 将笔记关联到知识库时，先在笔记模块搜索得到 `note_id` 和标题，再调用 `add_knowledge`；这不是追加笔记正文。

## 原文读取

- `get_media_info` 返回笔记媒体时，Provider 会通过笔记 API 读取正文。
- 返回 `url_info` 时，`fetch_media_content` 会携带服务返回的 headers 获取原文。
- 没有可访问 URL 时只提示“请使用 IMA 客户端查看原文”，不要猜测或拼接地址。
- 向用户展示知识库名称、文件标题和文件夹名称，不主动展示 `knowledge_base_id`、`media_id` 或 `folder_id`。

## 用户体验和错误处理

- 查询结果不足时按游标继续获取，不要凭空补写内容。
- 批量操作汇总成功与失败项目；失败时展示 Provider 返回的具体消息。
- 业务错误码由 IMA 返回，按 `msg` 解释；限频停止请求并稍后重试。
