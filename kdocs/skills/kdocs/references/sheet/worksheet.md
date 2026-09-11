# 工作表管理

## 1. sheet.get_sheets_info

#### 功能说明

获取指定表格文件的所有工作表信息，包含每个工作表的名称、索引、数据区域范围等。



> rowTo/colTo 比 maxRow/maxCol 更有参考价值，表示实际数据区域

#### 调用示例

获取工作表信息：

```json
{
  "file_id": "string"
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID

#### 返回值说明

```json
{
  "sheetsInfo": [
    {
      "isEmpty": false,
      "colFrom": 0,
      "colTo": 5,
      "isVisible": true,
      "maxCol": 16383,
      "maxRow": 1048575,
      "rowFrom": 0,
      "rowTo": 50,
      "sheetId": 3,
      "sheetIdx": 0,
      "sheetName": "Sheet1",
      "sheetType": "et"
    }
  ]
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `sheetsInfo[].sheetId` | integer | 工作表 ID |
| `sheetsInfo[].sheetIdx` | integer | 工作表索引 |
| `sheetsInfo[].sheetName` | string | 工作表名称 |
| `sheetsInfo[].sheetType` | string | 工作表类型（见下表） |
| `sheetsInfo[].isEmpty` | boolean | 是否为空 |
| `sheetsInfo[].isVisible` | boolean | 是否可见 |
| `sheetsInfo[].maxRow` | integer | 最大行数（工作表总容量） |
| `sheetsInfo[].maxCol` | integer | 最大列数 |
| `sheetsInfo[].rowFrom` | integer | 数据区域起始行 |
| `sheetsInfo[].rowTo` | integer | 数据区域结束行（比 `maxRow` 更有参考价值） |
| `sheetsInfo[].colFrom` | integer | 数据区域起始列 |
| `sheetsInfo[].colTo` | integer | 数据区域结束列 |

**sheetType 工作表类型：**

| sheetType | 说明 |
|-----------|------|
| `et` | 普通电子表格 |
| `db` | 数据表 |
| `airApp` | 应用表 |
| `oldDb` | 旧的数据表 |
| `dbDashBoard` | 数据表的仪表盘 |
| `etDashBoard` | 普通表格的仪表盘 |
| `workbench` | 工作台 |


---

## 2. sheet.create_airsheet_file

#### 功能说明

新建一个智能表格（.ksheet）文件。

`.ksheet` 不能通过通用 `create_file` 创建，应改用本工具。



**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

> 创建完成后，可继续使用 `sheet.get_sheets_info`、`sheet.update_range_data` 等 `sheet.*` 工具操作内容

#### 调用示例

创建智能表格：

```json
{
  "type": "ksheet",
  "tname": "项目任务跟踪表.ksheet"
}
```


#### 参数说明

- `type` (string, 可选): 文件类型；默认值：`ksheet`，仅允许 `ksheet`。可选值：`ksheet`
- `tname` (string, 必填): 智能表格文件名，建议带 `.ksheet` 后缀

#### 返回值说明

```json
{
  "id": "airsheet_xxx",
  "name": "项目任务跟踪表.ksheet"
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 新建文件 ID |
| `file_id` | string | 新建文件 ID（部分返回结构可能使用该字段） |
| `name` | string | 文件名 |


---

## 3. sheet.add_sheet

#### 功能说明

在指定表格文件中新增工作表。可指定名称、数量、插入位置和默认列宽。
插入位置通过 `before` / `after` / `end` 三选一控制。



**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

#### 调用示例

在末尾新增工作表：

```json
{
  "file_id": "string",
  "name": "销售数据",
  "end": true,
  "defColWidth": 1335,
  "count": 1
}
```

在指定工作表之后插入：

```json
{
  "file_id": "string",
  "name": "新工作表",
  "after": {
    "sheetId": 3
  }
}
```

在指定工作表之前插入：

```json
{
  "file_id": "string",
  "before": {
    "sheetId": 2
  }
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID（路径参数 `{file_id}`）
- `before` (object, 可选): 插入到指定工作表之前；与 `after`、`end` 三选一
- `after` (object, 可选): 插入到指定工作表之后；与 `before`、`end` 三选一
- `end` (boolean, 可选): 是否插入到末尾；与 `before`、`after` 三选一
- `defColWidth` (integer, 可选): 默认列宽，如 `1335`（约 10.5 个字符）
- `count` (integer, 可选): 新增工作表数量，默认 `1`；默认值：`1`
- `name` (string, 可选): 工作表名，默认 `sheetn`

**Path 参数：**

- `file_id`（string，必填）：文件 ID

**Body（`application/json`）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `before` | object | 否 | 在指定工作表之前插入；与 `after`、`end` 三选一 |
| `after` | object | 否 | 在指定工作表之后插入；与 `before`、`end` 三选一 |
| `end` | boolean | 否 | 是否在末尾插入；与 `before`、`after` 三选一 |
| `defColWidth` | integer | 否 | 默认列宽，如 `1335`（约 10.5 个字符） |
| `count` | integer | 否 | 新增工作表数量，默认 `1` |
| `name` | string | 否 | 工作表名，默认 `sheetn` |

**before / after 对象：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sheetId` | integer | 是 | 目标工作表 ID |


#### 返回值说明

```json
{
  "sheetId": 4
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `sheetId` | integer | 新建的工作表 ID |


---

## sheet.update_sheet

更新工作表属性，如名称、位置等

调用入口：`execute_write_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `move_sheet_id` | number | 否 | 移动需要参照的工作表 ID |
| `move_type` | string | 否 | 移动位置，可选 sheet_move_type_before / sheet_move_type_after |
| `name` | string | 否 | 工作表名称 |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `worksheet_id` | number | 是 | 工作表 ID |

## sheet.delete_sheets

删除工作表

调用入口：`execute_destructive_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `worksheet_ids` | array | 否 | 工作表 ID 列表 |

## 6. sheet.copy_worksheet

#### 功能说明

复制指定工作表。

适用于按模板快速生成副本、保留原始工作表不动的场景。



#### 操作约束

- **后置验证**：get_sheets_info 确认副本已创建

**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

> 可根据是否复制第一个工作表，按需设置 `copy_first_sheet`,若要复制第一个工作表必须带该参数且设置为 true

#### 调用示例

复制指定工作表：

```json
{
  "file_id": "string",
  "worksheet_id": 7
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID
- `worksheet_id` (integer, 必填): 工作表 ID
- `copy_first_sheet` (boolean, 可选): 是否复制第一个工作表,若要复制第一个工作表必须带该参数且设置为 true

#### 返回值说明

```json
{
  "worksheet_id": 9,
  "name": "任务模板 副本"
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `worksheet_id` | integer | 新复制出的工作表 ID |
| `name` | string | 新工作表名称 |


---

## 7. sheet.update_worksheet

#### 功能说明

更新工作表名称或调整工作表顺序位置。

支持重命名工作表，也支持相对于另一张工作表前后移动。



**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

> `name` 与移动参数可单独使用，也可按实际接口能力组合使用

#### 调用示例

重命名工作表：

```json
{
  "file_id": "string",
  "worksheet_id": 7,
  "name": "任务总览"
}
```

将工作表移动到另一张表之后：

```json
{
  "file_id": "string",
  "worksheet_id": 7,
  "move_sheet_id": 3,
  "move_type": "sheet_move_type_after"
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID
- `worksheet_id` (integer, 必填): 工作表 ID
- `name` (string, 可选): 新工作表名称
- `move_sheet_id` (integer, 可选): 参照工作表 ID
- `move_type` (string, 可选): 移动类型：`sheet_move_type_before` / `sheet_move_type_after`

#### 返回值说明

```json
{}

```


---

