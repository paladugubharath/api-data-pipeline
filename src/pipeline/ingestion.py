from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .client import APIClient
from .db import connect
from .transform import transform
from .validation import stable_json, validate_record

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_ingestion(config: dict[str, Any], known_customers: set[str] | None = None,
                  start_page: int | None = None, max_pages: int | None = None) -> dict[str, Any]:
    api, paths = config["api"], config["paths"]
    db_path = Path(paths["database"])
    for key in ("raw_dir", "quarantine_dir", "parquet_dir", "reports_dir"):
        Path(paths[key]).mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    checkpoint_name = paths.get("checkpoint_name", "orders")
    connection = connect(db_path)
    connection.execute(
        "INSERT INTO pipeline_runs(run_id, source_name, started_at, status) VALUES(?,?,?,?)",
        (run_id, "mock_orders_api", started_at, "running"),
    )
    connection.commit()
    checkpoint = connection.execute(
        "SELECT next_page FROM checkpoints WHERE checkpoint_name=?", (checkpoint_name,)
    ).fetchone()
    page = start_page if start_page is not None else (checkpoint["next_page"] if checkpoint else 1)
    pages_fetched = records_fetched = accepted = rejected = published = skipped = 0
    client = APIClient(
        api["base_url"], api["token"], api.get("timeout_seconds", 10),
        api.get("max_retries", 4), api.get("backoff_seconds", 0.2),
        api.get("requests_per_second", 20),
    )
    raw_dir = Path(paths["raw_dir"]) / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        while max_pages is None or pages_fetched < max_pages:
            payload = client.get_page(page, int(api.get("page_size", 250)))
            if payload.get("page") != page:
                raise ValueError(f"API page mismatch: requested {page}, got {payload.get('page')}")
            raw_file = raw_dir / f"page_{page:06d}.json"
            raw_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            expected_envelope_fields = {"page", "page_size", "total", "total_pages", "has_more", "data"}
            unexpected_fields = set(payload) - expected_envelope_fields
            if unexpected_fields:
                raise ValueError(f"Unexpected API response schema fields: {sorted(unexpected_fields)}")
            rows = payload["data"]
            page_accepted = page_rejected = page_published = page_skipped = 0
            # Page contents, quarantine rows, target rows, audit marker and checkpoint commit atomically.
            connection.execute("BEGIN")
            try:
                for index, raw_record in enumerate(rows):
                    valid, reason = validate_record(raw_record, known_customers)
                    if reason:
                        connection.execute(
                            """INSERT INTO quarantine(run_id,source_page,record_index,reason,raw_record,created_at)
                               VALUES(?,?,?,?,?,?)""",
                            (run_id, page, index, reason, stable_json(raw_record), utc_now()),
                        )
                        page_rejected += 1
                        continue
                    valid = transform(valid)
                    existing = connection.execute(
                        "SELECT source_record_json FROM orders WHERE order_id=?", (valid["order_id"],)
                    ).fetchone()
                    source_json = stable_json(raw_record)
                    if existing:
                        # Identical key with identical source payload is a safe replay; changed payload is a duplicate conflict.
                        if existing["source_record_json"] == source_json:
                            page_skipped += 1
                            continue
                        connection.execute(
                            """INSERT INTO quarantine(run_id,source_page,record_index,reason,raw_record,created_at)
                               VALUES(?,?,?,?,?,?)""",
                            (run_id, page, index, "duplicate order_id with conflicting payload",
                             source_json, utc_now()),
                        )
                        page_rejected += 1
                        continue
                    connection.execute(
                        """INSERT INTO orders(order_id,customer_id,amount,currency,status,event_time,updated_at,
                           source_page,source_run_id,source_record_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (valid["order_id"], valid["customer_id"], valid["amount"], valid["currency"],
                         valid["status"], valid["event_time"], valid["updated_at"], page, run_id, source_json),
                    )
                    page_accepted += 1
                    page_published += 1
                connection.execute(
                    """INSERT OR REPLACE INTO page_commits(checkpoint_name,page_number,run_id,committed_at,
                       raw_file,record_count) VALUES(?,?,?,?,?,?)""",
                    (checkpoint_name, page, run_id, utc_now(), str(raw_file), len(rows)),
                )
                connection.execute(
                    """INSERT INTO checkpoints(checkpoint_name,next_page,updated_at,last_run_id)
                       VALUES(?,?,?,?) ON CONFLICT(checkpoint_name) DO UPDATE SET
                       next_page=excluded.next_page,updated_at=excluded.updated_at,last_run_id=excluded.last_run_id""",
                    (checkpoint_name, page + 1, utc_now(), run_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            # Run totals are updated only after the page commits, so a rolled-back page is never counted.
            records_fetched += len(rows)
            accepted += page_accepted
            rejected += page_rejected
            published += page_published
            skipped += page_skipped
            pages_fetched += 1
            logger.info("run_id=%s page=%s fetched=%s accepted=%s rejected=%s skipped_existing=%s",
                        run_id, page, len(rows), page_accepted, page_rejected, page_skipped)
            has_more = bool(payload.get("has_more"))
            page += 1
            if not has_more:
                break
        ended_at = utc_now()
        connection.execute(
            """UPDATE pipeline_runs SET ended_at=?,status=?,pages_fetched=?,records_fetched=?,
               accepted_count=?,rejected_count=?,published_count=?,skipped_existing_count=? WHERE run_id=?""",
            (ended_at, "success", pages_fetched, records_fetched, accepted, rejected, published,
             skipped, run_id),
        )
        connection.commit()
        export_parquet(connection, Path(paths["parquet_dir"]))
        report = {
            "run_id": run_id, "status": "success", "started_at": started_at, "ended_at": ended_at,
            "pages_fetched": pages_fetched, "records_fetched": records_fetched,
            "accepted_count": accepted, "rejected_count": rejected, "published_count": published,
            "skipped_existing_count": skipped,
            "reconciles": records_fetched == accepted + rejected + skipped,
            "next_page": page,
        }
        report_path = Path(paths["reports_dir"]) / f"run_{run_id}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    except Exception as exc:
        connection.execute(
            """UPDATE pipeline_runs SET ended_at=?,status=?,pages_fetched=?,records_fetched=?,
               accepted_count=?,rejected_count=?,published_count=?,skipped_existing_count=?,
               error_message=? WHERE run_id=?""",
            (utc_now(), "failed", pages_fetched, records_fetched, accepted, rejected, published,
             skipped, f"{type(exc).__name__}: {exc}", run_id),
        )
        connection.commit()
        logger.exception("run_id=%s ingestion failed at page=%s", run_id, page)
        raise
    finally:
        client.close()
        connection.close()


def export_parquet(connection, output_dir: Path) -> Path:
    import pandas as pd
    rows = connection.execute(
        """SELECT order_id,customer_id,amount,currency,status,event_time,updated_at,
                  source_page,source_run_id FROM orders ORDER BY order_id"""
    ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows], columns=[
        "order_id", "customer_id", "amount", "currency", "status", "event_time", "updated_at",
        "source_page", "source_run_id"
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "orders.parquet"
    frame.to_parquet(target, index=False)
    return target