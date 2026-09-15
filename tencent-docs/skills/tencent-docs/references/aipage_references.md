# 本地 HTML 一键上云（.aipage 导入）

把本地 HTML 导入腾讯文档时，先用包内 `aipage_pack.js` 打包，再通过 Poco 调用 `tencent-docs` 服务完成预导入和异步导入。

## 标准链路

### 1. 打包为 `.aipage`

`aipage_pack.js` 使用 Node.js 14 及以上版本，零 npm 依赖，只负责本地打包，不读取凭据、不调用 MCP。

```bash
node <skill_dir>/aipage_pack.js --html "<html_path>" [--title "<title>"]
node <skill_dir>/aipage_pack.js --dir "<html_dir>" [--title "<title>"]
```

脚本输出 `AIPAGE_PATH`、`AIPAGE_SIZE`、`AIPAGE_MD5` 和 `AIPAGE_TITLE`。退出码：`0` 成功，`1` 参数错误，`2` 源 HTML 不合法，`3` 打包失败。

### 2. 预导入

通过 Poco 调用 `tencent-docs` 服务的 `manage.pre_import`：

```json
{
  "file_name": "<AIPAGE_PATH 的文件名>",
  "file_size": 123456,
  "file_md5": "<AIPAGE_MD5>"
}
```

保存返回的 `upload_url`、`file_key` 和 `task_id`。不要把签名地址写入对话或长期文件。

### 3. 上传文件

仅向 `manage.pre_import` 返回的签名地址上传本次文件：

```bash
curl --fail-with-body -X PUT \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@<AIPAGE_PATH>" \
  "<upload_url>"
```

只有 HTTP 2xx 才视为上传成功。此请求不是 MCP 调用，不应携带腾讯文档 Token。

### 4. 触发并查询导入

通过 Poco 调用 `manage.async_import`：

```json
{
  "task_id": "<task_id>",
  "file_key": "<file_key>",
  "file_name": "<file_name>",
  "file_md5": "<AIPAGE_MD5>",
  "file_size": 123456
}
```

随后调用 `manage.import_progress` 查询同一 `task_id`。只在服务返回完成状态后报告成功，并使用返回的 `file_id` 和 `file_url`。

## 约束

- HTML 必须使用 `aipage_pack.js` 打包，不自行重建 manifest 或 ZIP 结构。
- `manage.pre_import`、文件上传和 `manage.async_import` 都禁止自动重试。超时或结果不确定时，先查询任务或文件状态。
- 上传失败时不要继续调用 `manage.async_import`。
- 不把 Token 写入命令、环境变量、脚本或工作区文件。
- 不把签名上传地址、base64 内容或临时下载地址展示给用户。

