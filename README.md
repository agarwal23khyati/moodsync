# MoodSync ✿ — Coordinator + 4 agents (FastAPI) on MongoDB

One mood check-in → the **Coordinator** logs it and sends it **concurrently** to four agents (Styling, Task, Music, Recipe) that share one database and one preference memory. All Python.

```
frontend/    website (HTML/CSS/JS, served by the Coordinator)
backend/
  main.py            Coordinator + REST API (port 8000): auth, CRUD, /api/context, /api/feedback, /api/suggest/*
  agent_service.py   the 4 agents as a separate FastAPI service (port 8001)
  agents.py          the agents' rule-based logic (pure functions - easy to test)
  feedback.py        accept/reject -> preference memory, wear tracking, cascade delete, integrity check
  common.py          MongoDB connection, $jsonSchema validators, indexes, seed recipes/tracks
  schemas.py         Pydantic contracts between the two services
experiments/         suite.py (every experiment) + run_experiments.py (tables, figures, paper text)
tests/               pytest (self-contained, in-memory DB)
results/             generated tables/figures (shipped copy = mock run, NOT for the paper)
docs/                PAPER_UPDATE.md, USABILITY_PROTOCOL.md
```

## Run it (Windows)
1. Install Python 3.10+ and MongoDB Community Server (as a service). Optional: Compass.
2. Double-click **START.bat** (opens two windows: the agent service and the Coordinator). Browser opens at http://localhost:8000.
   Mac/Linux: `bash START.sh`. API docs: http://localhost:8000/docs  (agents: http://localhost:8001/docs)
3. Online DB: put the Atlas string in `backend/.env` (`MONGO_URI=`). Deploying: the two services must both run; set `AGENT_URL` to the agent service URL.

## Get the paper numbers
1. Keep START.bat running (both windows).
2. Double-click **RUN_EXPERIMENTS.bat**. It signs up throw-away test users, runs everything against YOUR real MongoDB and writes
   `results/results.md`, `results/paper_text.md`, `results/fig5_results.png`, `results/fig6_simulation.png`, `results/results.json`.
3. Quick self-check without MongoDB: **RUN_TESTS.bat** (pytest). `python experiments/run_experiments.py --mock` runs the same suite on an in-memory DB (numbers are NOT for the paper).
4. Follow `docs/PAPER_UPDATE.md`; do the real user study in `docs/USABILITY_PROTOCOL.md`.

## What to show your DBMS faculty
| Concept | Where |
|---|---|
| 11 collections, references (`user_id`, `mood_log_id`, `outfits.item_ids`) | Compass |
| `$jsonSchema` validation | `VALIDATORS` in `common.py` |
| Indexes (unique, compound, multikey on `item_ids`) | `INDEXES` in `common.py`, `db.outfits.getIndexes()` |
| Aggregation + `$lookup` joins | `/api/stats/*`, `backend/queries.mongosh.js` #4-#17 |
| GridFS photos, upsert feedback, bcrypt + JWT | wardrobe upload, `/api/song_feedback`, `/api/auth/*` |
| Cascade delete + integrity check | `feedback.delete_wardrobe_item`, `orphan_outfit_count`, query #15 |

## What's new in v2
- **Music plays inside the app.** Mood radio queue (up to 30 songs/mood, 47 seeded) with a persistent player bar: play/pause, next/prev, seek, volume, shuffle, repeat, auto-next, ♡/skip, keyboard Space, lock-screen controls. Songs are 30-second iTunes previews (no key needed), looked up **once** by the Coordinator (`POST /api/music/resolve`) and cached in the `tracks` collection.
- **Add your own music:** paste a YouTube or Spotify link (song or playlist) -> `POST /api/tracks` -> full song plays in the little embedded player. Private per user.
- **To-do v2:** priority, due date, category, effort, edit dialog, search/sort/filters, clear completed, and a **mood-aware "Focus now"** list from the Task agent (`task_focus` in `agents.py`).
- **Insights page** (`GET /api/insights`, maths in `backend/insights.py`): mood mix/timeline/weekday/time-of-day, task completion by mood/priority/effort/category, music plays & feedback, wardrobe use. Plain HTML/SVG charts, no library.
- Home dashboard: Focus now, this-week bars, 7-day mood dots, one-click mood radio.
- New collection `play_events`; extra task fields validated in `$jsonSchema`.

**Paper note:** the paper says the Task agent "does not rank". In v2 it still returns the same analytics (unchanged, oracle-tested) but also returns a ranked `focus` list. Update that sentence if you describe v2. Music is no longer purely static (it uses the iTunes Search API for previews).

**Needs internet (not testable in my sandbox):** iTunes lookup and the YouTube/Spotify embeds. If iTunes is unreachable, songs fall back to "opens ↗" links. Open the app via http://localhost:8000 (YouTube embeds refuse file://).
Tests: `RUN_TESTS.bat` (18 pass, incl. 9 new in `tests/test_v2.py`).

## Honest status
- Tested here: all agents, the Coordinator↔agent HTTP path, schema contracts, graceful degradation, integrity checks (pytest, in-memory MongoDB).
- **Not tested here (please check on your machine):** the real MongoDB server (validators, `collMod`, GridFS, `$lookup` queries in `queries.mongosh.js` #13-#17), Atlas, and the website in a browser (JS syntax-checked only). If anything breaks, send me the error text.
- Rule-based agents; the preference memory adapts but did not measurably improve simulated acceptance in development runs.
