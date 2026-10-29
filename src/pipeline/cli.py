from __future__ import annotations
import json
import logging
from pathlib import Path
import typer
import uvicorn
from .config import load_config
from .generator import write_dataset
from .ingestion import run_ingestion
from .reporting import reconciliation, benchmark

app = typer.Typer(help="Reliable API data ingestion demo")


@app.command()
def generate(count: int = 100, seed: int = 42, output: str = "data/sample/orders.json",
             edge_cases: bool = True):
    """Generate reproducible synthetic order records."""
    path = write_dataset(output, count, seed, edge_cases)
    typer.echo(f"Wrote {count} records to {path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Start the local mock API."""
    uvicorn.run("pipeline.mock_api:app", host=host, port=port, reload=False)


@app.command()
def ingest(config_path: str = "config/config.yaml", max_pages: int | None = None,
           start_page: int | None = None):
    """Run ingestion using configured API and storage paths."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(config_path)
    result = run_ingestion(config, start_page=start_page, max_pages=max_pages)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def reconcile(config_path: str = "config/config.yaml"):
    """Write reconciliation output and print it."""
    config = load_config(config_path)
    path = config["paths"]["database"]
    output = str(Path(config["paths"]["reports_dir"]) / "reconciliation.json")
    result = reconciliation(path, output)
    typer.echo(json.dumps(result, indent=2))


@app.command()
def benchmark_cmd(config_path: str = "config/config.yaml"):
    """Benchmark basic SQLite count and Parquet read."""
    config = load_config(config_path)
    result = benchmark(
        config["paths"]["database"],
        str(Path(config["paths"]["parquet_dir"]) / "orders.parquet"),
        str(Path(config["paths"]["reports_dir"]) / "benchmark.json"),
    )
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
