# ADR 0004: keep one position per second (1 Hz), not 10 Hz

- **Status:** accepted, 2026-11-04
- **Context:** SkillCorner gives 10 frames per second. Every row goes through Kafka, Bronze, Silver, Gold and the app.
- **Options:**
  1. Keep 10 Hz: the most detail, ten times the rows at every step.
  2. Keep 1 Hz (one frame in ten): the grain of every statistic we show.
- **Decision:** 1 Hz, done once at ingestion (`ingestion/config.py`, `FPS = 10`, one frame in `FPS` kept).
  - **Grain:** the app's statistics are per second or per window of minutes (distance, possession, pressing, 5-minute
    live stats); none needs a tenth of a second.
  - **Volume:** ten times fewer rows in Kafka, Bronze and Silver. At 1 Hz, m001 is 101,844 positions over 4,428 tracked
    seconds, 1.12 MB of JSON for the whole match in the browser (`docs/product.md`, section 8).
  - **Live page:** Streamlit redraws once per second, so a 10 Hz feed would show the same picture.
  - **Replay:** the browser plays the 1 Hz match smoothly by interpolating between seconds (never across a camera gap);
    measured at 60 frames per second (`app/streamlit/README.md`).
- **Consequences:** speeds come from positions one second apart, so top speeds and distances are under-estimates;
  the app labels them approximate. A sprint shorter than a second is not seen.
