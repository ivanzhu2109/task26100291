"""基准查询：基于最近 4 周窗口计算自有活动 CTR 的百分位。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from .storage import WeekRecordStore

WINDOW_SIZE = 4
MIN_END_WEEK = 4
MAX_END_WEEK = 52


@dataclass(frozen=True)
class BenchmarkResult:
    """一次基准查询的结果。

    percentile 为 None 表示参照集合为空，无基准。
    """

    percentile: float | None
    peer_count: int


def query_percentile(
    store: WeekRecordStore,
    industry: str,
    platform: str,
    end_week: int,
    own_clicks: int,
    own_impressions: int,
) -> BenchmarkResult:
    """计算自有活动 CTR 在同行业、同平台竞争品牌中的百分位。"""
    if not MIN_END_WEEK <= end_week <= MAX_END_WEEK:
        raise ValueError(
            f"end_week 必须在 {MIN_END_WEEK}..{MAX_END_WEEK} 之间: {end_week}"
        )
    if own_clicks < 0:
        raise ValueError("own_clicks 不能为负数")
    if own_impressions <= 0:
        raise ValueError("own_impressions 必须为正数")

    start_week = end_week - WINDOW_SIZE + 1
    records = store.fetch_window(industry, platform, start_week, end_week)

    clicks_by_brand: dict[str, int] = defaultdict(int)
    impressions_by_brand: dict[str, int] = defaultdict(int)
    for record in records:
        clicks_by_brand[record.brand] += record.clicks
        impressions_by_brand[record.brand] += record.impressions

    own_ctr = Fraction(own_clicks, own_impressions)
    below = 0
    equal = 0
    peer_count = 0
    for brand, impressions in impressions_by_brand.items():
        if impressions == 0:
            continue
        peer_count += 1
        peer_ctr = Fraction(clicks_by_brand[brand], impressions)
        if peer_ctr < own_ctr:
            below += 1
        elif peer_ctr == own_ctr:
            equal += 1

    if peer_count == 0:
        return BenchmarkResult(percentile=None, peer_count=0)
    percentile = 100.0 * (below + equal / 2) / peer_count
    return BenchmarkResult(percentile=percentile, peer_count=peer_count)
