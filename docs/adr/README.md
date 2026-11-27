# Architecture decisions

Each record says what had to be decided, the options, the choice and what it costs. Short on purpose.

| # | Decision | Status |
|---|---|---|
| [0001](0001-kafka-kraft.md) | Kafka in KRaft mode, one node | accepted |
| [0002](0002-medallion-layers.md) | Bronze, Silver, Gold (Bronze: one folder per replay) | accepted |
| [0003](0003-real-data-skillcorner.md) | Real SkillCorner tracking data instead of generated data | accepted |
| [0004](0004-one-row-per-second.md) | One position per second (1 Hz), not 10 Hz | accepted |
| [0005](0005-replay-id-complete-partial.md) | Every replay has an id; only complete replays are stored | accepted |
