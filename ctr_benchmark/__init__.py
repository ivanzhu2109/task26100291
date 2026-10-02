"""广告 CTR 基准计算库。"""

from .benchmark import BenchmarkResult, query_percentile
from .storage import WeekRecord, WeekRecordStore

__all__ = [
    "BenchmarkResult",
    "WeekRecord",
    "WeekRecordStore",
    "query_percentile",
]
