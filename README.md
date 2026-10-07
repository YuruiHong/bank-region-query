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

# Show statistics
bank-query stats

# Export data
bank-query export -o output.json

# Interactive mode
bank-query interactive

# JSON output
bank-query code -b "中国农业银行" -r "北京市" -f json
```

# License

MIT


