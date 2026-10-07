#!/usr/bin/env python3
"""
银行卡优惠活动信息提取脚本

从支付宝银行卡优惠活动截图中提取优惠信息，
结合 bank_region_query 查询地区码，输出 Excel 表格。

用法:
    python extract_promo.py <图片或目录路径> [-o 输出文件.xlsx]

依赖:
    - bank_region_query (pip install -e /path/to/bank-region-query)
    - openpyxl, requests
"""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import openpyxl
import requests
from openpyxl.styles import Font, Alignment, Border, Side

# bank_region_query 包路径（支持从项目根目录直接导入）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bank_region_query.core import BankRegionQuery


# ─── 百度智能云 OCR ────────────────────────────────────────────────────────────

# 百度智能云 API 凭证
BAIDU_API_KEY = "S00kRWoZ8AsI9flNe21RNTXL"
BAIDU_SECRET_KEY = "IEB4YZOuj718TzD06NDYzLS0geDt2V2W"

_access_token = None


def get_baidu_token() -> str:
    """获取百度智能云 Access Token（带缓存）"""
    global _access_token
    if _access_token:
        return _access_token
    resp = requests.get(
        "https://aip.baidubce.com/oauth/2.0/token",
        params={
            "grant_type": "client_credentials",
            "client_id": BAIDU_API_KEY,
            "client_secret": BAIDU_SECRET_KEY,
        },
    )
    resp.raise_for_status()
    _access_token = resp.json()["access_token"]
    return _access_token


