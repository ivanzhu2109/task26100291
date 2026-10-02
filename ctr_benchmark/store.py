"""SQLite persistence layer for weekly CTR records."""

from __future__ import annotations

import sqlite3

MIN_WEEK = 1
MAX_WEEK = 52

_SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    brand TEXT PRIMARY KEY,
    industry TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_records (
    brand TEXT NOT NULL,
    platform TEXT NOT NULL,
    week INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    PRIMARY KEY (brand, platform, week)
);
"""


class WeeklyRecordStore:
    """Stores weekly (brand, platform, week) -> (clicks, impressions) records."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)

    def upsert_record(
        self,
        brand: str,
        industry: str,
        platform: str,
        week: int,
        clicks: int,
        impressions: int,
    ) -> None:
        """Fully replace the record identified by (brand, platform, week)."""
        if not MIN_WEEK <= week <= MAX_WEEK:
            raise ValueError(f"week must be in [{MIN_WEEK}, {MAX_WEEK}], got {week}")
        if clicks < 0 or impressions < 0:
            raise ValueError("clicks and impressions must be non-negative")
        if clicks > impressions:
            raise ValueError("clicks cannot exceed impressions")
        row = self._conn.execute(
            "SELECT industry FROM brands WHERE brand = ?", (brand,)
        ).fetchone()
        if row is not None and row[0] != industry:
            raise ValueError(
                f"brand {brand!r} already belongs to industry {row[0]!r}"
            )
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO brands (brand, industry) VALUES (?, ?)",
                (brand, industry),
            )
            self._conn.execute(
                """
                INSERT INTO weekly_records
                    (brand, platform, week, clicks, impressions)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (brand, platform, week)
                DO UPDATE SET clicks = excluded.clicks,
                              impressions = excluded.impressions
                """,
                (brand, platform, week, clicks, impressions),
            )

    def withdraw_record(self, brand: str, platform: str, week: int) -> bool:
        """Remove the record if present; return True when a row was removed."""
        with self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM weekly_records
                WHERE brand = ? AND platform = ? AND week = ?
                """,
                (brand, platform, week),
            )
        return cursor.rowcount > 0

    def fetch_window_records(
        self,
        industry: str,
        platform: str,
        start_week: int,
        end_week: int,
    ) -> list[tuple[str, int, int, int]]:
        """Return (brand, week, clicks, impressions) rows for the window."""
        cursor = self._conn.execute(
            """
            SELECT r.brand, r.week, r.clicks, r.impressions
            FROM weekly_records r
            JOIN brands b ON b.brand = r.brand
            WHERE b.industry = ?
              AND r.platform = ?
              AND r.week BETWEEN ? AND ?
            """,
            (industry, platform, start_week, end_week),
        )
        return [(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()
