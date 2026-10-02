"""周记录的 SQLite 持久化：覆盖写入与撤回。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

MIN_WEEK = 1
MAX_WEEK = 52


@dataclass(frozen=True)
class WeekRecord:
    """一条周记录，由 (brand, platform, week) 唯一定位。"""

    brand: str
    industry: str
    platform: str
    week: int
    clicks: int
    impressions: int


class WeekRecordStore:
    """基于 SQLite 的周记录存储。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS week_record (
                brand       TEXT NOT NULL,
                industry    TEXT NOT NULL,
                platform    TEXT NOT NULL,
                week        INTEGER NOT NULL,
                clicks      INTEGER NOT NULL,
                impressions INTEGER NOT NULL,
                PRIMARY KEY (brand, platform, week)
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "WeekRecordStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert(self, record: WeekRecord) -> None:
        """覆盖写入一条周记录；重复写入表示完整替换。"""
        if not MIN_WEEK <= record.week <= MAX_WEEK:
            raise ValueError(f"week 必须在 {MIN_WEEK}..{MAX_WEEK} 之间: {record.week}")
        if record.clicks < 0 or record.impressions < 0:
            raise ValueError("clicks 与 impressions 不能为负数")
        self._conn.execute(
            """
            INSERT INTO week_record (brand, industry, platform, week, clicks, impressions)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (brand, platform, week)
            DO UPDATE SET industry = excluded.industry,
                          clicks = excluded.clicks,
                          impressions = excluded.impressions
            """,
            (
                record.brand,
                record.industry,
                record.platform,
                record.week,
                record.clicks,
                record.impressions,
            ),
        )
        self._conn.commit()

    def withdraw(self, brand: str, platform: str, week: int) -> None:
        """撤回一条周记录；记录不存在时不产生任何影响。"""
        self._conn.execute(
            "DELETE FROM week_record WHERE brand = ? AND platform = ? AND week = ?",
            (brand, platform, week),
        )
        self._conn.commit()

    def fetch_window(
        self, industry: str, platform: str, start_week: int, end_week: int
    ) -> list[WeekRecord]:
        """读取指定行业、平台、周区间内的全部记录。"""
        rows = self._conn.execute(
            """
            SELECT brand, industry, platform, week, clicks, impressions
            FROM week_record
            WHERE industry = ? AND platform = ? AND week BETWEEN ? AND ?
            """,
            (industry, platform, start_week, end_week),
        ).fetchall()
        return [WeekRecord(*row) for row in rows]
