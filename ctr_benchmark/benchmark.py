"""Benchmark query logic over stored weekly records."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .store import MAX_WEEK, MIN_WEEK, WeeklyRecordStore

WINDOW_SIZE = 4


@dataclass(frozen=True)
class BenchmarkResult:
    """Outcome of a benchmark query."""

    percentile: float
    brand_count: int
    own_ctr: Fraction


class CtrBenchmark:
    """Public facade: weekly record writes, withdrawals, benchmark queries."""

    def __init__(self, db_path: str) -> None:
        self._store = WeeklyRecordStore(db_path)

    def upsert_weekly_record(
        self,
        brand: str,
        industry: str,
        platform: str,
        week: int,
        clicks: int,
        impressions: int,
    ) -> None:
        self._store.upsert_record(brand, industry, platform, week, clicks, impressions)

    def withdraw_weekly_record(self, brand: str, platform: str, week: int) -> bool:
        return self._store.withdraw_record(brand, platform, week)

    def query_benchmark(
        self,
        industry: str,
        platform: str,
        end_week: int,
        own_clicks: int,
        own_impressions: int,
    ) -> BenchmarkResult | None:
        """Percentile of own CTR vs brands in the 4-week window; None if empty."""
        if not MIN_WEEK + WINDOW_SIZE - 1 <= end_week <= MAX_WEEK:
            raise ValueError(
                f"end_week must be in [{MIN_WEEK + WINDOW_SIZE - 1}, {MAX_WEEK}], "
                f"got {end_week}"
            )
        if own_clicks < 0:
            raise ValueError("own_clicks must be non-negative")
        if own_impressions <= 0:
            raise ValueError("own_impressions must be positive")
        own_ctr = Fraction(own_clicks, own_impressions)
        rows = self._store.fetch_window_records(
            industry, platform, end_week - WINDOW_SIZE + 1, end_week
        )
        clicks_by_brand: dict[str, int] = {}
        impressions_by_brand: dict[str, int] = {}
        for brand, _week, clicks, impressions in rows:
            clicks_by_brand[brand] = clicks_by_brand.get(brand, 0) + clicks
            impressions_by_brand[brand] = (
                impressions_by_brand.get(brand, 0) + impressions
            )
        below = 0
        equal = 0
        brand_count = 0
        for brand, total_impressions in impressions_by_brand.items():
            if total_impressions == 0:
                continue
            brand_count += 1
            brand_ctr = Fraction(clicks_by_brand[brand], total_impressions)
            if brand_ctr < own_ctr:
                below += 1
            elif brand_ctr == own_ctr:
                equal += 1
        if brand_count == 0:
            return None
        percentile = 100.0 * (below + 0.5 * equal) / brand_count
        return BenchmarkResult(
            percentile=percentile, brand_count=brand_count, own_ctr=own_ctr
        )

    def close(self) -> None:
        self._store.close()
