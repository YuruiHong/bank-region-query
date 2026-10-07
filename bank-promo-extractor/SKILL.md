---
name: bank-promo-extractor
description: 从支付宝银行卡优惠活动截图中提取优惠信息，结合 bank_region_query 查询银行卡号前缀对应的地区，输出 Excel 表格。当用户提供银行卡优惠活动截图（JPG/PNG），需要提取银行名、地区、门槛、立减金额、次数等信息并生成表格时使用此技能。
---

# 银行卡优惠信息提取

从支付宝银行卡优惠活动截图中自动提取信息，查询地区码，生成 Excel 表格。

## 工作流程

1. 确认图片路径（单张或目录）
2. 运行提取脚本
3. 检查输出结果，必要时手动修正

## 运行脚本

```bash
# 确保依赖已安装
pip install -e /home/hyr/bank-region-query
pip install pytesseract Pillow openpyxl

# 单张图片
python scripts/extract_promo.py /path/to/image.jpg -o result.xlsx

# 目录下所有图片
python scripts/extract_promo.py /path/to/images/ -o result.xlsx
```

脚本位于技能的 `scripts/extract_promo.py`。

## 输出表格列说明

| 列名 | 说明 |
|------|------|
| 银行 | 从截文中识别的银行名称 |
| 地区 | 通过卡号前缀第7位起的地区码查询得到；多个城市属同一省时显示省名 |
| 地区码 | 卡号前缀中第7位起的数字 |
| 门槛记录 | **留空**，供用户手动填写 |
| 立减记录 | **留空**，供用户手动填写 |
| 场景 | 使用场景（如"信用卡还款"），从方括号[xxx]中提取 |
| 精确门槛 | 从截文中提取的门槛金额（如1000.00） |
| 精确立减起点 | 立减金额范围的较小值 |
| 精确立减终点 | 立减金额范围的较大值 |
| 日次数 | 每用户每日次数限制（不含每日名额，找不到则留空） |
| 月次数 | 每用户每月次数限制 |
| 活动期间总次数 | 活动期间每用户总次数限制 |
| 活动期起点 | 活动开始日期 |
| 活动期终点 | 活动结束日期 |
| 备注 | **留空**，供用户手动填写 |

所有字段均为可选，未提取到时留空。

## 地区查询逻辑

1. 从截文中提取银行卡号前缀（如 45635102）
2. 取第7位起的数字作为地区码（如 "02"）
3. 用通配符 `02*` 调用 `bank_region_query` 的 `get_region_by_code()` 查询地区
4. 多个前缀匹配到同一省下不同城市时，自动汇总为省级名称

## 依赖

- `bank_region_query` 包（项目 `/home/hyr/bank-region-query`）
- `pytesseract`、`Pillow`、`openpyxl`
- 系统需安装 `tesseract-ocr` 并包含 `chi_sim` 中文语言包
