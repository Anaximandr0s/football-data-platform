# Contributing

- One branch per change (`type/short-description`), merged by pull request.
- A change to a table or column updates `SCHEMAS` in `ingestion/schemas.py` and `docs/contrat_donnees.md` together.
- Before pushing: `make lint` and `make test` (and `make smoke` if you touched `docker-compose.yml`).
- Never commit `.env`, `data/raw/`, `data/prepared/` or any Parquet or JSONL file.
- Python packages go in `requirements.txt`.
- Update the docs in the same pull request as the change.
- Adding a match: see `docs/data-sources.md`.
