"""Shared fixture: one small local SparkSession for the Silver tests (no Docker, no MinIO, no Iceberg).

The tests are skipped, not failed, on a machine without pyspark or without Java.
"""
import shutil

import pytest


@pytest.fixture(scope="session")
def spark():
    pytest.importorskip("pyspark")
    if shutil.which("java") is None:
        pytest.skip("Java is needed to run Spark")
    from pyspark.sql import SparkSession

    session = (SparkSession.builder.master("local[1]").appName("silver-tests")
               .config("spark.sql.shuffle.partitions", "1")
               .config("spark.ui.enabled", "false")
               .config("spark.sql.session.timeZone", "UTC")
               .getOrCreate())
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()
