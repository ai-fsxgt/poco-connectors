# 记录操作

## dbsheet.create_records

在指定数据表中批量创建记录，通过字段名称或字段 ID 指定各字段的值。调用前必须先通过 get_schema 确认字段名和字段类型。

调用入口：`execute_write_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `add_select_item` | boolean | 否 | 是否自动新增不存在的选项，默认 true |
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `link_value` | string | 否 | 关联字段值格式：id / all |
| `omit_failure` | boolean | 否 | 部分记录创建失败时是否继续 |
| `prefer_id` | boolean | 否 | 是否使用字段 ID 作为 key，默认 false（使用字段名） |
| `records` | array | 是 | 要创建的记录列表，每项含 fields 对象 |
| `sheet_id` | number | 是 | 目标数据表 ID |
| `text_value` | string | 否 | 文本值格式：original / text / compound |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `value_prefer_id` | boolean | 否 | 字段值是否使用 ID 表示 |

## dbsheet.update_records

批量更新数据表中已有记录的字段值，每条记录必须提供记录 ID。

调用入口：`execute_write_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `add_select_item` | boolean | 否 | 是否自动新增不存在的选项 |
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `link_value` | string | 否 | 关联字段值格式：id / value |
| `omit_failure` | boolean | 否 | 部分记录更新失败时是否继续 |
| `prefer_id` | boolean | 否 | 是否使用字段 ID 作为 key |
| `records` | array | 是 | 要更新的记录列表，每项须含 id 和 fields |
| `sheet_id` | number | 是 | 目标数据表 ID |
| `text_value` | string | 否 | 文本值格式：original / display |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `value_prefer_id` | boolean | 否 | 字段值是否使用 ID 表示 |

## 3. dbsheet.list_records

#### 功能说明

分页遍历数据表中的记录，支持按视图过滤、指定返回字段，以及通过 `filter` 参数实现复杂查询条件（多字段 AND/OR 组合筛选）。



#### 调用示例

基础分页查询：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "page_size": 100,
  "offset": "",
  "fields": [
    "名称",
    "状态",
    "截止日期"
  ]
}
```

带筛选条件查询：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "page_size": 100,
  "offset": "",
  "filter": {
    "mode": "AND",
    "criteria": [
      {
        "field": "状态",
        "op": "Intersected",
        "values": [
          "进行中"
        ]
      },
      {
        "field": "数量",
        "op": "Greater",
        "values": [
          "10"
        ]
      },
      {
        "field": "名称",
        "op": "Contains",
        "values": [
          "关键词"
        ]
      }
    ]
  }
}
```


#### 参数说明

- `file_id` (string, 必填): 多维表格文件 ID
- `sheet_id` (integer, 必填): 目标数据表 ID
- `page_size` (integer, 可选): 每页记录数
- `offset` (string, 可选): 翻页游标，首次请求传空字符串，后续传响应中的 `offset` 值
- `view_id` (string, 可选): 按指定视图返回记录
- `max_records` (integer, 可选): 最多返回的记录总数
- `fields` (array, 可选): 只返回指定字段列表，不填则返回所有字段
- `filter` (object, 可选): 筛选条件，含 mode 和 criteria 列表
  - `mode` (string, 必填): 条件连接方式：`"AND"` 或 `"OR"`
  - `criteria` (array, 必填): 筛选条件列表
    - `field` (string, 必填): 字段名称或 ID
    - `op` (string, 必填): 筛选操作符（见附录：筛选规则）
    - `values` (array, 可选): 筛选值，`Empty`/`NotEmpty` 时可省略
- `prefer_id` (boolean, 可选): 是否使用字段 ID 作为 key
- `text_value` (string, 可选): 文本值格式：`"original"`（原始值）或 `"display"`（显示值）
- `link_value` (string, 可选): 关联字段值格式：`"id"` 或 `"value"`
- `show_record_extra_info` (boolean, 可选): 是否返回记录额外信息
- `show_fields_info` (boolean, 可选): 是否在响应中返回字段定义信息

