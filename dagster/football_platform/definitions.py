"""The Dagster code location of the platform (dagster/workspace.yaml). Guide: dagster/README.md."""

import dagster as dg
from dagster_dbt import DbtCliResource

from football_platform import assets, sensors

defs = dg.Definitions(
    assets=[assets.bronze, assets.silver, assets.gold, assets.match_report],
    asset_checks=[assets.soda_silver, assets.soda_gold],
    jobs=[sensors.match_pipeline, sensors.nightly_quality],
    sensors=[sensors.replay_end, sensors.run_log_success, sensors.run_log_failure],
    schedules=[sensors.nightly],
    resources={"dbt": DbtCliResource(project_dir=str(assets.DBT_DIR), profiles_dir=str(assets.DBT_DIR))},
)
