from __future__ import annotations

import re

URL_PATTERN = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?)]}，。；：！？）】》」』"
TIME_PATTERN = re.compile(
    r"(\d{1,2}月\d{1,2}日|\d{1,2}号|今天|明天|后天|今晚|明早|本周|这周|周末|周[一二三四五六日天]"
    r"|下周|月底|月初|节假日|国庆|春节|五一|端午|中秋)",
    re.IGNORECASE,
)
LOCATION_PATTERN = re.compile(
    r"([A-Za-z\u4e00-\u9fff]{2,20}(市|区|县|镇|村|街|路|站|机场|大学|园区|公园|景区|商场|展馆|博物馆|体育馆|校区))"
)
BUDGET_PATTERN = re.compile(r"(\d+(?:\.\d+)?\s*(元|块|w|万|k|K)|预算|花费|价格|价位|人民币)")


def merge_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def extract_urls(text: str) -> list[str]:
    cleaned: list[str] = []
    for match in URL_PATTERN.findall(text):
        normalized = match.rstrip(TRAILING_URL_PUNCTUATION)
        if normalized:
            cleaned.append(normalized)
    return cleaned


def has_time_signal(*parts: str | None) -> bool:
    return bool(TIME_PATTERN.search(merge_text(*parts)))


def has_location_signal(*parts: str | None) -> bool:
    text = merge_text(*parts)
    if not text:
        return False
    explicit_terms = ("落地", "地点", "目的地", "位置", "现场", "路上", "通勤", "机场", "车站")
    return bool(LOCATION_PATTERN.search(text)) or any(term in text for term in explicit_terms)


def has_budget_signal(*parts: str | None) -> bool:
    return bool(BUDGET_PATTERN.search(merge_text(*parts)))
