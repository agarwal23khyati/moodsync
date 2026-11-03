# MoodSync results (MOCK RUN - do not publish)

## Test environment (fills Section IV-A placeholders)

CPU: Intel(R) Xeon(R) Processor @ 2.10GHz | RAM: 3.9 GB | OS: Linux 6.18.44-fc-v139 | Python 3.12.3 | FastAPI 0.143.3 | Uvicorn 0.54.0 | PyMongo 4.19.0 | Pydantic 2.14.1 | pandas 3.0.2 | test framework: pytest 9.1.1 | DB: mongomock (in-memory, NOT a real MongoDB)

## Table II - functional and integration results

| Metric | Result |
|---|---|
| Outfit re-ranking, mood/occasion change | 100% (24/24) |
| Worn-count penalty (no repeat in 3 cycles) | 94% (47/50) |
| Referential integrity (outfits -> items/mood logs, 500 outfits, 15 items deleted) | 0 orphans |
| Task analytics vs independent oracle | 100% (100/100) |
| Music agent checks | 100% (12/12) |
| Recipe agent checks | 100% (101/101) |
| Inter-service payload (Coordinator -> agents), clean responses | 100% (200/200); schema mismatches: 0 |
| Mean round-trip latency (50 runs, after 3 warm-up) | 12.2 ms (median 11.8, p95 14.0, max 15.9) |
| Usability: wizard completed unaided | FILL FROM YOUR REAL USER STUDY (see docs/USABILITY_PROTOCOL.md) |

## Simulation: shared mood context vs siloed modules

200 simulated users x 30 rounds. rho = how much a user's hidden taste deviates from the population rules.

| rho | siloed | shared context | shared + feedback | shared - siloed (paired, 95% CI) | learning gain (paired, 95% CI) |
|---|---|---|---|---|---|
| 0.25 | 0.591 +/- 0.009 | 0.722 +/- 0.007 | 0.714 +/- 0.008 | +0.132 +/- 0.006 | -0.009 +/- 0.004 |
| 0.5 | 0.576 +/- 0.009 | 0.662 +/- 0.008 | 0.657 +/- 0.008 | +0.086 +/- 0.006 | -0.005 +/- 0.005 |
| 0.75 | 0.570 +/- 0.009 | 0.609 +/- 0.010 | 0.615 +/- 0.008 | +0.039 +/- 0.007 | +0.006 +/- 0.006 |

Mood entries per session: siloed = 4 (one per module), shared = 1 (by design, not measured).

Details: styling-case failures: []
; worn-penalty failed trials: [2, 6, 32]; recipe/music failures: [] []