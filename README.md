# task26100291
## 广告 CTR 基准计算库

媒介采购人员用本库判断自有活动点击率（CTR）在同行业、同平台竞争品牌中的百分位。
周记录持久化在 SQLite，支持覆盖写入、撤回与基准查询；历史周的修正或撤回会立即反映到所有包含该周的窗口。

### 运行环境

- Python 3.10+，仅使用标准库（`sqlite3`、`fractions`），无第三方依赖。

### 运行测试

```bash
python3 -m unittest discover -s tests -v
```

### 使用示例

```python
from ctr_benchmark import WeekRecord, WeekRecordStore, query_percentile

with WeekRecordStore("benchmark.db") as store:
    # 覆盖写入：同一 (品牌, 平台, 周) 重复写入表示完整替换
    store.upsert(WeekRecord("品牌A", "美妆", "抖音", week=4, clicks=5, impressions=100))
    # 撤回：记录不存在时不产生任何影响
    store.withdraw("品牌A", "抖音", week=4)
    # 基准查询：窗口为结束周及其之前 3 周
    result = query_percentile(store, "美妆", "抖音", end_week=4,
                              own_clicks=3, own_impressions=100)
    print(result.percentile, result.peer_count)  # 集合为空时 percentile 为 None
```

### 目录结构

- `ctr_benchmark/storage.py`：周记录的 SQLite 存储（覆盖写入、撤回、窗口读取）
- `ctr_benchmark/benchmark.py`：基准查询（4 周窗口聚合、精确比率比较、百分位计算）
- `tests/test_benchmark.py`：自动化测试