> **分页说明**：响应中的 `offset` 指向下一页第一条记录，下次请求将该值传入 `offset` 即可翻页。最后一页不再返回 `offset`。


#### 返回值说明

```json
{
  "detail": {
    "offset": "D",
    "records": [
      { "id": "E", "fields": { "名称": "任务A", "状态": "进行中", "数量": 15 } },
      { "id": "F", "fields": { "名称": "任务B", "状态": "进行中", "数量": 20 } }
    ]
  },
  "result": "ok"
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `detail.offset` | string | 下一页游标，无更多数据时不返回此字段 |
| `detail.records[].id` | string | 记录 ID |
| `detail.records[].fields` | object | 各字段的值 |
| `result` | string | ok 表示成功 |


---

## 4. dbsheet.get_record

#### 功能说明

获取数据表中某条指定记录的完整字段内容。


#### 调用示例

获取单条记录：

```json
{
  "file_id": "string",
  "sheet_id": 3,
  "record_id": "B"
}
```


#### 参数说明

- `file_id` (string, 必填): 多维表格文件 ID
- `sheet_id` (integer, 必填): 目标数据表 ID
- `record_id` (string, 必填): 记录 ID
- `prefer_id` (boolean, 可选): 是否使用字段 ID 作为 key
- `text_value` (string, 可选): 文本值格式：`"original"`（原始值）或 `"display"`（显示值）
- `link_value` (string, 可选): 关联字段值格式：`"id"` 或 `"value"`
- `show_record_extra_info` (boolean, 可选): 是否返回记录额外信息
- `show_fields_info` (boolean, 可选): 是否返回字段定义信息

#### 返回值说明

```json
{
  "detail": {
    "id": "B",
    "fields": {
      "名称": "任务A",
      "数量": 123,
      "日期": "2021/5/1",
      "状态": "未开始"
    }
  },
  "result": "ok"
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `detail.id` | string | 记录 ID |
| `detail.fields` | object | 各字段的值 |
| `result` | string | ok 表示成功 |


---

## 5. dbsheet.delete_records

#### 功能说明

批量删除数据表中的指定记录。`records` 为记录 ID 的对象数组，**不是字符串数组**。



#### 操作约束

- **前置检查**：调用 list_records 或 get_record 核对拟删记录的内容，确认记录 ID 正确
- **用户确认**：批量删除记录不可恢复，必须向用户确认记录列表和数量

**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

> `records` 是对象数组（记录 ID），**不是**字符串数组；不应该传 `["G"]` 等字符串格式，而应该传 `[{"id":"G"}]` 等对象格式

#### 调用示例

批量删除记录：

```json
{
  "file_id": "VsdfG0001234567",
  "sheet_id": 3,
  "records": [
    {
      "id": "G"
    },
    {
      "id": "H"
    }
  ]
}
```


#### 参数说明

- `file_id` (string, 必填): 多维表格文件 ID（路径参数）
- `sheet_id` (integer, 必填): 数据表 ID
- `records` (array[string], 必填): 要删除的记录 ID 列表（对象数组，每项为一个记录 ID）

**请求体结构：**

| 字段 | 类型 | 是否必填 | 说明 |
|------|------|----------|------|
| `records` | array[object] | 是 | 记录 ID 对象数组，每个元素为一条记录的 ID |

**请求体示例：**

```json
{
  "records": [
    { "id": "G" },
    { "id": "H" },
    { "id": "I" }
  ]
}
```

> 记录 ID 可通过 `dbsheet.list_records` 或 `dbsheet.get_record` 获取。


#### 返回值说明

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "records": [
      { "id": "G", "deleted": true },
      { "id": "H", "deleted": true }
    ]
  }
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 响应代码，0 表示成功，非 0 表示失败 |
| `msg` | string | 响应信息 |
| `data.records` | array[object] | 删除结果列表 |
| `more` | object | 更多错误信息（失败时返回） |


---

