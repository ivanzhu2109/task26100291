# ctr_benchmark

广告 CTR 基准计算库：周记录保存在 SQLite，由上层代码直接调用。

## 能力

- `upsert_weekly_record(brand, industry, platform, week, clicks, impressions)`
  周记录覆盖写入。记录由（品牌、平台、周）唯一定位，重复写入为完整替换；
  品牌的行业固定，冲突时抛 `ValueError`。周范围 1–52。
- `withdraw_weekly_record(brand, platform, week)`
  撤回周记录；记录不存在时不改变结果，返回 `False`。
- `query_benchmark(industry, platform, end_week, own_clicks, own_impressions)`
  基准查询，结束周范围 4–52，窗口为结束周及其之前 3 周。
  返回 `BenchmarkResult(percentile, brand_count, own_ctr)`；
  参照集合为空时返回 `None`（不是零百分位）。

## 规则

- 每个竞争品牌的窗口 CTR = 窗口内点击数之和 / 曝光数之和（不是各周 CTR 的平均）。
- 缺失周不贡献数据；窗口曝光总数为零的品牌不参与对标。
- 只纳入指定行业、指定平台的数据；每个品牌无论数据多少只贡献一个等权参照值。
- 自有活动只用于查询，不加入参照集合。
- 百分位 = 100 ×（严格低于的品牌数 + 相等品牌数的一半）/ 参与品牌总数。
- 比率比较使用 `fractions.Fraction` 的数学精确值，仅最终百分位转为小数。
- 查询每次基于 SQLite 中的原始周记录实时计算，因此修正或撤回任意历史周后，
  所有包含该周的窗口立即使用新数据，其他窗口不受影响。

## 用法

```python
from ctr_benchmark import CtrBenchmark

bench = CtrBenchmark("ctr.db")          # 或 ":memory:"
bench.upsert_weekly_record("brandA", "auto", "web", 10, 120, 40000)
bench.withdraw_weekly_record("brandA", "web", 10)
result = bench.query_benchmark("auto", "web", 12, 300, 100000)
if result is not None:
    print(result.percentile, result.brand_count)
bench.close()
```

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

无第三方依赖，仅需 Python 3.10+ 标准库。
