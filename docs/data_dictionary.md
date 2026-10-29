# Data dictionary

## Source entity: `orders` API records

**Grain:** one source order event/current order representation per `order_id` in this mock API. The assignment uses current-state order records, not a complete event log. If the real source exposes multiple events per order, use a separate immutable `order_events` table keyed by event ID.

| Field | Type | Required | Rules |
|---|---|---:|---|
| `order_id` | string | yes | Stable primary key; non-empty |
| `customer_id` | string | yes | Must match `cust_` plus six digits. Only the format is checked by default; an optional `known_customers` set enforces membership |
| `amount` | decimal-like number | yes | Non-negative (zero is accepted) |
| `currency` | string | yes | Three uppercase alphabetic characters |
| `status` | string | yes | created, paid, cancelled, refunded |
| `event_time` | ISO-8601 timestamp | yes | Time the business event occurred |
| `updated_at` | ISO-8601 timestamp | yes | Source update timestamp; records may arrive out of order |

Unknown extra fields on a record are rejected and quarantined.

## Target table: `orders`

The target mirrors validated source fields and adds `source_page`, `source_run_id` and `source_record_json` for lineage. `order_id` is the primary key. Amount is stored as SQLite REAL for demo simplicity; financial production systems should use integer minor units or a decimal type.

## Operational tables

- `pipeline_runs`: run ID, start/end timestamps, status, `pages_fetched`, `records_fetched`, `accepted_count`, `rejected_count`, `published_count`, `skipped_existing_count`, and the error message. For a finished run, `records_fetched = accepted_count + rejected_count + skipped_existing_count`.
- `checkpoints`: next page to request and the run that committed it.
- `page_commits`: page-level commit ledger and raw response path.
- `quarantine`: the rejected record as received, the reason, source page and record index, run ID and timestamp. It is an append-only audit log, so replaying a page adds rows again.

## Rules for duplicates and late data

- A repeated `order_id` with an identical payload is skipped and counted in `skipped_existing_count`.
- A repeated `order_id` with a different payload is quarantined as `duplicate order_id with conflicting payload`. The first accepted version stays in the target, so later updates to an existing order are not applied.
- A record with a new `order_id` is accepted whatever its `event_time` or position in the stream.

## Assumptions and limitations

- The mock API uses page-number pagination and a fixed synthetic snapshot. For mutable real APIs, prefer cursor-based pagination or source change tokens.
- Checkpointing is page-level. Target writes, quarantine writes, page ledger and checkpoint update commit in one SQLite transaction after the raw page is written.
- Raw response files are written before the database transaction. A failed transaction can leave an unreferenced raw file, which is safe and auditable but may need periodic cleanup.
- An interrupted process (for example Ctrl+C) leaves its run marked `running` with no end time, because only exceptions are recorded as `failed`.
- A production change-data-capture feed should store immutable events and apply explicit version ordering.