def ocr_image(image_path: str) -> str:
    """使用百度智能云 OCR 高精度接口识别图片，返回拼接文本"""
    token = get_baidu_token()
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    resp = requests.post(
        "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic",
        params={"access_token": token},
        data={"image": img_b64},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    result = resp.json()

    if "error_code" in result:
        raise RuntimeError(f"百度 OCR 错误 {result['error_code']}: {result.get('error_msg', '')}")

    lines = [item["words"] for item in result.get("words_result", [])]
    return "\n".join(lines)


# ─── 信息提取 ──────────────────────────────────────────────────────────────────

# 已知银行名称列表（用于模糊匹配）
KNOWN_BANKS = [
    "中国工商银行", "中国农业银行", "中国银行", "中国建设银行",
    "交通银行", "招商银行", "中信银行", "浦发银行",
    "中国民生银行", "兴业银行", "光大银行", "华夏银行",
    "平安银行", "广发银行", "渤海银行", "浙商银行",
    "中国邮政储蓄银行",
    # 简称映射
    "工商银行", "农业银行", "建设银行", "邮储银行",
]


def extract_bank_name(text: str, query: BankRegionQuery) -> str | None:
    """从 OCR 文本中提取银行名称，模糊匹配数据库"""
    # 尝试先匹配数据库中的银行
    for bank in query.list_banks():
        if bank in text:
            return bank

    # 数据库中没有的银行：从文本中提取"XX银行储蓄卡"模式
    match = re.search(r'([\u4e00-\u9fa5]{2,6})银行储蓄卡', text)
    if match:
        return match.group(1) + "银行"
    # 回退：匹配"XX银行"但排除"活动银行"等无关词
    match = re.search(r'(?<![活参])\b([\u4e00-\u9fa5]{2,6})银行', text)
    if match:
        candidate = match.group(1) + "银行"
        if candidate not in ("活动银行", "指定银行", "其他银行", "联名银行"):
            return candidate

    # 尝试简称匹配
    short_to_full = {
        "工商银行": "中国工商银行",
        "农业银行": "中国农业银行",
        "建设银行": "建设银行",
        "中国建设银行": "建设银行",
        "交通银行": "交通银行",
        "招商银行": "招商银行",
        "中信银行": "中信银行",
        "浦发银行": "浦发银行",
        "民生银行": "中国民生银行",
        "兴业银行": "兴业银行",
        "光大银行": "中国光大银行",
        "华夏银行": "华夏银行",
        "平安银行": "平安银行",
        "广发银行": "广发银行",
        "渤海银行": "渤海银行",
        "浙商银行": "浙商银行",
        "邮储银行": "中国邮政储蓄银行",
    }
    for short, full in short_to_full.items():
        if short in text:
            # 验证全称是否在数据库中
            if full in query.list_banks():
                return full
            # 直接用简称尝试
            result = query.list_banks()
            for bank in result:
                if short in bank or bank in short:
                    return bank

    # 最后尝试：从数据库中的银行名逐一检查子串匹配
    for bank in query.list_banks():
        # 取银行名的核心部分（去掉"中国"前缀）
        core = bank.replace("中国", "")
        if core in text:
            return bank

    return None


def extract_card_prefixes(text: str) -> list[str]:
    """从 OCR 文本中提取银行卡号前缀列表"""
    prefixes = []

    # 模式1: 冒号后跟逗号分隔的数字前缀
    # 如: "银行卡号需要为以下开头...: 45635102, 60138202, 62166302"
    pattern1 = r'(?:开头|前缀|卡号)[：:\s]*([\d,\s，、\.]{10,})'
    match = re.search(pattern1, text)
    if match:
        block = match.group(1)
        # 提取所有连续的数字串（6-8位）
        found = re.findall(r'\b(\d{6,12})\b', block)
        prefixes.extend(found)
        if prefixes:
            return prefixes

    # 模式2: 直接找冒号后紧跟的数字序列
    pattern2 = r'[：:]\s*((?:\d{6,12}[\s,，、]*)+)'
    matches = re.findall(pattern2, text)
    for m in matches:
        found = re.findall(r'\b(\d{6,12})\b', m)
        prefixes.extend(found)
    if prefixes:
        return prefixes

    # 模式3: 在文本中找连续的8位数字序列（可能是卡号前缀）
    found = re.findall(r'\b(\d{8})\b', text)
    # 过滤：至少出现2次相同长度的数字（通常是多个前缀）
    if len(found) >= 2:
        return found

    return prefixes


def extract_threshold(text: str) -> float | None:
    """提取门槛金额（满X元）"""
    # 去除换行，处理跨行文本
    flat = re.sub(r'\s+', ' ', text)
    patterns = [
        r'满\s*(\d+\.?\d*)\s*元',
        r'实付满\s*(\d+\.?\d*)\s*元',
        r'单笔.*?满\s*(\d+\.?\d*)\s*元',
        r'满\s*(\d+\.?\d*)[元块钱]',
        r'门槛[为是：:]*\s*(\d+\.?\d*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, flat)
        if match:
            return float(match.group(1))
    return None


def extract_discount(text: str) -> tuple[float | None, float | None]:
    """提取立减金额范围，返回 (起点, 终点)"""
    flat = re.sub(r'\s+', ' ', text)
    patterns = [
        # 随机减1.60~2.40元
        r'(?:随机)?减\s*(\d+\.?\d*)\s*[~～至—-]\s*(\d+\.?\d*)\s*元',
        # 减1.60-2.40元
        r'减\s*(\d+\.?\d*)\s*[-~～]\s*(\d+\.?\d*)\s*元',
        # 立减X元
        r'立减\s*(\d+\.?\d*)\s*元',
        # 减X元（单值）
        r'(?:优惠|减)\s*(\d+\.?\d*)\s*元',
    ]
    for pattern in patterns:
        match = re.search(pattern, flat)
        if match:
            groups = match.groups()
            if len(groups) == 2 and groups[1] is not None:
                start = float(groups[0])
                end = float(groups[1])
                return (min(start, end), max(start, end))
            elif groups[0] is not None:
                val = float(groups[0])
                return (val, val)
    return (None, None)


def extract_daily_limit(text: str) -> int | None:
    """提取每用户每日次数限制（不含每天名额）"""
    flat = re.sub(r'\s+', ' ', text)
    patterns = [
        r'每自然日\s*[至到]\s*多\s*(?:可\s*)?(?:享受\s*)?(\d+)\s*次',
        r'每天\s*[至到]\s*多\s*(?:可\s*)?(?:享受\s*)?(\d+)\s*次',
        r'每日\s*[至到]\s*多\s*(?:可\s*)?(?:享受\s*)?(\d+)\s*次',
        r'每自然日\s*限\s*(\d+)\s*次',
        r'每天\s*限\s*(\d+)\s*次',
        r'每日\s*限\s*(\d+)\s*次',
    ]
    for pattern in patterns:
        match = re.search(pattern, flat)
        if match:
            return int(match.group(1))
    return None


def extract_monthly_limit(text: str) -> int | None:
    """提取每用户每月次数限制"""
    flat = re.sub(r'\s+', ' ', text)
    patterns = [
        r'每自然月\s*[至到]\s*多\s*(\d+)\s*次',
        r'每月\s*[至到]\s*多\s*(\d+)\s*次',
        r'每自然月\s*限\s*(\d+)\s*次',
        r'每月\s*限\s*(\d+)\s*次',
    ]
    for pattern in patterns:
        match = re.search(pattern, flat)
        if match:
            return int(match.group(1))
    return None


def extract_total_limit(text: str) -> int | None:
    """提取活动期间每用户总次数限制"""
    flat = re.sub(r'\s+', ' ', text)
    patterns = [
        r'活动期间\s*[至到]\s*多\s*(?:可)?\s*享受\s*(\d+)\s*次',
        r'活动期[内间]\s*[至到]\s*多\s*(?:可)?\s*享受\s*(\d+)\s*次',
        r'同一用户.*?活动期间.*?(\d+)\s*次',
    ]
    for pattern in patterns:
        match = re.search(pattern, flat)
        if match:
            return int(match.group(1))
    return None


def extract_scene(text: str) -> str | None:
    """提取使用场景（通常在方括号中，如[信用卡还款]）"""
    flat = re.sub(r'\s+', ' ', text)
    # 匹配 [xxx] 或 【xxx】 中的场景名
    match = re.search(r'[\[【](.*?)[\]】]', flat)
    if match:
        scene = match.group(1).strip()
        # 去除内部空格（OCR 可能插入空格，如 "信用卡还 款" -> "信用卡还款"）
        scene = re.sub(r'\s+', '', scene)
        if scene and len(scene) >= 2 and not re.match(r'^\d+$', scene):
            return scene
    return None


def extract_period(text: str) -> tuple[str | None, str | None]:
    """
    提取活动期间，返回 (起点, 终点) 日期时间字符串。
    匹配如 "2026年04月03日 17:59:32-2026年06月30日 23:59:59" 或 "2026.04.03-2026.06.30"
    """
    flat = re.sub(r'\s+', ' ', text)

    # 模式1: YYYY年MM月DD日 HH:MM:SS ... - YYYY年MM月DD日 HH:MM:SS（兼容全角冒号）
    pattern1 = r'(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}[：:]\d{2}[：:]\d{2})[-—~～]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}[：:]\d{2}[：:]\d{2})'
    match = re.search(pattern1, flat)
    if match:
        start = re.sub(r'\s+', '', match.group(1))
        end = re.sub(r'\s+', '', match.group(2))
        return (start, end)

    # 模式2: YYYY年MM月DD日 ... - YYYY年MM月DD日（无时间）
    pattern2 = r'(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)[^-—~～]*?[-—~～]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)'
    match = re.search(pattern2, flat)
    if match:
        start = re.sub(r'\s+', '', match.group(1))
        end = re.sub(r'\s+', '', match.group(2))
        return (start, end)

    # 模式3: YYYY.MM.DD - YYYY.MM.DD
    pattern3 = r'(\d{4}[./-]\d{1,2}[./-]\d{1,2})\s*[-—~～]\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2})'
    match = re.search(pattern3, flat)
    if match:
        return (match.group(1), match.group(2))

    return (None, None)


# ─── 地区查询 ──────────────────────────────────────────────────────────────────

def get_region_from_prefix(query: BankRegionQuery, bank_name: str,
                           prefix: str) -> list[str]:
    """根据卡号前缀查询对应的地区名称列表"""
    if len(prefix) < 7:
        return []
    code = prefix[6:]  # 第7位起
    if not code:
        return []

    result = query.get_region_by_code(bank_name, code + "*")
    if not result.success:
        return []

    if isinstance(result.data, str):
        return [result.data]
    elif isinstance(result.data, list):
        regions = []
        for item in result.data:
            if isinstance(item, dict) and 'region' in item:
                regions.append(item['region'])
        return regions
    return []


def summarize_regions(query: BankRegionQuery, bank_name: str,
                      all_regions: list[str]) -> str:
    """
    将匹配到的多个地区汇总为一个名称。
    - 如果只有一个地区 → 直接返回
    - 如果多个地区属于同一省 → 返回省名
    - 否则 → 用"/"连接
    """
    if not all_regions:
        return "未知"
    if len(all_regions) == 1:
        return all_regions[0]

    unique_regions = list(set(all_regions))

    # 检查是否所有地区都相同
    if len(unique_regions) == 1:
        return unique_regions[0]

    # 检查是否属于同一省
    # 从数据库中查找该银行的省级条目
    import json
    from pathlib import Path as P
    data_path = P(query.__init__.__code__.co_consts[1]) if False else None

    # 直接读取数据
    data_file = Path(__file__).resolve().parent.parent.parent / "bank_region_query" / "data" / "bank_region_codes.json"
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        # 回退：无法判断省份，直接拼接
        return "/".join(sorted(set(unique_regions)))

    bank_data = data.get(bank_name, {})
    region_to_code = bank_data.get("region_to_code", {})

    # 找出所有省级条目
    provinces = []
    for region_name in region_to_code:
        if ('省' in region_name or '自治区' in region_name) and '市' not in region_name:
            provinces.append(region_name)

    # 对每个省，检查匹配到的地区是否都属于该省
    # 方法：检查省级地区码对应的城市是否包含所有匹配到的城市
    # 更简单的方法：检查所有匹配到的城市是否都在某个省的 region_to_code 下
    for province in provinces:
        province_code = region_to_code[province]
        # 省级地区码可能有多个（如 "1300,6200"）
        codes = [c.strip() for c in province_code.split(',')]

        # 找出该省下的所有城市
        province_cities = set()
        for city, city_code in region_to_code.items():
            if city == province:
                continue
            # 检查城市码是否以省级码开头
            for code in codes:
                if city_code.startswith(code) or city_code == code:
                    province_cities.add(city)

        # 检查所有匹配到的地区是否都在该省的城市列表中
        if all(r in province_cities for r in unique_regions):
            return province

    # 无法归到同一省，拼接
    return "/".join(sorted(set(unique_regions)))


def get_region_code_from_prefix(prefix: str) -> str:
    """从卡号前缀提取地区码（第7位起的数字）"""
    if len(prefix) >= 7:
        return prefix[6:]
    return ""


# ─── Excel 输出 ────────────────────────────────────────────────────────────────

HEADERS = [
    "银行", "地区", "地区码", "门槛记录", "立减记录",
    "场景", "精确门槛", "精确立减起点", "精确立减终点",
    "日次数", "月次数", "活动期间总次数",
    "活动期起点", "活动期终点", "备注",
]


def create_excel(records: list[dict], output_path: str):
    """创建 Excel 表格"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "银行卡优惠信息"

    # 写表头
    header_font = Font(bold=True, size=11)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border

    # 写数据
    for row_idx, record in enumerate(records, 2):
        for col, header in enumerate(HEADERS, 1):
            val = record.get(header, "")
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border

    # 调整列宽
    col_widths = [15, 20, 10, 10, 10, 12, 10, 12, 12, 8, 8, 14, 18, 18, 20]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    wb.save(output_path)


# ─── 主流程 ────────────────────────────────────────────────────────────────────

def process_single_image(image_path: str, query: BankRegionQuery) -> dict | None:
    """处理单张图片，返回提取的记录"""
    print(f"  OCR: {os.path.basename(image_path)}")
    text = ocr_image(image_path)
    if not text.strip():
        print(f"  警告: {image_path} OCR 未识别到内容，跳过")
        return None

    # 提取信息
    bank = extract_bank_name(text, query)
    if not bank:
        print(f"  警告: {image_path} 未识别到银行名称，跳过")
        print(f"  OCR 文本前200字: {text[:200]}")
        return None

    prefixes = extract_card_prefixes(text)
    if not prefixes:
        print(f"  警告: {image_path} 未识别到卡号前缀，跳过")
        return None

    threshold = extract_threshold(text)
    discount_start, discount_end = extract_discount(text)
    daily = extract_daily_limit(text)
    monthly = extract_monthly_limit(text)
    total = extract_total_limit(text)
    scene = extract_scene(text)
    period_start, period_end = extract_period(text)

    # 查询地区（银行需在数据库中才可查询）
    all_regions = []
    region_codes = set()
    bank_in_db = bank in query.list_banks()
    if bank_in_db:
        for prefix in prefixes:
            regions = get_region_from_prefix(query, bank, prefix)
            all_regions.extend(regions)
            code = get_region_code_from_prefix(prefix)
            if code:
                region_codes.add(code)
        region = summarize_regions(query, bank, all_regions)
    else:
        region = ""
        print(f"  提示: 银行 '{bank}' 不在地区码数据库中，地区留空")

    region_code = ",".join(sorted(region_codes)) if region_codes else ""

    record = {
        "银行": bank,
        "地区": region,
        "地区码": region_code,
        "门槛记录": "",  # 用户手动填写
        "立减记录": "",  # 用户手动填写
        "场景": scene,
        "精确门槛": threshold,
        "精确立减起点": discount_start,
        "精确立减终点": discount_end,
        "日次数": daily,
        "月次数": monthly,
        "活动期间总次数": total,
        "活动期起点": period_start,
        "活动期终点": period_end,
        "备注": "卡号前缀: " + ", ".join(prefixes) if not bank_in_db else "",
    }

    print(f"  银行: {bank}")
    print(f"  地区: {region}")
    print(f"  地区码: {region_code}")
    print(f"  场景: {scene}")
    print(f"  门槛: {threshold}, 立减: {discount_start}~{discount_end}")
    print(f"  日次数: {daily}, 月次数: {monthly}, 总次数: {total}")
    print(f"  活动期: {period_start} ~ {period_end}")

    return record


def main():
    parser = argparse.ArgumentParser(description="银行卡优惠活动信息提取工具")
    parser.add_argument("path", help="图片文件或包含图片的目录路径")
    parser.add_argument("-o", "--output", help="输出 Excel 文件路径（默认: output.xlsx）")
    args = parser.parse_args()

    input_path = Path(args.path)
    output_path = args.output or "output.xlsx"

    # 收集图片文件
    if input_path.is_file():
        images = [str(input_path)]
    elif input_path.is_dir():
        images = sorted([
            str(f) for f in input_path.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        ])
    else:
        print(f"错误: 路径不存在: {input_path}")
        sys.exit(1)

    if not images:
        print("错误: 未找到图片文件")
        sys.exit(1)

    # 初始化查询
    query = BankRegionQuery()

    # 处理每张图片
    records = []
    for image_path in images:
        print(f"\n处理: {image_path}")
        record = process_single_image(image_path, query)
        if record:
            records.append(record)

    if not records:
        print("\n未提取到任何有效记录")
        sys.exit(1)

    # 输出 Excel
    create_excel(records, output_path)
    print(f"\n完成! 共提取 {len(records)} 条记录，已保存到: {output_path}")


if __name__ == "__main__":
    main()
