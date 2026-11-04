# Windows setup

Two ways. Option A is easier because the README then works unchanged.

## Option A (recommended): WSL2

1. Install Docker Desktop and turn on "Use the WSL 2 based engine" and the integration for your Ubuntu distribution.
2. Open the Ubuntu terminal and clone the repository inside the Linux filesystem (`~/football-data-platform`),
   not under `/mnt/c` (it is much slower there).
3. Follow the Quick start of the README as it is written, `make` included.

## Option B: PowerShell, without make

Needs Docker Desktop (running), Git and Python 3.11+.

```powershell
git clone https://github.com/Anaximandr0s/football-data-platform.git
cd football-data-platform
Copy-Item .env.example .env                  # then change MINIO_ROOT_PASSWORD
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1                 # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

docker compose up -d
python scripts\smoke_test.py                 # must end with ALL OK

python -m ingestion.download_foot 1874553
python -m ingestion.ingest_foot --match m001 --sc-id 1874553
python -m ingestion.download_foot 1925299
python -m ingestion.ingest_foot --match m002 --sc-id 1925299
```

Then two terminals (both with the virtual environment activated):

```powershell
# terminal 1: Kafka -> MinIO bronze (leave running)
python -m ingestion.bronze_writer

# terminal 2: replay, then verify (about 100 s per match)
python -m ingestion.producer_foot --match m001 --speed 60
python -m ingestion.producer_foot --match m002 --speed 60
python -m ingestion.check_bronze --match m001
python -m ingestion.check_bronze --match m002
```

Other commands: `docker compose down` (keep data), `docker compose down -v` (**deletes all data**),
`python -m pytest -q`, `ruff check .`.

## Notes

- `make` is optional. If you want it, install it with your package manager (for example `choco install make`).
- Line endings: the repository forces LF (`.gitattributes`); keep your editor on LF.
- Spark on native Windows is painful (it needs Hadoop helper binaries). Run Spark in WSL2 or in a Docker
  container instead.