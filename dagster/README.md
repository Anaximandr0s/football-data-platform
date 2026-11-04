# dagster
Assets: bronze → silver (Spark) → dbt (`dagster-dbt`) → Soda asset checks → post-match report.
At least one schedule; a sensor on the final-whistle event; retries; idempotent runs.
