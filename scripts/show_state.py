import sqlite3
c = sqlite3.connect("data/output/pipeline.db")
c.row_factory = sqlite3.Row
print("RUNS:")
for r in c.execute("select status, pages_fetched, records_fetched, accepted_count, rejected_count, skipped_existing_count, error_message from pipeline_runs order by started_at"):
    print("  ", dict(r))
row = c.execute("select checkpoint_name, next_page from checkpoints").fetchone()
print("CHECKPOINT:", dict(row) if row else None)
print("ORDERS IN TARGET:", c.execute("select count(*) from orders").fetchone()[0])
