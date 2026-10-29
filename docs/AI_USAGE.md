# AI usage

I used ChatGPT and Claude while developing this project. This document explains how I used each tool, where AI helped most, and what I personally ran and verified.

## Tools

- **ChatGPT (OpenAI):** Used for code development, pipeline design, and creating the runbook.
- **Claude (Anthropic):** Used for the remaining project work, including additional development assistance, debugging, testing, performance analysis, and documentation.

## Where AI helped most

- **Initial implementation:** AI assistance was used to develop the pipeline code, tests, documentation, and README.
- **Code changes:** AI helped implement the `skipped_existing_count` counter and reconciliation checks in `ingestion.py`, `db.py`, and `reporting.py`. It also helped with the mock API cache in `mock_api.py`, the SQLite-versus-Parquet benchmark, and 11 of the 21 tests.
- **Documentation:** AI helped draft the README, `docs/design_tradeoffs.md`, `docs/data_dictionary.md`, and this file using the project results I provided.
- **Design and runbook:** ChatGPT helped with the pipeline design and runbook.
- **Debugging guidance:** AI suggested troubleshooting steps, helped explain errors, and provided guidance for running and testing the project.

## What I did and verified myself

I ran commands on my Windows machine and checked the actual outputs. I used these results to investigate issues and validate the implementation.

- **End-to-end pipeline:** Ran the mock API, ingestion, replay, reconciliation, and benchmark. I also inspected the quarantine table to check that the 6 rejected records matched the injected bad records.
- **Record-count reconciliation:** Investigated the difference between 100 source records and the 93 accepted plus 6 rejected records. I traced the remaining record to a repeated `order_id`, then checked the raw pages and target row to confirm that the two copies were identical. This led to the `skipped_existing_count` counter.
- **Idempotency:** Replayed the same input using `--start-page 1` and checked that `target_rows` remained at 93 with the same total amount.
- **Partial failure and restart:** Ran the `fail-always` demonstration with `page_size: 25`, inspected the failed run and checkpoint, and checked that the resumed run started at page 2.
- **Performance:** Ran the 100,000-record test before and after the optimization and profiled 40 pages. The profiling results indicated that the mock server, rather than the pipeline code, was the main bottleneck. I also checked that the output remained identical after the change. I did not accept the initial AI suggestion about per-row SQLite inserts because the profiling results did not support it.
- **Debugging:** Investigated a pytest 9 startup crash on Python 3.10.0 and pinned pytest to a version below 9. I also addressed environment issues involving a nested folder, an older mock server running stale code, and an interrupted run.
- **Tests:** The recorded final test output shows that all 21 tests passed in `evidence/pytest_output_final.txt`.

## What I did not fully verify

- I have not confirmed that every part of the validation and client-retry code was reviewed line by line.
- The ID formats and the generator's edge-case labelling were based on the sample data and existing code. These details should be checked against the implementation before making stronger claims.
- The performance figures came from runs on one machine and may vary. The reported improvement relates to the mock source, not necessarily to the pipeline code itself.
- Passing tests provides evidence that the tested cases work, but it does not prove that every possible case has been covered.
- The exact division of individual code changes between ChatGPT and Claude should not be claimed unless it can be confirmed from the available chat history.

## Design decisions I can explain

- **Duplicate handling:** The first version of an `order_id` is kept. A conflicting later version is quarantined rather than applied. This limitation is documented.
- **Page-level atomic commit:** A page is committed as a unit, so a failed page does not advance the checkpoint.
- **Performance optimization:** A mock API cache was used instead of batching database inserts because profiling showed that SQLite accounted for only about 2% of runtime.

## Summary

I used AI tools to accelerate development, understand errors, improve the implementation, prepare documentation, and investigate performance. I personally ran the project commands and examined the resulting outputs to validate the reported behavior. AI-generated suggestions were not treated as automatically correct; I used test results, reconciliation, and profiling to evaluate them.
