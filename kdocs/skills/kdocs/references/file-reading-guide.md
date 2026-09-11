# 文件读取指南

不同文件类型对应不同读取工具。先判断类型再调用工具，可避免空结果和结构丢失。

#### 读取流程

1. **定位文件**：先用 `search_files` / `get_file_info` 获取 `file_id`、`drive_id` 和文件后缀。  
2. **查看文件后缀**：按后缀确认文档类型，禁止 `search_files` 后直接批量调用 `read_file_content`。  
3. **按后缀选择读取工具**：使用下方“类型映射表”的首选路径。  
4. **检查任务状态**：仅在服务端返回运行中状态时，继续查询已有任务。

#### 类型映射表（唯一主表）

| 文件类型 | 首选读取路径 | `read_file_content` 使用策略 |
|---|---|---|
| `.docx`（wps）/ `.pdf` | `read_file_content` | 默认可用 |
| `.otl`（ap） | `otl.block_query`（优先分块） | 仅在导出 Markdown 时使用 |
| `.xlsx`（et）/ `.ksheet`（as） | `sheet.get_sheets_info` + `sheet.get_range_data` | 禁止 |
| `.dbt`（db） | `dbsheet.get_schema` + `dbsheet.list_records` / `dbsheet.get_record` | 禁止 |
| `.csv` | `read_file` | 使用 `read_file` |

#### 任务状态与调用风险

`read_file` 和 `read_file_content` 均有上传附件能力，按目录走敏感写入入口。只需文字时明确传 `enable_upload_medias=false`。

首次调用不传 `task_id`。仅在返回 `task_status=running` 和任务 ID 后，按服务端指示携带该 ID 查询；返回成功或失败即停止。禁止无限轮询或自动重新提交任务。

#### 特殊类型说明

**智能文档**（.otl / ap）——优先用 `otl.block_query`：

`otl.block_query`（`blockIds: ["doc"]`）可完整获取文档的块结构与内容。`read_file_content` 对 otl 存在内容遗漏风险，仅在需要导出 Markdown 时使用。

**文字文档 / PDF**（.docx / wps、.pdf）——用 `read_file_content`：

返回内容已自动转为 Markdown，可直接用于 AI 分析（摘要、审查、问答等）。

**表格类**（.xlsx / et、.ksheet / as）——**勿用 `read_file_content`**：

1. `sheet.get_sheets_info` 获取工作表列表和结构
2. `sheet.get_range_data` 按范围读取单元格数据

**多维表格**（.dbt / db）——**勿用 `read_file_content`**：

1. `dbsheet.get_schema` 获取数据表、字段、视图结构
2. `dbsheet.list_records` / `dbsheet.get_record` 读取记录

**CSV 文件**：使用 `read_file`，支持 Markdown 或结构化内容；不要先转换文件。

#### 注意事项

- **PDF 精度**：复杂排版（表格、图片、多栏）可能存在精度损失，提取结果为近似纯文本
- **空读取排查**：若 `read_file_content` 返回空内容，检查：(1) 文件是否为空文件 (2) 文件格式是否受支持 (3) 文件后缀与实际格式是否匹配
