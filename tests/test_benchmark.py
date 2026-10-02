"""CTR 基准计算库的自动化测试。

运行方式（仓库根目录，无需任何第三方依赖）：
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from fractions import Fraction

from ctr_benchmark import WeekRecord, WeekRecordStore, query_percentile

INDUSTRY = "美妆"
PLATFORM = "抖音"
OWN_CLICKS = 3
OWN_IMPRESSIONS = 100


def oracle_percentile(records, industry, platform, end_week,
                      own_clicks, own_impressions):
    """独立标准：直接从原始周记录字典重新聚合，不经过被测库的任何代码路径。"""
    clicks = {}
    impressions = {}
    for rec in records.values():
        if rec.industry != industry or rec.platform != platform:
            continue
        if not end_week - 3 <= rec.week <= end_week:
            continue
        clicks[rec.brand] = clicks.get(rec.brand, 0) + rec.clicks
        impressions[rec.brand] = impressions.get(rec.brand, 0) + rec.impressions

    own = Fraction(own_clicks, own_impressions)
    below = equal = total = 0
    for brand, imp in impressions.items():
        if imp == 0:
            continue
        total += 1
        ctr = Fraction(clicks[brand], imp)
        if ctr < own:
            below += 1
        elif ctr == own:
            equal += 1
    if total == 0:
        return None, 0
    return 100.0 * (below + equal / 2) / total, total


class MutationScenarioTest(unittest.TestCase):
    """跨周曝光量悬殊，历史替换与撤回连续发生时，逐窗口对照独立标准。"""

    def setUp(self):
        self.store = WeekRecordStore(":memory:")
        self.addCleanup(self.store.close)
        # 原始周记录字典：测试侧独立维护的事实来源。
        self.records = {}

    def upsert(self, brand, week, clicks, impressions,
               industry=INDUSTRY, platform=PLATFORM):
        rec = WeekRecord(brand, industry, platform, week, clicks, impressions)
        self.store.upsert(rec)
        self.records[(brand, platform, week)] = rec

    def withdraw(self, brand, week, platform=PLATFORM):
        self.store.withdraw(brand, platform, week)
        self.records.pop((brand, platform, week), None)

    def assert_all_windows_match(self):
        for end_week in range(4, 13):
            expected_pct, expected_n = oracle_percentile(
                self.records, INDUSTRY, PLATFORM, end_week,
                OWN_CLICKS, OWN_IMPRESSIONS,
            )
            result = query_percentile(
                self.store, INDUSTRY, PLATFORM, end_week,
                OWN_CLICKS, OWN_IMPRESSIONS,
            )
            self.assertEqual(
                (expected_pct, expected_n),
                (result.percentile, result.peer_count),
                f"end_week={end_week}",
            )

    def test_skewed_impressions_with_replacements_and_withdrawals(self):
        # 曝光量悬殊：Heavy 一周 1_000_000 曝光、另一周 1 曝光。
        # 若错误地平均各周 CTR，结果必然与独立标准不符。
        self.upsert("Heavy", 1, 10_000, 1_000_000)   # 周CTR 1%
        self.upsert("Heavy", 2, 1, 1)                # 周CTR 100%
        self.upsert("Light", 1, 3, 100)
        self.upsert("Light", 2, 3, 100)
        self.upsert("Peer", 3, 6, 200)
        self.assert_all_windows_match()

        # 历史替换：把 Heavy 第 1 周改为零曝光，窗口 1-4 起 Heavy 的
        # 窗口 CTR 从约 1% 变为 100%，参照集合与排序立即变化。
        self.upsert("Heavy", 1, 0, 0)
        self.assert_all_windows_match()

        # 撤回第 2 周：Heavy 在窗口 2-5 起完全无数据，退出参照集合。
        self.withdraw("Heavy", 2)
        self.assert_all_windows_match()

        # 撤回不存在的记录：任何窗口结果都不得改变。
        self.withdraw("Heavy", 2)
        self.withdraw("Ghost", 5)
        self.assert_all_windows_match()

        # 补录更晚的周，验证滑动窗口边界。
        self.upsert("Heavy", 4, 1, 10)
        self.upsert("Light", 5, 9, 100)
        self.upsert("Peer", 6, 1, 1_000)
        self.assert_all_windows_match()

        # 撤回 Light 一周，再把另一周替换为零曝光。
        self.withdraw("Light", 1)
        self.upsert("Light", 2, 0, 0)
        self.assert_all_windows_match()


if __name__ == "__main__":
    unittest.main()


class PrecisionAndEdgeCaseTest(unittest.TestCase):
    """精确并列、极近但不相等的比率、零曝光与空集合。"""

    def setUp(self):
        self.store = WeekRecordStore(":memory:")
        self.addCleanup(self.store.close)

    def upsert(self, brand, week, clicks, impressions,
               industry=INDUSTRY, platform=PLATFORM):
        self.store.upsert(WeekRecord(brand, industry, platform, week,
                                     clicks, impressions))

    def query(self, own_clicks, own_impressions, end_week=4,
              industry=INDUSTRY, platform=PLATFORM):
        return query_percentile(self.store, industry, platform, end_week,
                                own_clicks, own_impressions)

    def test_exact_tie_with_different_numerator_denominator(self):
        # 2/100、4/200、1/50 是同一 CTR 的不同分子分母表示，必须判等。
        self.upsert("P1", 4, 2, 100)
        self.upsert("P2", 4, 4, 200)
        self.upsert("P3", 4, 1, 50)
        self.upsert("P4", 4, 5, 100)   # 更高
        self.upsert("P5", 4, 1, 100)   # 更低
        result = self.query(6, 300)    # 自有 CTR 同为 2%
        self.assertEqual(result.peer_count, 5)
        # (1 低于 + 3 并列/2) / 5 * 100 = 50.0
        self.assertEqual(result.percentile, 50.0)

    def test_close_but_unequal_ratios(self):
        # 1/3 与 333333/1000000 显示后可能相同，但数学上严格不等。
        self.upsert("Near", 4, 333_333, 1_000_000)
        result = self.query(1, 3)
        self.assertEqual(result.peer_count, 1)
        # Near 严格低于自有 -> 百分位 100，而不是并列的 50。
        self.assertEqual(result.percentile, 100.0)
        # 反向：对方替换为精确的 1/3，自有 333333/1000000 严格更低 -> 0。
        self.upsert("Near", 4, 1, 3)
        result = self.query(333_333, 1_000_000)
        self.assertEqual(result.percentile, 0.0)

    def test_zero_impressions_brand_excluded(self):
        self.upsert("Zero", 4, 0, 0)          # 窗口曝光为零，不参与
        self.upsert("ZeroClicks", 4, 0, 500)  # 曝光为正、点击为零，参与
        self.upsert("Normal", 4, 10, 100)
        result = self.query(5, 100)
        self.assertEqual(result.peer_count, 2)
        # ZeroClicks(0) 低于，Normal(10%) 高于 -> 50.0
        self.assertEqual(result.percentile, 50.0)

    def test_brand_with_only_zero_impression_weeks_excluded(self):
        # 同一品牌窗口内多周曝光相加仍为零，同样不参与。
        self.upsert("AllZero", 3, 0, 0)
        self.upsert("AllZero", 4, 0, 0)
        result = self.query(5, 100)
        self.assertEqual(result.peer_count, 0)
        self.assertIsNone(result.percentile)

    def test_empty_set_returns_no_benchmark(self):
        result = self.query(5, 100)
        self.assertEqual(result.peer_count, 0)
        self.assertIsNone(result.percentile)
        # 其他行业/平台有数据也不影响空集合判定。
        self.upsert("Other", 4, 10, 100, industry="汽车")
        self.upsert("Other", 4, 10, 100, platform="快手")
        result = self.query(5, 100)
        self.assertEqual(result.peer_count, 0)
        self.assertIsNone(result.percentile)

    def test_window_aggregation_sums_not_averages(self):
        # 窗口 CTR = 点击之和 / 曝光之和，而非各周 CTR 的平均。
        # 周 CTR 为 100% 与 1%，平均约 50%；按和聚合为 101/200 = 50.5%。
        self.upsert("Skew", 3, 100, 100)
        self.upsert("Skew", 4, 1, 100)
        # 自有 50%：按错误平均法 Skew 高于自有，按正确聚合法 Skew 也高于；
        # 换自有 50.4%：和聚合法下 Skew(50.5%) 高于，平均法(约50%) 低于。
        result = self.query(504, 1000)
        self.assertEqual(result.peer_count, 1)
        self.assertEqual(result.percentile, 0.0)

    def test_invalid_arguments_rejected(self):
        with self.assertRaises(ValueError):
            self.query(1, 100, end_week=3)    # 结束周小于 4
        with self.assertRaises(ValueError):
            self.query(1, 100, end_week=53)   # 结束周大于 52
        with self.assertRaises(ValueError):
            self.query(1, 0)                  # 自有曝光必须为正
        with self.assertRaises(ValueError):
            self.query(-1, 100)               # 点击不能为负
        with self.assertRaises(ValueError):
            self.upsert("Bad", 0, 1, 100)     # 周编号越界
        with self.assertRaises(ValueError):
            self.upsert("Bad", 53, 1, 100)
        with self.assertRaises(ValueError):
            self.upsert("Bad", 4, -1, 100)    # 负数指标
