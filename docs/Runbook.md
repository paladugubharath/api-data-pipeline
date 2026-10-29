# API Data Ingestion Pipeline — Runbook

## 1. Prerequisites

- Python 3.10 or newer
- Git
- Two terminal windows

## 2. Clone the Repository

```bash
git clone <repository-url>
cd <project-folder>
```

Run all commands from the project root containing `pyproject.toml`.

## 3. Install Dependencies

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 4. Configure the Project

The default configuration is in `config/config.yaml`.

Default API URL:

```text
http://127.0.0.1:8000
```

The default client and mock API token is `local-demo-token`.

If you change the token, set the same value for `API_TOKEN` and `MOCK_API_TOKEN`.

**Windows (PowerShell):**

```powershell
$env:API_TOKEN = "my-token"
$env:MOCK_API_TOKEN = "my-token"
```

**macOS / Linux:**

```bash
export API_TOKEN=my-token
export MOCK_API_TOKEN=my-token
```

## 5. Start the Mock API

Open **Terminal 1**, activate the virtual environment, and run:

```bash
python -m pipeline.cli serve --host 127.0.0.1 --port 8000
```

Keep the server running.

## 6. Generate Data and Run the Pipeline

Open **Terminal 2** in the project root and activate the virtual environment.

Generate 100 sample records:

```bash
python -m pipeline.cli generate --count 100 --seed 42 --output data/sample/orders.json
```

Restart the mock API server after generating new data.

Run ingestion:

```bash
python -m pipeline.cli ingest
```

Run reconciliation:

```bash
python -m pipeline.cli reconcile
```

Run the benchmark:

```bash
python -m pipeline.cli benchmark-cmd
```

Run the tests:

```bash
python -m pytest -rA
```

## 7. Verify the Results

For the default 100-record test dataset, the expected results are:

- Accepted records: `93`
- Rejected records: `6`
- Skipped existing records on the first run: `1`
- Target rows: `93`
- Unexplained records: `0`
- Duplicate target keys: `0`
- Automated tests: `21 passed`

Check the output files:

- `data/output/pipeline.db`
- `data/output/raw/`
- `data/output/parquet/orders.parquet`
- `reports/`
- `evidence/` (if test evidence is included)

Actual results may vary if you use different data or existing output files.

## 8. Test the API (Optional)

You can use Thunder Client in VS Code.

**Method:** `GET`

**URL:**

```text
http://127.0.0.1:8000/v1/orders?page=1&page_size=5
```

Configure the required authentication header if needed, then click **Send**.

## 9. Troubleshooting

- **`No module named pipeline`:** Activate the virtual environment and run `python -m pip install -e ".[dev]"` again.
- **Connection refused:** Check that the mock API server is running.
- **`401 Unauthorized`:** Check that `API_TOKEN` and `MOCK_API_TOKEN` match.
- **Port 8000 is busy:** Start the server on port 8001 and set `API_BASE_URL` to `http://127.0.0.1:8001` in Terminal 2.
- **Unexpected results:** Check the input data and existing output files before rerunning.

For additional details, see the project README and documentation in `docs/`.



