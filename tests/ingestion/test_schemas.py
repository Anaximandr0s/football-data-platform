"""Tests of the contract in code: config.py and schemas.py agree with each other."""

from ingestion.config import KEYS, TOPICS
from ingestion.schemas import SCHEMAS, bronze_schema


def test_every_table_has_a_topic_and_a_message_key_that_is_a_column():
    assert set(TOPICS) == set(SCHEMAS) == set(KEYS)
    for table, schema in SCHEMAS.items():
        assert KEYS[table] in schema.names


def test_bronze_adds_the_five_kafka_columns_last():
    for table in SCHEMAS:
        assert bronze_schema(table).names[-5:] == [
            "kafka_partition",
            "kafka_offset",
            "kafka_ts",
            "ingested_at",
            "kafka_replay_id",
        ]
