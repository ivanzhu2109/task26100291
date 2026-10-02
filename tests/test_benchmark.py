"""Automated tests for the ctr_benchmark library.

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import random
import unittest
from fractions import Fraction

from ctr_benchmark import CtrBenchmark

WINDOW_SIZE = 4


def oracle_percentile(
    records: dict[tuple[str, str, int], tuple[int, int]],
    brand_industry: dict[str, str],
    industry: str,
    platform: str,
    end_week: int,
    own_clicks: int,
    own_impressions: int,
) -> tuple[float, int] | None:
    """Independent reference: recompute from raw weekly records only."""
    own_ctr = Fraction(own_clicks, own_impressions)
    start_week = end_week - WINDOW_SIZE + 1
    clicks_by_brand: dict[str, int] = {}
    impressions_by_brand: dict[str, int] = {}
    for (brand, rec_platform, week), (clicks, impressions) in records.items():
        if brand_industry[brand] != industry:
            continue
        if rec_platform != platform or not start_week <= week <= end_week:
            continue
        clicks_by_brand[brand] = clicks_by_brand.get(brand, 0) + clicks
        impressions_by_brand[brand] = impressions_by_brand.get(brand, 0) + impressions
    below = 0
    equal = 0
    total = 0
    for brand, total_impressions in impressions_by_brand.items():
        if total_impressions == 0:
            continue
        total += 1
        brand_ctr = Fraction(clicks_by_brand[brand], total_impressions)
        if brand_ctr < own_ctr:
            below += 1
        elif brand_ctr == own_ctr:
            equal += 1
    if total == 0:
        return None
    return 100.0 * (below + 0.5 * equal) / total, total


class MutationSequenceTest(unittest.TestCase):
    """Disparate weekly volumes with interleaved replaces and withdrawals.

    After every mutation, every window (end weeks 4..52) must match an
    independent recomputation from the raw weekly records.
    """

    def setUp(self) -> None:
        self.bench = CtrBenchmark(":memory:")
        self.records: dict[tuple[str, str, int], tuple[int, int]] = {}
        self.brand_industry = {
            "alpha": "auto",
            "beta": "auto",
            "gamma": "auto",
            "delta": "auto",
            "epsilon": "finance",  # different industry, must be ignored
        }

    def tearDown(self) -> None:
        self.bench.close()

    def apply_upsert(
        self,
        brand: str,
        platform: str,
        week: int,
        clicks: int,
        impressions: int,
    ) -> None:
        self.bench.upsert_weekly_record(
            brand, self.brand_industry[brand], platform, week, clicks, impressions
        )
        self.records[(brand, platform, week)] = (clicks, impressions)

    def apply_withdraw(self, brand: str, platform: str, week: int) -> None:
        removed = self.bench.withdraw_weekly_record(brand, platform, week)
        existed = self.records.pop((brand, platform, week), None) is not None
        self.assertEqual(removed, existed)

    def assert_all_windows_match(self, own_clicks: int, own_impressions: int) -> None:
        for end_week in range(4, 53):
            result = self.bench.query_benchmark(
                "auto", "web", end_week, own_clicks, own_impressions
            )
            expected = oracle_percentile(
                self.records,
                self.brand_industry,
                "auto",
                "web",
                end_week,
                own_clicks,
                own_impressions,
            )
            if expected is None:
                self.assertIsNone(result, f"end_week={end_week}")
            else:
                self.assertIsNotNone(result, f"end_week={end_week}")
                self.assertAlmostEqual(
                    result.percentile, expected[0], places=12, msg=f"end_week={end_week}"
                )
                self.assertEqual(
                    result.brand_count, expected[1], f"end_week={end_week}"
                )

    def test_replace_and_withdraw_sequence(self) -> None:
        rng = random.Random(20261002)
        brands = ["alpha", "beta", "gamma", "delta", "epsilon"]
        platforms = ["web", "app"]

        # Initial load: wildly disparate weekly volumes (1 to ~10^7 impressions).
        for brand in brands:
            for platform in platforms:
                for week in range(1, 53):
                    if rng.random() < 0.2:
                        continue  # missing weeks contribute nothing
                    impressions = rng.choice([0, 1, 7, 500, 60_000, 9_999_999])
                    clicks = rng.randint(0, impressions) if impressions else 0
                    self.apply_upsert(brand, platform, week, clicks, impressions)
        self.assert_all_windows_match(321, 10_000)

        # Historical corrections: full replacement of earlier weeks.
        for _ in range(60):
            brand = rng.choice(brands)
            platform = rng.choice(platforms)
            week = rng.randint(1, 52)
            impressions = rng.choice([0, 3, 250, 80_000, 5_000_000])
            clicks = rng.randint(0, impressions) if impressions else 0
            self.apply_upsert(brand, platform, week, clicks, impressions)
            self.assert_all_windows_match(321, 10_000)

        # Withdrawals, including records that do not exist (must be no-ops).
        for _ in range(60):
            brand = rng.choice(brands)
            platform = rng.choice(platforms)
            week = rng.randint(1, 52)
            self.apply_withdraw(brand, platform, week)
            self.assert_all_windows_match(321, 10_000)

        # Re-add some withdrawn weeks; windows must pick them up immediately.
        for _ in range(40):
            brand = rng.choice(brands)
            platform = rng.choice(platforms)
            week = rng.randint(1, 52)
            impressions = rng.choice([0, 11, 900, 123_456])
            clicks = rng.randint(0, impressions) if impressions else 0
            self.apply_upsert(brand, platform, week, clicks, impressions)
            self.assert_all_windows_match(7, 500)


class ExactComparisonTest(unittest.TestCase):
    """Exact ties, near-but-unequal ratios, zero impressions, empty sets."""

    def setUp(self) -> None:
        self.bench = CtrBenchmark(":memory:")

    def tearDown(self) -> None:
        self.bench.close()

    def test_exact_tie_with_different_fractions(self) -> None:
        # 2/6 and 5/15 both equal 1/3 exactly; ties count as half.
        self.bench.upsert_weekly_record("tie1", "auto", "web", 1, 2, 6)
        self.bench.upsert_weekly_record("tie2", "auto", "web", 4, 5, 15)
        self.bench.upsert_weekly_record("low", "auto", "web", 2, 1, 100)
        result = self.bench.query_benchmark("auto", "web", 4, 1, 3)
        self.assertIsNotNone(result)
        self.assertEqual(result.brand_count, 3)
        # below=1, equal=2 -> 100 * (1 + 1) / 3
        self.assertAlmostEqual(result.percentile, 200.0 / 3.0, places=12)

    def test_close_but_unequal_ratios(self) -> None:
        # 1/3 vs 333333/1000000: display-equal at many precisions, not equal.
        self.bench.upsert_weekly_record("near", "auto", "web", 1, 333333, 1000000)
        result = self.bench.query_benchmark("auto", "web", 4, 1, 3)
        self.assertIsNotNone(result)
        # 333333/1000000 < 1/3, so the brand is strictly below.
        self.assertAlmostEqual(result.percentile, 100.0, places=12)
        # And the mirror: own is the near ratio, brand holds exactly 1/3.
        bench2 = CtrBenchmark(":memory:")
        self.addCleanup(bench2.close)
        bench2.upsert_weekly_record("exact", "auto", "web", 1, 1, 3)
        result2 = bench2.query_benchmark("auto", "web", 4, 333333, 1000000)
        self.assertIsNotNone(result2)
        # 1/3 > 333333/1000000, brand is strictly above -> percentile 0.
        self.assertAlmostEqual(result2.percentile, 0.0, places=12)

    def test_window_ctr_is_ratio_of_sums_not_mean_of_ratios(self) -> None:
        # Weeks: 1/1 (100%) and 1/999 (~0.1%). Ratio of sums = 2/1000 = 0.2%,
        # far below the 50.05% mean-of-ratios value.
        self.bench.upsert_weekly_record("skew", "auto", "web", 1, 1, 1)
        self.bench.upsert_weekly_record("skew", "auto", "web", 2, 1, 999)
        result = self.bench.query_benchmark("auto", "web", 4, 1, 100)
        self.assertIsNotNone(result)
        # 2/1000 < 1/100, so the single brand is strictly below.
        self.assertAlmostEqual(result.percentile, 100.0, places=12)

    def test_zero_impression_brand_excluded(self) -> None:
        self.bench.upsert_weekly_record("zero", "auto", "web", 1, 0, 0)
        self.bench.upsert_weekly_record("zero", "auto", "web", 3, 0, 0)
        self.bench.upsert_weekly_record("real", "auto", "web", 2, 1, 10)
        result = self.bench.query_benchmark("auto", "web", 4, 5, 100)
        self.assertIsNotNone(result)
        self.assertEqual(result.brand_count, 1)
        # 1/10 > 5/100 -> the only brand is strictly above.
        self.assertAlmostEqual(result.percentile, 0.0, places=12)

    def test_all_zero_impressions_yields_no_benchmark(self) -> None:
        self.bench.upsert_weekly_record("zero", "auto", "web", 1, 0, 0)
        result = self.bench.query_benchmark("auto", "web", 4, 1, 100)
        self.assertIsNone(result)

    def test_empty_set_returns_none_not_zero(self) -> None:
        result = self.bench.query_benchmark("auto", "web", 4, 1, 100)
        self.assertIsNone(result)
        # Wrong industry / platform also yields no benchmark.
        self.bench.upsert_weekly_record("a", "auto", "web", 1, 1, 10)
        self.assertIsNone(self.bench.query_benchmark("finance", "web", 4, 1, 100))
        self.assertIsNone(self.bench.query_benchmark("auto", "app", 4, 1, 100))

    def test_withdraw_nonexistent_is_noop(self) -> None:
        self.bench.upsert_weekly_record("a", "auto", "web", 1, 1, 10)
        before = self.bench.query_benchmark("auto", "web", 4, 1, 10)
        self.assertFalse(self.bench.withdraw_weekly_record("a", "web", 2))
        self.assertFalse(self.bench.withdraw_weekly_record("ghost", "web", 1))
        after = self.bench.query_benchmark("auto", "web", 4, 1, 10)
        self.assertEqual(before, after)

    def test_correction_updates_all_overlapping_windows_only(self) -> None:
        self.bench.upsert_weekly_record("a", "auto", "web", 5, 1, 100)
        self.bench.upsert_weekly_record("b", "auto", "web", 5, 50, 100)
        # Windows ending 5..8 contain week 5; window ending 4 does not.
        # a=1/100 below own 10/100, b=50/100 above -> 100 * 1 / 2 = 50.
        self.assertAlmostEqual(
            self.bench.query_benchmark("auto", "web", 8, 10, 100).percentile,
            50.0,
            places=12,
        )
        # Correct week 5 of brand b downward: 50/100 -> 1/1000.
        self.bench.upsert_weekly_record("b", "auto", "web", 5, 1, 1000)
        # Now both brands are below own (10/100): percentile 100.
        self.assertAlmostEqual(
            self.bench.query_benchmark("auto", "web", 8, 10, 100).percentile,
            100.0,
            places=12,
        )
        # Window ending 4 never contained week 5 and stays empty.
        self.assertIsNone(self.bench.query_benchmark("auto", "web", 4, 10, 100))
        # Withdraw the correction; brand b leaves the reference set entirely.
        self.assertTrue(self.bench.withdraw_weekly_record("b", "web", 5))
        result = self.bench.query_benchmark("auto", "web", 8, 10, 100)
        self.assertEqual(result.brand_count, 1)
        self.assertAlmostEqual(result.percentile, 100.0, places=12)

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "auto", "web", 0, 1, 10)
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "auto", "web", 53, 1, 10)
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "auto", "web", 1, -1, 10)
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "auto", "web", 1, 1, -10)
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "auto", "web", 1, 11, 10)
        with self.assertRaises(ValueError):
            self.bench.query_benchmark("auto", "web", 3, 1, 10)
        with self.assertRaises(ValueError):
            self.bench.query_benchmark("auto", "web", 53, 1, 10)
        with self.assertRaises(ValueError):
            self.bench.query_benchmark("auto", "web", 4, 1, 0)
        # A brand's industry is fixed.
        self.bench.upsert_weekly_record("a", "auto", "web", 1, 1, 10)
        with self.assertRaises(ValueError):
            self.bench.upsert_weekly_record("a", "finance", "web", 2, 1, 10)


if __name__ == "__main__":
    unittest.main()
