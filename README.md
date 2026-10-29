# Reliable API Data Ingestion Pipeline

This project is a local, reproducible data engineering solution built for a take-home assignment. It demonstrates how to fetch data from a paginated API, handle authentication, retry failed requests, apply backoff, handle rate limits, save raw API responses, maintain checkpoints, validate data, quarantine invalid records, prevent duplicate writes, track operational metrics, reconcile records, run tests, and export data to Parquet.

## Architecture

```text
Synthetic JSON -> Local FastAPI mock (pagination/auth/429/5xx/schema drift)
                               |
                        httpx ingestion client
                     retries + backoff + pacing
                               |
                raw page JSON files (immutable per run)
                               |
               SQLite transaction per successfully fetched page
             /          |           |            \
         orders      quarantine   page ledger   checkpoint
             |
      Parquet analytical export + run/reconciliation reports
```

## Documentation

The following documents provide more information about the project:

- **Runbook:** `docs/RUNBOOK.md` — Explains how to install dependencies, configure the project, and run the pipeline.
- **Design Trade-offs:** `docs/design_tradeoffs.md` — Describes the main design decisions and the trade-offs involved.
- **Data Dictionary:** `docs/data_dictionary.md` — Describes the data fields used in the project.
- **AI Usage:** `docs/AI_USAGE.md` — Explains how ChatGPT and Claude were used during development and what I personally reviewed and validated.
- **AI Prompt History:** `docs/AI_PROMPT_HISTORY.md` — Contains the prompts used during AI-assisted development.
- **Test Evidence:** `evidence/` — Contains test output and supporting verification evidence.

## Requirements

- Python 3.10+
- An internet connection is not required after the dependencies have been installed.
- The project has been tested locally. Python 3.11 or 3.12 is recommended.

## Setup

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env  # optional; export variables in your shell as needed
```

The project configuration is stored in `config/config.yaml`. You can override the API settings using these environment variables: `API_BASE_URL`, `API_TOKEN`, `API_TIMEOUT_SECONDS`, `API_MAX_RETRIES`, `API_BACKOFF_SECONDS`, and `API_REQUESTS_PER_SECOND`.

Never commit real credentials to the repository.

## Run end-to-end

**Terminal 1:**

```bash
python -m pipeline.cli serve --host 127.0.0.1 --port 8000
```

**Terminal 2:**

```bash
python -m pipeline.cli generate --count 100 --seed 42 --output data/sample/orders.json
python -m pipeline.cli ingest
python -m pipeline.cli reconcile
python -m pipeline.cli benchmark-cmd
```

By default, the data generator adds several edge cases:

- A valid record with a zero amount
- An unknown customer reference
- A negative amount
- A missing field
- An unexpected record field
- A duplicate key
- A malformed timestamp
- An invalid status
- An out-of-order timestamp

These cases are labelled in the generator source and should be included in test runs.

The mock API allows you to configure a set of known customer references. To enforce referential integrity, pass a known customer set to `run_ingestion(..., known_customers=...)`. By default, the CLI checks the record structure and domain rules. The record with an invalid customer reference is rejected only when reference validation is enabled.

You can also run the pipeline directly from Python:

```python
from pipeline.config import load_config
from pipeline.ingestion import run_ingestion
result = run_ingestion(load_config())
print(result)
```

## Generate larger volume

```bash
python -m pipeline.cli generate --count 100000 --seed 42 --output data/sample/orders.json --no-edge-cases
python -m pipeline.cli ingest
```

For a full benchmark, use a fresh `data/output/pipeline.db` or reset the checkpoint and database first.

The mock API uses page-number pagination. You can configure the page size in `config/config.yaml`.

## Fault injection

You can use the mock API's control endpoints to simulate different failures. For example, run these commands with `curl`:

```bash
curl -X POST http://127.0.0.1:8000/__control/reset
curl -X POST http://127.0.0.1:8000/__control/fail-once/2
curl -X POST http://127.0.0.1:8000/__control/rate-limit-every/3
curl -X POST http://127.0.0.1:8000/__control/schema-change/1
```

To simulate a persistent failure, call ` /__control/fail-always/2`.

When a page fails, it is not committed to the database, and the checkpoint stays at that page. To remove the failure, call the reset endpoint and run ingestion again.

## Tests

```bash
pytest
pytest --cov=pipeline --cov-report=term-missing
```

The tests cover the successful ingestion path, an empty source, malformed or missing fields, duplicate and domain-invalid records, temporary failures and retries, rate limiting, idempotency on reruns, checkpoint preservation after persistent failures, authentication rejection, and unexpected response schemas.

## Outputs

- `data/output/pipeline.db`: Contains the target data and audit tables.
- `data/output/raw/<run_id>/page_*.json`: Stores the complete original API response for each page.
- `data/output/parquet/orders.parquet`: Contains the analytical target snapshot.
- `reports/run_<run_id>.json`: Contains metrics for each run.
- `reports/reconciliation.json`: Contains record counts, the aggregate amount, and target uniqueness information.
- `reports/benchmark.json`: Contains timing comparisons between SQLite counts and Parquet reads.

## Data quality and reconciliation

The counts in `pipeline_runs` are calculated per run and include explicit replays.

The `orders` table stores the current state of the data and uses a unique `order_id`. Because of this, reconciliation reports both the counts for individual runs and the final number of unique records in the target table.

The quarantine table preserves each rejected record, the reason for rejection, the run ID, the page number, and the record index.

You can use the following SQL queries to inspect the data:

```sql
SELECT status, COUNT(*) AS rows, ROUND(SUM(amount), 2) AS amount_sum
FROM orders GROUP BY status;

SELECT reason, COUNT(*) AS rejected_rows
FROM quarantine GROUP BY reason ORDER BY rejected_rows DESC;

SELECT COUNT(*) AS duplicate_keys
FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1);
```

## Idempotency, retries, and backfills

- **Retries:** Retries are limited to a configured number. The pipeline retries network errors, timeouts, HTTP 429 responses, and HTTP 5xx responses. Most HTTP 4xx errors fail immediately.
- **Raw data and transactions:** Each page is saved as a raw response before the target data is written. The target writes, quarantine records, page ledger, and checkpoint update are handled in a single SQLite transaction.
- **Reruns:** The pipeline resumes from `next_page`. Use `--start-page 1` to replay from the beginning. Identical records are ignored, while conflicting duplicate records are quarantined.
- **Backfills:** To process an earlier range of pages, use `--start-page N --max-pages M`. Make sure the source data has a stable page order. If the source changes while using offset or page-number pagination, records may be skipped or processed more than once.
- **Checkpoints:** Checkpoints are based on page numbers, not timestamps. A production incremental API should use a stable cursor, change token, or `updated_since` watermark with an overlap period and deduplication.

## Security

The project uses synthetic data only.

Authentication uses a bearer token read from the environment or configuration. The local demo token is not a production secret. The `.env` file is excluded from Git.

## Known limitations and next steps

- SQLite uses `REAL` for the `amount` field to keep the example simple. A financial system should use integer cents or `DECIMAL`.
- The mock API uses a static JSON snapshot and page-number pagination.
- Raw filesystem writes and SQLite commits are not part of a distributed transaction. Therefore, raw files may remain even if a database commit fails.
- After a successful run, the Parquet export rewrites the entire target snapshot.
- For larger workloads, possible improvements include batch inserts, partitioned Parquet files, structured metrics and alerts, integration with a secret manager, and integration tests against a source sandbox.


🙌 Author

PALADUGU BHARATH

linkedIn: https://www.linkedin.com/posts/paladugubharath