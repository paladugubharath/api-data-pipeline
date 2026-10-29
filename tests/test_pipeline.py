import json
from pathlib import Path
import pytest
import httpx
from pipeline.db import connect
from pipeline.generator import generate_records, write_dataset
from pipeline.ingestion import run_ingestion
from pipeline.reporting import reconciliation
import pipeline.mock_api as mock


def _write_source(records):
    Path(mock.DATA_FILE).write_text(json.dumps(records), encoding="utf-8")


def test_happy_path_and_parquet(local_env):
    result = run_ingestion(local_env)
    assert result["status"] == "success"
    assert result["records_fetched"] == 30
    assert result["published_count"] == 30
    assert (Path(local_env["paths"]["parquet_dir"]) / "orders.parquet").exists()
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 30
    db.close()


def test_empty_input(local_env):
    Path(mock.DATA_FILE).write_text("[]", encoding="utf-8")
    result = run_ingestion(local_env)
    assert result["records_fetched"] == 0
    assert result["published_count"] == 0


def test_invalid_records_are_quarantined(local_env):
    records = generate_records(15, seed=7, include_edge_cases=True)
    Path(mock.DATA_FILE).write_text(json.dumps(records), encoding="utf-8")
    result = run_ingestion(local_env)
    assert result["rejected_count"] >= 5
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] >= 5
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] < 15
    db.close()


def test_retry_after_transient_failure(local_env):
    mock.STATE["fail_once_pages"].add(2)
    result = run_ingestion(local_env)
    assert result["status"] == "success"
    assert result["records_fetched"] == 30


def test_rate_limit_retry(local_env):
    mock.STATE["rate_limit_every"] = 2
    result = run_ingestion(local_env)
    assert result["status"] == "success"
    assert result["records_fetched"] == 30


def test_rerun_same_input_is_idempotent(local_env):
    first = run_ingestion(local_env)
    # New full replay explicitly starts at page one; duplicate rows are skipped.
    second = run_ingestion(local_env, start_page=1)
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 30
    assert second["published_count"] == 0
    db.close()


def test_persistent_failure_preserves_checkpoint(local_env):
    first = run_ingestion(local_env, max_pages=1)
    assert first["next_page"] == 2
    mock.STATE["always_fail_pages"].add(2)
    with pytest.raises(Exception):
        run_ingestion(local_env)
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT next_page FROM checkpoints WHERE checkpoint_name='orders'").fetchone()[0] == 2
    assert db.execute("SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0] == "failed"
    db.close()


def test_authentication_required(local_env):
    with httpx.Client() as client:
        response = client.get("http://127.0.0.1:8765/v1/orders", params={"page": 1})
    assert response.status_code == 401


def test_unexpected_api_schema_fails_loudly(local_env):
    mock.STATE["schema_change_page"] = 1
    with pytest.raises(ValueError, match="Unexpected API response schema"):
        run_ingestion(local_env)
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0] == "failed"
    db.close()


def test_null_required_field_is_quarantined(local_env):
    records = generate_records(12, seed=11, include_edge_cases=False)
    records[0]["customer_id"] = None
    Path(mock.DATA_FILE).write_text(json.dumps(records), encoding="utf-8")
    result = run_ingestion(local_env)
    assert result["rejected_count"] == 1
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM quarantine WHERE reason LIKE '%customer_id%'").fetchone()[0] == 1
    db.close()


# ---- New tests: duplicates, domain edge cases, raw retention, reconciliation ----

def test_replay_counts_skipped_existing_and_reconciles(local_env):
    first = run_ingestion(local_env)
    second = run_ingestion(local_env, start_page=1)
    assert first["skipped_existing_count"] == 0
    assert second["accepted_count"] == 0
    assert second["skipped_existing_count"] == 30
    assert second["reconciles"] is True
    result = reconciliation(local_env["paths"]["database"])
    assert result["target_rows"] == 30
    assert result["source_reconciles"] is True
    assert result["unexplained_records"] == 0


def test_identical_duplicate_in_source_is_skipped_and_counted(local_env):
    records = generate_records(12, seed=5, include_edge_cases=False)
    records.append(dict(records[0]))
    _write_source(records)
    result = run_ingestion(local_env)
    assert result["records_fetched"] == 13
    assert result["accepted_count"] == 12
    assert result["skipped_existing_count"] == 1
    assert result["rejected_count"] == 0
    assert result["reconciles"] is True
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 12
    db.close()


