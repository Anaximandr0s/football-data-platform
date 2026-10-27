# Working together

## Branches
- `main`: always runs with `docker compose up -d`. Never push directly.
- `feat/a-<topic>` (Person A) and `feat/b-<topic>` (Person B).
- Open a PR, the **other person reviews**. This forces both of you to understand the whole platform.

## Commits
Small and frequent. Prefix: `feat:`, `fix:`, `docs:`, `chore:`, `test:`.

## Ownership (avoid merge conflicts)
- A owns: `data_gen/`, `kafka/`, `spark/`
- B owns: `dbt/`, `soda/`, `dagster/`, `app/`
- Shared (PR only): `docker-compose.yml`, `README.md`, `docs/contrat_donnees.md`, `.env.example`

## Definition of done
1. Runs with `docker compose` (or documented command in the folder README)
2. Documented (folder README + requirement coverage updated with proof)
3. Reviewed by the other person

## Local setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
```

## Rituals
- 10 min sync at the start of each session: what I deliver / what I need from you.
- 30 min knowledge swap before the defence: A explains Silver, B explains Gold + Dagster.
