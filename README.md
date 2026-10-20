# Bank Region Query

A Python package for querying bank region codes and names.

## Installation

```bash
pip install bank-region-query
```

# Usage

## Bank name matching

Every API/CLI entry point that takes a bank name matches it as a **string**
against each bank's canonical name and 别称 before querying. Nothing is derived
or invented: the 别称 are taken verbatim from `data/bank_aliases.json`, generated
from `balance.xlsx` (sheet 银行缩写) by `scripts/build_bank_aliases.py`.
Comparison ignores whitespace, full-width/half-width and letter case.

- a 别称 (`工行`, `icbc`, `cmb`) must match exactly — treating pinyin
  abbreviations as substrings would collide on shared prefixes (`cmb` ⊂ `cmbc`);
- CJK names additionally match by containment in both directions:
  `农业银行` ⊂ `中国农业银行`, and `中国农业银行北京分行` ⊃ `中国农业银行`.

The number of matching banks then decides:

| matches | result |
| --- | --- |
| exactly 1 | used directly |
| 0 | fail, message asks for a re-query |
| 2–3 | fail in script/API mode; interactive mode shows a menu to pick one |
| > 3 (`MAX_CHOICES`) | fail, message asks for a more specific name |

```python
query.resolve_bank_name("icbc")        # '中国工商银行'
query.resolve_bank_name("建行")         # '建设银行'
query.resolve_bank_name("中信")         # '中信银行'   (containment)
query.resolve_bank_name("cmb")         # '招商银行'
query.resolve_bank_name("平安银行")      # None — matches no bank
query.resolve_bank_name("商银行")        # None — matches 3 banks
query.match_banks("商银行")             # ['中国工商银行', '招商银行', '浙商银行']
query.resolve_bank("商银行").message    # "... Please re-query with one of them: 1. ... 2. ... 3. ..."
query.list_aliases("工行").data        # ['icbc', '工商银行', '工行']
```

One deliberate refusal: an input carrying a parenthesised qualifier is never
matched, because `中国建设银行（亚洲）` is a separate entity rather than a
spelling of `建设银行`. It fails with a re-query message like any non-match.

Regenerate the 别称 table after editing the workbook:

```bash
python scripts/build_bank_aliases.py ~/Documents/balance.xlsx
```

## 补丁机制（patches.txt）

`data/bank_region_codes.json` 是生成文件，不手改；补充或修正条目写进补丁文件
`data/patches.txt`，加载时叠加在 JSON 之上。每行一条三元组，`#` 之后为备注：

```
农行 407 亳州 # 261020点询亳州分行营业部确认
```

- 银行可写规范名或别称（`农行` / `abc`），按上面的匹配规则解析成唯一规范名；
- 地区码按数据约定原样书写（注意补零；支持 `萧山227` 这类带汉字前缀的写法）；
- 地区按书写原样存储；
- `#` 备注只留在补丁文件里，**不进入工具数据与任何输出**（含 `export`）；
- 补丁可以新增映射，也可以覆盖错误映射（覆盖时在 stderr 打警告）；同一地区
  多个码沿用逗号拼接约定（`032,萧山227,999`）。

审计与显式指定补丁文件：

```bash
bank-query list patches                        # 查看已应用的补丁条目（无备注）
bank-query --patch-file /path/to/patches.txt list patches
```

默认查找顺序：自定义数据文件（`-d`）所在目录的 `patches.txt`，否则用包内
`data/patches.txt`。坏行（字段数不是 3）或银行名解析不唯一时，该行跳过并在
stderr 警告，不致命。

## Python API

```python
from bank_region_query import BankRegionQuery

# Initialize
query = BankRegionQuery()

# Get region code by bank and region
result = query.get_region_code("中国农业银行", "北京市")
print(result.data)  # "001"

# Aliases work here too
result = query.get_region_code("农行", "北京市")
print(result.data)  # "001"

# Get region name by bank and code
result = query.get_region_by_code("中国农业银行", "001")
print(result.data)  # "北京市"

# Search by region across all banks
result = query.search_by_region("北京市")
print(result.data)  # {"中国农业银行": "001", ...}

# List all banks
banks = query.list_banks()
print(banks)  # ["中国农业银行", ...]

# Use an explicit patch file instead of the default lookup
query = BankRegionQuery(patch_file="patches.txt")

# List applied patch entries (no '# ...' notes -- those stay in the file)
query.list_patches().data  # [{"bank": "中国农业银行", "code": "407", "region": "亳州"}, ...]

# Get statistics
stats = query.get_statistics()
print(stats)
```

## Command Line Interface

```bash
# Get region code
bank-query code -b "中国农业银行" -r "北京市"
bank-query code -b "农行" -r "北京市"          # 别称

# Resolve a name to the canonical bank name
bank-query resolve -b "icbc"

# List known 别称
bank-query list aliases
bank-query list aliases -b "工行"

# Interactive mode shows a menu when a name matches 2-3 banks
bank-query interactive

# Get region name
bank-query region -b "中国农业银行" -c "001"

# Search by region
bank-query search --region "北京市"

# Search by code
bank-query search --code "001"

# List all banks
bank-query list banks

# List regions for a bank
bank-query list regions -b "中国农业银行"

# List codes for a bank
bank-query list codes -b "中国农业银行"

# List applied patch entries (补丁)
bank-query list patches

# Show statistics
bank-query stats

# Export data
bank-query export -o output.json

# Interactive mode
bank-query interactive

# JSON output (-f is a global option and goes before the subcommand)
bank-query -f json code -b "中国农业银行" -r "北京市"
```

# License

MIT