def test_conflicting_duplicate_is_quarantined_first_version_wins(local_env):
    records = generate_records(12, seed=5, include_edge_cases=False)
    original_amount = records[0]["amount"]
    conflict = dict(records[0])
    conflict["amount"] = original_amount + 1
    records.append(conflict)
    _write_source(records)
    result = run_ingestion(local_env)
    assert result["accepted_count"] == 12
    assert result["rejected_count"] == 1
    assert result["skipped_existing_count"] == 0
    db = connect(local_env["paths"]["database"])
    rows = db.execute("SELECT reason, source_page, record_index FROM quarantine").fetchall()
    assert len(rows) == 1
    assert "conflicting payload" in rows[0][0]
    assert rows[0][1] is not None and rows[0][2] is not None  # traceable to source
    stored = db.execute("SELECT amount FROM orders WHERE order_id=?", (records[0]["order_id"],)).fetchone()[0]
    assert stored == pytest.approx(original_amount)
    db.close()


def test_zero_amount_boundary_is_accepted(local_env):
    records = generate_records(12, seed=3, include_edge_cases=False)
    records[0]["amount"] = 0.0
    _write_source(records)
    result = run_ingestion(local_env)
    assert result["rejected_count"] == 0
    db = connect(local_env["paths"]["database"])
    stored = db.execute("SELECT amount FROM orders WHERE order_id=?", (records[0]["order_id"],)).fetchone()[0]
    assert stored == 0.0
    db.close()


def test_negative_amount_is_quarantined(local_env):
    records = generate_records(12, seed=3, include_edge_cases=False)
    records[0]["amount"] = -1.0
    _write_source(records)
    result = run_ingestion(local_env)
    assert result["rejected_count"] == 1
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM quarantine WHERE reason LIKE '%amount%'").fetchone()[0] == 1
    db.close()


def test_unknown_customer_is_quarantined_when_reference_set_supplied(local_env):
    records = generate_records(12, seed=3, include_edge_cases=False)
    known = {r["customer_id"] for r in records}
    records[0]["customer_id"] = "cust_999999"  # well-formed but not a known customer
    _write_source(records)
    result = run_ingestion(local_env, known_customers=known)
    assert result["rejected_count"] == 1
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 11
    assert db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 1
    db.close()


def test_unexpected_record_field_is_quarantined(local_env):
    records = generate_records(12, seed=3, include_edge_cases=False)
    records[0]["extra_surprise"] = "unexpected schema field"
    _write_source(records)
    result = run_ingestion(local_env)
    assert result["rejected_count"] == 1
    db = connect(local_env["paths"]["database"])
    assert db.execute("SELECT COUNT(*) FROM quarantine WHERE reason LIKE '%extra_surprise%'").fetchone()[0] == 1
    db.close()


def test_raw_responses_are_retained_per_page(local_env):
    result = run_ingestion(local_env)
    raw_files = sorted((Path(local_env["paths"]["raw_dir"]) / result["run_id"]).glob("page_*.json"))
    assert len(raw_files) == 3
    payload = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert payload["page"] == 1
    assert len(payload["data"]) == 10


def test_reconciliation_balances_with_bad_and_duplicate_records(local_env):
    _write_source(generate_records(15, seed=7, include_edge_cases=True))
    run_ingestion(local_env)
    result = reconciliation(local_env["paths"]["database"])
    assert result["source_reconciles"] is True
    assert result["unexplained_records"] == 0
    assert result["target_matches_accepted"] is True
    assert result["duplicate_target_keys"] == 0

def test_out_of_order_arrival_does_not_change_final_target(local_env):
    records = generate_records(12, seed=9, include_edge_cases=False)
    _write_source(list(reversed(records)))  # newest-looking records arrive first
    result = run_ingestion(local_env)
    assert result["accepted_count"] == 12
    assert result["rejected_count"] == 0
    db = connect(local_env["paths"]["database"])
    stored = {row[0] for row in db.execute("SELECT order_id FROM orders")}
    assert stored == {r["order_id"] for r in records}
    total = db.execute("SELECT SUM(amount) FROM orders").fetchone()[0]
    assert total == pytest.approx(sum(r["amount"] for r in records))
    db.close()


def test_later_version_of_existing_order_is_quarantined_not_applied(local_env):
    records = generate_records(12, seed=9, include_edge_cases=False)
    later = dict(records[0])
    later["status"] = "refunded" if records[0]["status"] != "refunded" else "paid"
    later["updated_at"] = "2030-01-01T00:00:00+00:00"
    _write_source(records + [later])
    result = run_ingestion(local_env)
    assert result["accepted_count"] == 12
    assert result["rejected_count"] == 1
    db = connect(local_env["paths"]["database"])
    status = db.execute("SELECT status FROM orders WHERE order_id=?", (records[0]["order_id"],)).fetchone()[0]
    assert status == records[0]["status"]
    reason = db.execute("SELECT reason FROM quarantine").fetchone()[0]
    assert "conflicting payload" in reason
    db.close()