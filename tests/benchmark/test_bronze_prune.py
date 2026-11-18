"""bronze_prune.plan: which Bronze files are deleted, never the replay Silver reads."""
import bronze_prune as bp

R = "tracking/match_id=m001/replay_id={}/ingest_date=2026-11-17/part-1-1.parquet"


def test_the_last_complete_replays_and_the_newer_ones_stay_the_rest_goes():
    replays = ["m001-20261117T090000Z", "m001-20261117T100000Z", "m001-20261117T110000Z", "m001-20261117T120000Z",
               "m001-20261117T130000Z"]
    objects = {R.format(r): 10 for r in replays}
    objects["tracking/match_id=m001/ingest_date=2026-11-16/part-1-1.parquet"] = 5          # old layout
    objects[R.format("none")] = 1
    complete = {"m001-20261117T090000Z", "m001-20261117T100000Z", "m001-20261117T110000Z"}  # 12:00, 13:00 stopped
    out = bp.plan(objects, lambda m, r: r in complete, keep=2)
    kept = {bp.parse(k)[2] for k in out["keep"]}
    assert kept == {"m001-20261117T130000Z", "m001-20261117T120000Z", "m001-20261117T110000Z",
                    "m001-20261117T100000Z"}                     # 2 complete (11:00, 10:00) + the newer ones
    assert {bp.parse(k)[2] for k in out["delete"]} == {"m001-20261117T090000Z", None, "none"}


def test_keys_outside_the_layout_are_never_deleted():
    objects = {"tracking/README.txt": 1, R.format("m001-20261117T090000Z"): 10}
    out = bp.plan(objects, lambda m, r: True, keep=1)
    assert out == {"keep": ["tracking/README.txt", R.format("m001-20261117T090000Z")], "delete": []}
