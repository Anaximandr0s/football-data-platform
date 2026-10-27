# data_gen (Phase 1-2 · Person A)

```bash
pip install -r data_gen/requirements.txt
python -m data_gen.ingest_foot --source sim --match m001 --seed 42     # -> data/generated/m001/*.parquet
python -m data_gen.producer_foot --match m001 --speed 30               # replay into Kafka (x1..x60)
python -m data_gen.producer_foot --match m001 --speed 60 --dry-run     # no Kafka needed
python kafka/bronze_writer.py                                          # Kafka -> MinIO bronze
pytest                                                                 # generator tests
```
Optional real match (see `docs/data-sources.md`):
```bash
python scripts/download_skillcorner.py 1925299
python -m data_gen.ingest_foot --source skillcorner --match m002 --sc-id 1925299
```
Files: `sim.py` (simulator), `skillcorner.py` (real-data converter + pseudonymisation), `ingest_foot.py`, `producer_foot.py`, `common.py` (schemas).
