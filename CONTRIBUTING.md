# Contributing

- One branch per task (`feature/<what>`), merged by pull request, reviewed by the other person.
- The data contract (`docs/contrat_donnees.md` and `SCHEMAS` in `ingestion/schemas.py`) changes only by pull request that
  updates both and names the person to warn.
- Before pushing: `make lint` and `make test` (and `make smoke` if you touched `docker-compose.yml`).
- Never commit `.env`, `data/raw/`, `data/prepared/` or any Parquet or JSONL file.
- Python packages go in `requirements.txt` (one file, one commented section per phase).
- Update the docs in the same pull request as the change, and keep `docs/requirements-coverage.md` honest: a status needs a proof.
- Adding a match: see `docs/data-sources.md`.