## 6. dbsheet.records_list

#### 功能说明


**请求体（均在 JSON 内，无 URL query）**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| fields | array[string] | 是* | 指定返回记录中的字段；*文档写必填，若不填则默认返回全部字段。`prefer_id=true` 时填字段 id，否则填字段名 |
| filter | object | 否 | 筛选条件 |
| filter.criteria | array[object] | 条件内必填 | 条件数组，每项含 `field`（字段名/id）、`op`（操作符，如 Contains / Equal / Empty 等）、`values`（筛选值，Empty/NotEmpty 时可省略） |
| max_records | integer | 否 | 最多取前 max_records 条；不填则不限 |
| page_size | integer | 否 | 每页大小，默认 100，范围 1–1000 |
| page_token | string | 否 | 分页游标；有下一页时用上次的 page_token |
| prefer_id | boolean | 否 | 为 true 时 fields 等按字段 id 解析 |
| show_fields_info | boolean | 否 | 是否额外返回字段元信息（类似 Schema fields） |
| show_record_extra_info | boolean | 否 | 是否返回创建者、创建时间、最后修改者、最后修改时间等 |
| text_value | string | 否 | 不填默认 original；可选 original、text、compound |
| view_id | string | 否 | 指定视图则从该视图取用户可见记录；不填从工作表取 |



> filter.criteria 的结构需符合多维表格接口对筛选条件的约定。

#### 调用示例

最简：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "body": {}
}
```

返回文本值并携带额外信息：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "prefer_id": false,
  "show_fields_info": false,
  "text_value": "text",
  "show_record_extra_info": true
}
```

分页与视图：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "view_id": "B",
  "page_size": 50,
  "page_token": ""
}
```


#### 参数说明

- `file_id` (string, 必填): 多维表格文件 ID
- `sheet_id` (integer, 必填): 数据表 ID
- `body` (object, 可选): 可选整包请求体；与顶层字段混用时同键以顶层为准
- `fields` (array, 必填): 指定所返回记录中的字段信息，若不填写则默认返回全部字段。prefer_id=true 时须用字段 id，否则用字段名
- `filter` (object, 可选): 筛选条件
  - `mode` (string, 必填): 条件连接方式：`"AND"` 或 `"OR"`
  - `criteria` (array, 必填): 筛选条件列表，每项包含：
    - `field` (string, 必填): 字段名称或字段 id（由 prefer_id 决定）
    - `op` (string, 必填): 筛选操作符，见多维表格参数说明（如 `Contains`、`Intersected`、`Greater`、`Less`、`Equal`、`Empty`、`NotEmpty` 等）
    - `values` (array, 可选): 筛选值；`Empty` / `NotEmpty` 操作符时可省略
- `max_records` (integer, 可选): 最多返回前 max_records 条，若不填写则默认返回全部记录
- `page_size` (integer, 可选): 分页获取记录时的每页大小，默认 100，取值范围 1-1000
- `page_token` (string, 可选): 分页起始位置。当存在分页且未查询到最后一页或 max_records 记录时，返回值会包含 page_token
- `prefer_id` (boolean, 可选): 使用 id 来标识字段和选项。为 true 时，参数内全部的 field、fields 参数均按照 id 做解析
- `show_fields_info` (boolean, 可选): 是否返回一个 fields 结构体，展示字段信息（类似 Base Schema 中的 fields）
- `show_record_extra_info` (boolean, 可选): 是否返回创建者、创建时间、最后修改者、最后修改时间信息（与是否有对应字段无关）
- `text_value` (string, 可选): 返回值类型，不填默认为 original。可选：original（原始值）、text（文本值）、compound（原始值和文本值）
- `view_id` (string, 可选): 指定视图 id。填写后从该视图获取用户所见记录；不填则从工作表获取记录

所有列举参数均在 **POST JSON 请求体** 中，不拼 URL query。

若同时传 `body` 与顶层字段，同键以 **顶层** 为准。


#### 返回值说明

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "fields_schema": [
      {
        "name": "文本",
        "type": "MultiLineText",
        "id": "B",
        "data": { "unique_value": false }
      },
      {
        "name": "数字",
        "type": "Number",
        "id": "C",
        "data": { "number_format": "0.00_ " }
      }
    ],
    "records": [
      {
        "fields": "{\"单选项\":\"选项1\",\"数字\":\"123.00 \",\"文本\":\"第一行文本\",\"日期\":\"2024/12/20\",\"等级\":\"1\"}",
        "id": "B",
        "created_time": "2024/12/20 11:30:32",
        "creator": "280026893",
        "last_modified_by": "280026893",
        "last_modified_time": "2024/12/20 15:47:01"
      }
    ],
    "page_token": ""
  }
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 响应代码，非 0 表示失败 |
| `msg` | string | 响应信息 |
| `data` | object | 响应数据 |
| `more` | object | 更多的错误信息 |


---

## 7. dbsheet.records_search

#### 功能说明


**请求体（均在 JSON 内，无 URL query）**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| records | array[string] | 是 | 记录 id 列表 |
| prefer_id | boolean | 否 | 是否使用字段 / 选项 id 而不是字段 / 选项名来标识 |
| show_fields_info | boolean | 否 | 为 true 时额外返回 fields 结构体展示字段信息；返回范围取决于是否指定 fields 或 view_id |
| show_record_extra_info | boolean | 否 | 为 true 时额外显示创建者、创建时间、最后修改者、最后修改时间（与是否有对应字段无关） |
| text_value | string | 否 | 返回值类型，不填默认 original；可选 original、text、compound |



> records 为必填参数，需传入有效的记录 id 列表。
> records_search 在 MCP 层若要求 filter 为必填参数，传空条件 {"mode":"AND","criteria":[]} 即可满足

#### 调用示例

按记录 id 批量检索：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "records": [
    "B",
    "C"
  ]
}
```

