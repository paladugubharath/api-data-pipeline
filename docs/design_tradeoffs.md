# Design and trade-offs

1. **SQLite instead of a managed warehouse:** zero credentials, easy local review, and transactions make page-level commits straightforward. It is not intended for concurrent high-volume writers.
2. **Parquet target export:** columnar output demonstrates an analytical consumer path. SQLite remains the transactional source of truth; Parquet is rebuilt after a successful run.
3. **Raw response retention:** every fetched page is saved as the complete response envelope (`data/output/raw/<run_id>/page_*.json`). Raw data is retained even when individual records are rejected.
4. **Retry policy:** bounded retries with exponential backoff for network errors, HTTP 429, and 5xx. Authentication and schema errors fail fast.
5. **Idempotency:** primary key on `order_id`. An identical replay is skipped and counted in `skipped_existing_count`; a conflicting payload for an existing key goes to quarantine (first version wins). The page checkpoint moves only in the same transaction as the target, quarantine and page-ledger writes, so a failed page never advances it.
6. **Late and out-of-order data:** records are not filtered by event time or arrival order, so a valid record with a new `order_id` is accepted whenever it arrives, and the final target does not depend on arrival order (covered by a test). **Limitation:** a later version of an *existing* order (for example a newer `updated_at` or a changed `status`) is quarantined as a conflict and is not applied, so the target does not track order updates. Quarantine keeps the rejected version for traceability. Next step: keep an immutable `order_events` history table and apply a newer `updated_at` explicitly.
7. **Schema drift:** unknown response envelope fields fail the run. Unknown record fields are rejected by strict Pydantic validation and quarantined. This makes drift visible instead of silently dropping fields.
8. **Secrets:** the token is read from the environment; `.env` is ignored by Git. The mock's default token is only for local demonstration.
9. **Scope limitation:** no external secret manager, distributed scheduler, exactly-once guarantee across filesystem and database, or multi-tenant support. A raw-file write and the SQLite commit cannot share one atomic transaction.

## Performance

**Method.** A 100,000-record dataset (`--seed 42 --no-edge-cases`), 250 records per page (400 pages), request pacing of 20 requests per second. Run time is `ended_at - started_at` from the run report; `Measure-Command` also includes Python startup. Evidence is in `evidence/large_run/`.

| Run | Mock API data loading | Run time | Throughput |
|---|---|---|---|
| Baseline 1 | parses the data file on every request | 137.6 s | 727 rows/s |
| Baseline 2 | same | 105.9 s | 944 rows/s |
| After 1 | parsed file cached | 26.4 s | 3,783 rows/s |
| After 2 | same | 29.7 s (`Measure-Command`; run report not read) | about 3,400 rows/s |

Output is identical before and after: `target_rows` 100,000, `target_amount_sum` 248,771,901.52, `source_reconciles` true, `unexplained_records` 0.

**Where the time went.** A cProfile of the first 40 pages (16.2 s, measured against the original server): about 9.2 s (57%) waiting for the API to respond, about 1.0 s (6%) rate-limit sleeps, and about 0.4 s (2%) for SQLite (42 commits and about 20,000 statements). Python startup and imports account for most of the rest. The pipeline's own database work was not the bottleneck.

**Optimization.** The mock API re-read and re-parsed the whole data file on every request, about 0.23 s per page. It now parses the file once and reloads it only when the file's path, modification time or size changes. The run got about 4 to 5 times faster. This speeds up the *source simulator*, not the pipeline code, and I report it for that reason: it is what the measurement pointed to.

**Not done, and why.** Batching inserts with `executemany` would save at most a second or so of a 26 s run, so it isn't justified. At 20 requests per second, 400 requests cannot finish in under about 20 s, and the after-runs are close to that floor. My inference is that request pacing is now the main cost; I did not measure it by raising the rate limit.

**Storage comparison.** The same count and sum per status on the same 100,000 rows: SQLite 0.195 s, Parquet 0.033 s (results match). On the 93-row starter sample SQLite is faster (0.0025 s against 0.0063 s). Each figure is a single run and varies between runs.
