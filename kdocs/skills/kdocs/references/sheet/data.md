# 数据操作

## 1. sheet.get_range_data

#### 功能说明

获取指定工作表中某个矩形区域内的单元格数据。行列索引均为 0-based。
请求参数使用 `worksheet_id` 和 `range` 对象。



> 行列索引均为 0-based；读取整张表时先用 sheet.get_sheets_info 获取 range.rowTo / range.colTo 上限
> isCellPic=true 时，单元格为图片；picData（在线文件）和 sha1（本地图片）二选一返回
> originalCellValue 返回公式栏原始值，cellText 返回显示值；fmlaText 仅在含公式时返回

#### 调用示例

读取 A1:F11 区域（前 11 行、前 6 列）：

```json
{
  "file_id": "VsdfG0001234567",
  "worksheet_id": 3,
  "range": {
    "rowFrom": 0,
    "rowTo": 10,
    "colFrom": 0,
    "colTo": 5
  }
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID（路径参数）
- `worksheet_id` (integer, 必填): 工作表 ID
- `range` (object, 必填): 选区范围，行列索引均为 0-based

#### 返回值说明

```json
{
  "result": "ok",
  "detail": {
    "rangeData": [
      {
        "cellText": "test",
        "colFrom": 0,
        "colTo": 0,
        "isCellPic": false,
        "numFormat": "G/通用格式",
        "originalCellValue": "test",
        "rowFrom": 0,
        "rowTo": 0,
        "fmlaText": "=A1"
      },
      {
        "cellText": "111",
        "colFrom": 1,
        "colTo": 1,
        "isCellPic": false,
        "numFormat": "G/通用格式",
        "originalCellValue": "111",
        "rowFrom": 0,
        "rowTo": 0
      },
      {
        "cellText": "332",
        "colFrom": 0,
        "colTo": 0,
        "isCellPic": false,
        "numFormat": "G/通用格式",
        "originalCellValue": "332",
        "rowFrom": 1,
        "rowTo": 1
      },
      {
        "cellText": "=DISPIMG(\"ID_018590616CC643F796F3CB58682DEA85\",1)",
        "colFrom": 1,
        "colTo": 1,
        "isCellPic": true,
        "numFormat": "G/通用格式",
        "originalCellValue": "=DISPIMG(\"ID_018590616CC643F796F3CB58682DEA85\",1)",
        "picData": "MSM5KAQABI",
        "sha1": "6CC643F796F3CB58682DEA85",
        "rowFrom": 1,
        "rowTo": 1,
        "tag": "attachment"
      }
    ]
  }
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `result` | string | 'ok' 表示成功 |
| `detail.rangeData` | array[object] | 单元格数据数组，每项对应选区内一个有数据的单元格 |


---

## 2. sheet.update_range_data

#### 功能说明

批量更新单元格选区数据，支持写值/公式、设置格式、合并单元格、写入图片。
每项操作必须包含 `opType` 和四个坐标字段（`rowFrom`/`rowTo`/`colFrom`/`colTo`）。



#### 操作约束

- **前置检查**：调用 sheet.get_range_data 读取目标区域现有数据，确认覆盖范围
- **提示**：每项必须包含 rowFrom/rowTo/colFrom/colTo 四个坐标；opType 必须使用 formula/format/merge/picture

**重试约束**：不自动重试失败调用；写入结果不确定时先查询实际状态。

> 参数名使用 camelCase（如 `opType`、`rowFrom`、`alcH`、`cellPicInfo`）
> merge 操作的 `type` 使用 `MergeCenter`、`MergeContent`、`MergeSame`、`MergeColumns`
> picture 操作的 `cellPicInfo.tag` 使用 `local` / `attachment` / `url`，并按 tag 传 `uploadId` / `attachmentId` / `url`

#### 调用示例

写入值/公式：

```json
{
  "file_id": "VsdfG0001234567",
  "worksheet_id": 3,
  "rangeData": [
    {
      "opType": "formula",
      "rowFrom": 0,
      "rowTo": 0,
      "colFrom": 0,
      "colTo": 0,
      "formula": "Hello"
    }
  ]
}
```

设置格式（加粗、居中、背景色）：

```json
{
  "file_id": "VsdfG0001234567",
  "worksheet_id": 3,
  "rangeData": [
    {
      "opType": "format",
      "rowFrom": 0,
      "rowTo": 0,
      "colFrom": 0,
      "colTo": 5,
      "xf": {
        "font": {
          "name": "微软雅黑",
          "dyHeight": 220,
          "bls": true,
          "color": {
            "type": 2,
            "value": 16777215
          }
        },
        "alcH": 2,
        "alcV": 1,
        "wrap": true,
        "fill": {
          "type": 1,
          "back": {
            "type": 2,
            "value": 4294901760
          },
          "fore": {
            "type": 255,
            "value": 0,
            "tint": 0
          }
        }
      }
    }
  ]
}
```

合并单元格：

```json
{
  "file_id": "VsdfG0001234567",
  "worksheet_id": 3,
  "rangeData": [
    {
      "opType": "merge",
      "rowFrom": 2,
      "rowTo": 3,
      "colFrom": 0,
      "colTo": 3,
      "type": "MergeCenter"
    }
  ]
}
```

写入在线图片：

```json
{
  "file_id": "VsdfG0001234567",
  "worksheet_id": 3,
  "rangeData": [
    {
      "opType": "picture",
      "rowFrom": 0,
      "rowTo": 0,
      "colFrom": 1,
      "colTo": 1,
      "cellPicInfo": {
        "tag": "url",
        "url": "https://example.com/image.png",
        "width": 200,
        "height": 150
      }
    }
  ]
}
```


#### 参数说明

- `file_id` (string, 必填): 文件 ID（路径参数）
- `worksheet_id` (integer, 必填): 工作表 ID
- `rangeData` (array[object], 必填): 单元格操作数组，每项必须包含 `opType` 和坐标字段，详见 param_detail

**rangeData 每项字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `opType` | string | 是 | 操作类型（枚举值见下表） |
| `rowFrom` | integer | 是 | 起始行（0-based） |
| `rowTo` | integer | 是 | 结束行 |
| `colFrom` | integer | 是 | 起始列（0-based） |
| `colTo` | integer | 是 | 结束列 |
| `formula` | string | 否 | 单元格公式或内容（`opType=formula` 时使用） |
| `xf` | object | 否 | 格式对象（`opType=format` 时使用，见下方 xf 说明） |
| `type` | string | 否 | 合并类型（`opType=merge` 时使用） |
| `cellPicInfo` | object | 否 | 图片信息（`opType=picture` 时使用） |

---

**opType 枚举值：**

| 枚举值 | 说明 | 需要的额外字段 |
|--------|------|--------------|
| `formula` | 写值/公式 | `formula` |
| `format` | 设置格式 | `xf` |
| `merge` | 合并单元格 | `type` |
| `picture` | 写入图片 | `cellPicInfo` |

---

**type 枚举值（opType = merge）：**

| 枚举值 | 说明 |
|--------|------|
| `MergeCenter` | 合并居中 |
| `MergeContent` | 内容合并 |
| `MergeSame` | 相同内容合并 |
| `MergeColumns` | 按列合并 |

---

**cellPicInfo 字段（opType = picture）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `width` | integer | 是 | 图片宽度；`-1` 表示自适应 |
| `height` | integer | 是 | 图片高度；`-1` 表示自适应 |
| `tag` | string | 是 | 图片来源：`local` / `attachment` / `url` 三选一 |
| `uploadId` | string | 否 | 本地文件（`tag=local`）时必填 |
| `attachmentId` | string | 否 | 附件（`tag=attachment`）时必填 |
| `url` | string | 否 | 在线 URL（`tag=url`）时必填 |

---

**xf 字段（opType = format）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alcH` | integer | 否 | 水平对齐：1=左，2=居中，3=右，4=填充，5=两端，6=跨列，7=分散 |
| `alcV` | integer | 否 | 垂直对齐：0=上，1=中，2=下，3=两端，4=分散 |
| `wrap` | boolean | 否 | 自动换行 |
| `shrinkToFit` | boolean | 否 | 缩小字体填充 |
| `locked` | boolean | 否 | 锁定单元格 |
| `hidden` | boolean | 否 | 隐藏公式 |
| `indent` | integer | 否 | 缩进 |
| `readingOrder` | integer | 否 | 文字方向 |
| `trot` | integer | 否 | 文字旋转角度 |
| `numfmt` | string | 否 | 数字格式串，如 `"G/通用格式"`、`"yyyy-mm-dd"`、`"0.00%"` |
| `mask_cats` | integer | 否 | 掩码 |
| `mask_catsFont` | integer | 否 | 掩码字体 |
| `font` | object | 否 | 字体，见下方 font 字段表 |
| `fill` | object | 否 | 填充，见下方 fill 字段表 |
| `dgLeft` | integer | 否 | 左边框线型 |
| `dgRight` | integer | 否 | 右边框线型 |
| `dgTop` | integer | 否 | 上边框线型 |
| `dgBottom` | integer | 否 | 下边框线型 |
| `dgDiagDown` | integer | 否 | 向下斜线边框线型 |
| `dgDiagUp` | integer | 否 | 向上斜线边框线型 |
| `dgInsideHorz` | integer | 否 | 内框横线线型 |
| `dgInsideVert` | integer | 否 | 内框竖线线型 |
| `clrLeft` | object | 否 | 左边框颜色（颜色对象，见下方颜色说明） |
| `clrRight` | object | 否 | 右边框颜色 |
| `clrTop` | object | 否 | 上边框颜色 |
| `clrBottom` | object | 否 | 下边框颜色 |
| `clrDiagDown` | object | 否 | 向下斜线边框颜色 |
| `clrDiagUp` | object | 否 | 向上斜线边框颜色 |
| `clrInsideHorz` | object | 否 | 内框横线颜色 |
| `clrInsideVert` | object | 否 | 内框竖线颜色 |

边框线型枚举：0=无，1=细线，2=中等，3=虚线，4=点线，5=粗线，6=双线，7=细虚线

**xf.font 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 字体名称，如 `"微软雅黑"` |
| `dyHeight` | integer | 否 | 字体高度（单位 Twip，1pt=20Twip，如 11pt=220） |
| `charSet` | integer | 否 | 字符集 |
| `bls` | boolean | 否 | 粗体 |
| `italic` | boolean | 否 | 斜体 |
| `strikeout` | boolean | 否 | 删除线 |
| `uls` | integer | 否 | 下划线类型 |
| `sss` | integer | 否 | 上下标类型 |
| `themeFont` | integer | 否 | 字体类型 |
| `color` | object | 否 | 字体颜色（颜色对象，见下方颜色说明） |

**xf.fill 字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | integer | 是 | 填充类型 |
| `back` | object | 是 | 背景色（颜色对象） |
| `fore` | object | 是 | 前景色（颜色对象） |

**颜色对象（color / clr_* / fill.back / fill.fore）：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | integer | 是 | 颜色类型：0=ICV，1=THEME 主题色，2=ARGB，254=无颜色（背景透明），255=自动色（字体/边框默认） |
| `value` | integer | 是 | ARGB 整数值（type=2 时有效），如纯红 `0xFFFF0000` = `4294901760` |
| `tint` | integer | 是 | 透明度，调节颜色深浅 |


#### 返回值说明

```json
{
  "code": 0,
  "msg": ""
}

```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | integer | 0 表示成功，非 0 表示失败 |
| `msg` | string | 人可阅读的响应信息 |


---

## sheet.delete_range_data

删除指定工作表的单元格选区数据

调用入口：`execute_destructive_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `range_data` | array | 是 | 选区范围数组，每项含 col_from/col_to/row_from/row_to |
| `shift_type` | string | 否 | 移动方式，默认 shift_up；可选 shift_up / shift_left |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `worksheet_id` | number | 是 | 工作表 ID |

## sheet.add_row

在指定工作表中新增行

调用入口：`execute_write_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `range_data` | array | 否 | 新增行数据列表，每项含 op_type(formula/picture) 及对应字段 |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `worksheet_id` | number | 是 | 工作表 ID |

## sheet.find_range_data

查找单元格

调用入口：`execute_read_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_id` | string | 否 | 文件 id；与 url、link_id 三选一 |
| `filter` | object | 是 | 筛选条件 |
| `ignore_hidden_cell` | boolean | 否 | 为true时忽略隐藏的单元格，默认为false |
| `link_id` | string | 否 | 分享 id；与 url、file_id 三选一 |
| `option_cols` | array | 否 | 想获取的选项坐标，相对于range |
| `page` | object | 否 | 分页，可选 |
| `range` | object | 是 | 筛选的区域 |
| `show_total` | boolean | 否 | 是否显示总数 默认为false |
| `url` | string | 否 | 文档 URL；与 link_id、file_id 三选一 |
| `worksheet_id` | number | 是 | 工作表 ID |

## sheet.get_attachment_url

获取附件下载链接。

调用入口：`execute_unknown_tool`。失败不自动重试；完整嵌套参数由 `search_tools` 返回。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `Content-Type` | string | 是 | 文件类型 |
| `content_base64` | string | 否 | 文件内容的 Base64 编码；与 url 二选一 |
| `cover_id` | string | 否 | 封面 ID |
| `file_id` | string | 是 | 智能表格文件 ID |
| `filename` | string | 是 | 附件名 |
| `map_id` | string | 否 | 占位图标识符 |
| `scale` | number | 否 | 缩略图压缩比 |
| `source` | string | 否 | 附件来源，例如：processon |
| `source_type` | string | 否 | 附件来源类型，默认为文件 |
| `url` | string | 否 | 附件 URL；与 content_base64 二选一 |

