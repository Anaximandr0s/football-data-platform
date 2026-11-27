# Contributing

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # Python 3.11+, Java 17 for the Spark tests
make ci                             # lint, tests with coverage, config checks (Docker needed for the last)
```

The Soda tests need their own environment (Soda Core pins an older DuckDB); CI runs them in the `soda` job.
`make build` builds every Docker image, as the `docker` job does.

## Making a change

- One branch per change, named `type/short-description` (`feat/`, `fix/`, `docs/`, `ci/`, ...), merged by pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org): `type(scope): subject`.
- CI must pass: lint, tests, Soda tests, combined coverage of at least 90 %, config checks and image builds.
- Add or update tests with the behaviour you change. Tests run without Docker: Kafka, S3 and HTTP are replaced
  by small fakes, Spark and DuckDB run for real.
- A change to a table or column updates `SCHEMAS` in `ingestion/schemas.py` and `docs/contrat_donnees.md` together.
- Update the docs in the same pull request as the change.
- Never commit `.env`, `data/raw/`, `data/prepared/` or any Parquet or JSONL file.

Adding a match: see `docs/data-sources.md`.

## Releases

Tags follow SemVer (`vMAJOR.MINOR.PATCH`). Pushing a tag runs CI on it, then publishes a GitHub release with notes
built from the merged pull requests.
