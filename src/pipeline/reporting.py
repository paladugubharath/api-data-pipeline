from __future__ import annotations
import json
import time
from pathlib import Path
from .db import connect


def reconciliation(db_path: str, report_path: str | None = None) -> dict:
    connection = connect(db_path)
    try:
        runs = connection.execute(
            """SELECT COUNT(*) run_count, COALESCE(SUM(records_fetched),0) fetched,
               COALESCE(SUM(accepted_count),0) accepted, COALESCE(SUM(rejected_count),0) rejected,
               COALESCE(SUM(published_count),0) published,
               COALESCE(SUM(skipped_existing_count),0) skipped FROM pipeline_runs"""
        ).fetchone()
        target = connection.execute("SELECT COUNT(*) count, COALESCE(SUM(amount),0) amount_sum FROM orders").fetchone()
        quarantine = connection.execute("SELECT COUNT(*) count FROM quarantine").fetchone()["count"]
        duplicates = connection.execute(
            "SELECT COUNT(*) count FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1)"
        ).fetchone()["count"]
        unexplained = runs["fetched"] - runs["accepted"] - runs["rejected"] - runs["skipped"]
        result = {
            "run_count": runs["run_count"], "records_fetched_across_runs": runs["fetched"],
            "accepted_across_runs": runs["accepted"], "rejected_across_runs": runs["rejected"],
            "published_across_runs": runs["published"],
            "skipped_existing_across_runs": runs["skipped"],
            "unexplained_records": unexplained,
            "source_reconciles": unexplained == 0,
            "target_matches_accepted": target["count"] == runs["accepted"],
            "target_rows": target["count"],
            "target_amount_sum": round(target["amount_sum"], 2), "quarantine_rows": quarantine,
            "duplicate_target_keys": duplicates,
            "target_primary_key_unique": duplicates == 0,
            "note": "Run-level counts include replays; target_rows is the unique current target state. "
                    "Quarantine is an append-only audit log, one set of rows per run.",
        }
        if report_path:
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
            Path(report_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        connection.close()


def benchmark(db_path: str, parquet_path: str, output_path: str) -> dict:
    import pandas as pd
    timings = {}

    # 1) Original measurements, kept so earlier results stay comparable.
    start = time.perf_counter()
    connection = connect(db_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        timings["sqlite_count_seconds"] = round(time.perf_counter() - start, 6)
    finally:
        connection.close()
    start = time.perf_counter()
    frame = pd.read_parquet(parquet_path)
    timings["parquet_read_seconds"] = round(time.perf_counter() - start, 6)

    # 2) Like-for-like: the same aggregate (count and total amount per status) on both stores.
    start = time.perf_counter()
    connection = connect(db_path)
    try:
        sqlite_agg = {
            row["status"]: (row["n"], round(row["total"], 2))
            for row in connection.execute(
                "SELECT status, COUNT(*) n, COALESCE(SUM(amount),0) total FROM orders GROUP BY status"
            )
        }
    finally:
        connection.close()
    sqlite_agg_seconds = round(time.perf_counter() - start, 6)

    start = time.perf_counter()
    narrow = pd.read_parquet(parquet_path, columns=["status", "amount"])
    grouped = narrow.groupby("status")["amount"].agg(["count", "sum"])
    parquet_agg = {
        status: (int(row["count"]), round(float(row["sum"]), 2)) for status, row in grouped.iterrows()
    }
    parquet_agg_seconds = round(time.perf_counter() - start, 6)

    aggregates_match = (
        sqlite_agg.keys() == parquet_agg.keys()
        and all(
            sqlite_agg[k][0] == parquet_agg[k][0] and abs(sqlite_agg[k][1] - parquet_agg[k][1]) < 0.01
            for k in sqlite_agg
        )
    )

    result = {
        "target_rows_sqlite": count, "target_rows_parquet": len(frame),
        "sqlite_count_seconds": timings["sqlite_count_seconds"],
        "parquet_read_seconds": timings["parquet_read_seconds"],
        "sqlite_aggregate_seconds": sqlite_agg_seconds,
        "parquet_aggregate_seconds": parquet_agg_seconds,
        "aggregates_match": aggregates_match,
        "optimization": (
            "Measured on a 100,000-record run: the run was dominated by the mock API re-parsing its data "
            "file on every request. Caching the parsed file (reloaded only when its path, mtime or size "
            "changes) cut the run from roughly 106-138 s to roughly 26-30 s. SQLite work was about 2% of "
            "runtime in a 40-page profile, so batching inserts with executemany is not justified yet."
        ),
        "note": (
            "sqlite_count_seconds times COUNT(*) only, while parquet_read_seconds loads every column into "
            "a DataFrame, so those two are not like-for-like. Compare sqlite_aggregate_seconds with "
            "parquet_aggregate_seconds instead: both compute the same count and sum per status."
        ),
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
