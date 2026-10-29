from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL,
  pages_fetched INTEGER NOT NULL DEFAULT 0,
  records_fetched INTEGER NOT NULL DEFAULT 0,
  accepted_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0,
  published_count INTEGER NOT NULL DEFAULT 0,
  skipped_existing_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT
);
CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_name TEXT PRIMARY KEY,
  next_page INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  last_run_id TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  amount REAL NOT NULL CHECK(amount >= 0),
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  event_time TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  source_page INTEGER NOT NULL,
  source_run_id TEXT NOT NULL,
  source_record_json TEXT NOT NULL,
  FOREIGN KEY(source_run_id) REFERENCES pipeline_runs(run_id)
);
CREATE TABLE IF NOT EXISTS quarantine (
  quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  source_page INTEGER,
  record_index INTEGER,
  reason TEXT NOT NULL,
  raw_record TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
);
CREATE TABLE IF NOT EXISTS page_commits (
  checkpoint_name TEXT NOT NULL,
  page_number INTEGER NOT NULL,
  run_id TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  raw_file TEXT NOT NULL,
  record_count INTEGER NOT NULL,
  PRIMARY KEY(checkpoint_name, page_number)
);
CREATE INDEX IF NOT EXISTS idx_orders_updated_at ON orders(updated_at);
CREATE INDEX IF NOT EXISTS idx_quarantine_run_id ON quarantine(run_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA)
    # Migration: databases created before skipped_existing_count existed get the column added.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(pipeline_runs)")}
    if "skipped_existing_count" not in columns:
        connection.execute(
            "ALTER TABLE pipeline_runs ADD COLUMN skipped_existing_count INTEGER NOT NULL DEFAULT 0"
        )
        connection.commit()
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection):
    try:
        connection.execute("BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise