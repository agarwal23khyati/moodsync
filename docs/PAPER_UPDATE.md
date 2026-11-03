# What to change in the paper so it matches this code

All measured numbers come from `results/paper_text.md` + `results/results.md` after YOU run `RUN_EXPERIMENTS` on your machine
with real MongoDB (the copies shipped in this zip are from an in-memory mock run and are marked DO NOT PUBLISH).

## Must change (these statements are no longer true of the code)
| Where | Old | New |
|---|---|---|
| Title / abstract / Fig. 2 / Sec. III-B | Java Spring Boot layer | **Python FastAPI Coordinator service (port 8000)** + **Python FastAPI agent service (port 8001)** + MongoDB. Delete every Java / Spring Data JPA / Hibernate mention |
| Abstract, Sec. III-B | MySQL/PostgreSQL, 10 relational tables, 3NF | **MongoDB, 11 collections**: users, mood_logs, tasks, wardrobe_items (clothes/shoes/accessories as one collection with a `category`), outfits, grocery_items, recipes, recipe_rejections, tracks, song_feedback, user_preferences |
| Sec. III-B, Fig. 3 | foreign keys, 3NF | document model with **references by ObjectId** (`user_id`, `mood_log_id`, `outfits.item_ids`), `$jsonSchema` validation, unique/compound indexes, GridFS for photos. Referential integrity is enforced **in the application** (cascade delete of outfits when an item is deleted) and verified by test. Drop the 3NF claim; cite the MongoDB data-modelling documentation (add the reference yourself) |
| Fig. 4 | Styling + Recipe only | Coordinator dispatches to **all four agents concurrently** (`asyncio.gather`) |
| Sec. III-A | "written asynchronously" | true: `/api/feedback` returns 202 and writes in a background task |
| Sec. IV | 24/24, 96%, 200/200, 284 ms | **your own measured values** (paper_text.md). They will differ; that is expected |
| Sec. IV-D | 5 students, "mood selector does not filter recipes" | the recipe agent now applies a **soft mood bonus** (`MOOD_TAGS`) on top of ingredient overlap, so re-run or re-word this question |
| Contributions (iii) | "validated by unit, integration and usability testing" | add: "and a simulation study of shared mood context versus siloed modules" |

## New sections/figures available
- Fig. 5 (`results/fig5_results.png`) - success rates + latency (replaces the old Fig. 5).
- Fig. 6 (`results/fig6_simulation.png`) - acceptance curves: siloed vs shared vs shared+feedback at three levels of individual variation.
- Table II / Sec. IV-B..F text - already written in `results/paper_text.md`.

## Be careful about these claims
- **Do not claim learning helps** unless your real run shows it. In the development runs the accept/reject adaptation gave no reliable gain; the generated text states what YOUR run shows.
- The simulation is built on the same mood vocabulary as the agents, so it supports the *mechanism*, not real-user benefit. The text says so; keep it.
- The worn-count rotation costs outfit fit (reported). Keep that sentence.
- Weights in `agents.py` (`W`, `STYLE_BY_MOOD`...) are hand-set. Say so (Limitation vi).
- The usability numbers must come from real people (docs/USABILITY_PROTOCOL.md).

## Tables to update
Table I: all four rows can honestly stay "Implemented" now (the code exists and is tested), but change the descriptions:
Styling = mood/occasion/season/colour scoring + worn-count penalty + coherence; Task = completion rate, streak, week-over-week, per-mood (pandas);
Music = mood-category playlist + like/skip feedback; Recipe = ingredient-overlap ranking + soft mood bonus + rejection penalty.
Table III: unchanged in structure; MoodSync row = 4 domains, mood-aware yes, shared context yes, microservices yes.