返回文本值并携带额外信息：

```json
{
  "file_id": "string",
  "sheet_id": 1,
  "records": [
    "B",
    "C"
  ],
  "prefer_id": false,
  "show_fields_info": false,
  "text_value": "text",
  "show_record_extra_info": true
}
```


#### 参数说明

- `file_id` (string, 必填): 多维表格文件 ID
- `sheet_id` (integer, 必填): 数据表 ID
- `body` (object, 可选): 可选整包请求体；与顶层字段混用时同键以顶层为准
- `records` (array, 必填): 记录 ID 列表，指定要检索的记录
- `prefer_id` (boolean, 可选): 是否使用字段 / 选项 ID 而不是字段 / 选项名来标识
- `show_fields_info` (boolean, 可选): 是否返回 fields 结构体展示字段信息。为 true 时，若指定了 fields 则返回指定字段；未指定 fields 时，根据是否指定 view_id 决定返回视图可见字段或全部字段
- `show_record_extra_info` (boolean, 可选): 是否返回创建者、创建时间、最后修改者、最后修改时间信息（与是否有对应字段无关）
- `text_value` (string, 可选): 返回值类型，不填默认为 original。可选：original（原始值）、text（文本值）、compound（原始值和文本值）

#### 返回值说明

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "records": [
      {
        "fields": "{\"单选项\":\"选项1\",\"图片和附件\":\"12KB.docx,aigc\",\"数字\":\"123.00 \",\"文本\":\"第一行文本\",\"日期\":\"2024/12/20\",\"等级\":\"1\"}",
        "id": "B"
      },
      {
        "fields": "{\"单选项\":\"选项2\",\"图片和附件\":\"14.4KB.png\",\"数字\":\"321.00 \",\"文本\":\"第二行文本\",\"日期\":\"2024/12/21\",\"等级\":\"2\"}",
        "id": "C"
      }
    ]
  }
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 响应代码，非 0 表示失败 |
| `msg` | string | 响应信息 |
| `data` | object | 响应数据 |
| `more` | object | 更多的错误信息 |


---

