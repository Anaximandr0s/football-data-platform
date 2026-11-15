"""session.py: build the SparkSession (S3A on MinIO, Iceberg Hadoop catalog on the silver bucket)."""
from pyspark.sql import SparkSession

from spark.silver import config


def build_spark(app_name: str = "bronze_to_silver", packages: str | None = None,
                iceberg: bool = True) -> SparkSession:
    """`packages`: comma separated Maven coordinates ("" = none, e.g. local files only).
    `iceberg=False` (dry run) skips the catalog, so no Iceberg jar is needed."""
    packages = config.PACKAGES if packages is None else packages
    b = (SparkSession.builder.appName(app_name)
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.ui.showConsoleProgress", "false")
         .config("spark.hadoop.fs.s3a.endpoint", config.S3_ENDPOINT_URL)
         .config("spark.hadoop.fs.s3a.path.style.access", "true")
         .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
         .config("spark.hadoop.fs.s3a.access.key", config.S3_USER)
         .config("spark.hadoop.fs.s3a.secret.key", config.S3_PASSWORD))
    if packages:
        b = b.config("spark.jars.packages", packages)
    if iceberg:
        cat = f"spark.sql.catalog.{config.CATALOG}"
        b = (b.config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
             .config(cat, "org.apache.iceberg.spark.SparkCatalog")
             .config(f"{cat}.type", "hadoop")
             .config(f"{cat}.warehouse", config.WAREHOUSE))
    spark = b.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
