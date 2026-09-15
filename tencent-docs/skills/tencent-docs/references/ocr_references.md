# OCR 图片识别参考

## 工具总览

| 工具 | 功能 | 输入 | 输出 |
| --- | --- | --- | --- |
| `ocr.extract` | 识别单张图片文字 | 单张图片 | 文字列表，可选坐标 |
| `ocr.toword` | 图片转在线文档 | 1 至 9 张图片 | `file_id` + `file_url` |
| `ocr.toexcel` | 图片表格转在线表格 | 1 至 9 张图片 | `file_id` + `file_url` |

限制：单张不超过 10MB，总计不超过 50MB；支持 PNG、JPG、JPEG、BMP、WEBP。

## 图片来源

- 公网 HTTP(S) URL：直接传 `image_url`。地址必须能被腾讯文档服务直接下载，不能依赖登录、内网或已过期签名。
- 本地文件：用本地文件能力读取并编码为纯 base64，再传 `image_base64`。不要把 base64 写入对话或长期文件。
- data URI：去掉 `data:image/...;base64,` 前缀，只传纯 base64。

`image_url` 与 `image_base64` 严格二选一。图片过大导致 MCP 参数超限时停止并说明限制，不通过直连 MCP 或索取额外开放平台凭据绕过。

## `ocr.extract`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `image_url` | string | 二选一 | 公网图片 URL |
| `image_base64` | string | 二选一 | 不含 data URI 前缀的纯 base64 |
| `extract_type` | string | 否 | `basic`、`accurate` 或 `efficient` |
| `with_positions` | bool | 否 | 是否返回文字坐标，默认 false |

返回 `texts`；开启坐标后还返回 `text_detections`。

## `ocr.toword` 与 `ocr.toexcel`

两者参数结构相同，输出类型分别为在线文档和在线表格。单张图片时会启用矫正增强。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `images` | array | 是 | 1 至 9 项，每项使用 `image_url` 或 `image_base64` |
| `title` | string | 否 | 文档标题 |

## 典型流程

- 提取文字：准备图片输入，调用 `ocr.extract`，再整理 `texts`。
- 图片转文档或表格：准备图片，调用 `ocr.toword` 或 `ocr.toexcel`，向用户返回 `file_url`。
- 回填现有文档：先取得 OCR 文本，再按目标类型使用 `smartcanvas.edit`、`doc.insert_markdown` 或 Sheet 写入工具。

OCR 可能消耗积分。超时或结果不确定时不要自动重复调用；只报告服务实际返回的状态。

