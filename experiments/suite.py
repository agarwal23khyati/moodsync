"""MoodSync evaluation suite. Every number in the paper's Results section comes from a function in this file.
Run via  python experiments/run_experiments.py  (see README). Nothing here is hard-coded: results are measured."""
import datetime as dt, json, math, os, platform, random, statistics as st, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

MOODS = ["happy", "energetic", "calm", "low"]
OCCASIONS = ["Casual", "Work", "Party", "Workout", "Study", "Rest day"]
STYLES = ["Casual", "Formal", "Party", "Sporty", "Traditional"]
PALETTE = {"warm": ["red", "yellow", "orange", "pink"], "cool": ["blue", "green", "teal", "purple"],
           "neutral": ["black", "white", "grey", "beige"]}
ALL_COLORS = [c for v in PALETTE.values() for c in v]


def _ci95(xs):
    if len(xs) < 2: return 0.0
    return 1.96 * st.stdev(xs) / math.sqrt(len(xs))


# ============================================================ environment (fills the paper's [placeholders])
def environment(mock: bool) -> dict:
    import importlib.metadata as md
    cpu = platform.processor() or ""
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"): cpu = line.split(":", 1)[1].strip(); break
    except Exception: pass
    try:
        import psutil; ram = round(psutil.virtual_memory().total / 2 ** 30, 1)
    except Exception: ram = None
    v = lambda p: (md.version(p) if p in {d.metadata["Name"] for d in md.distributions()} else "n/a")
    mongo = "mongomock (in-memory, NOT a real MongoDB)"
    if not mock:
        try:
            from common import client; mongo = "MongoDB " + client.server_info()["version"]
        except Exception as e: mongo = f"unknown ({e})"
    return {"cpu": cpu or "unknown", "ram_gb": ram, "os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
            "fastapi": v("fastapi"), "uvicorn": v("uvicorn"), "pymongo": v("pymongo"), "pydantic": v("pydantic"), "pandas": v("pandas"),
            "httpx": v("httpx"), "pytest": v("pytest"), "database": mongo, "mock_database": mock}


# ============================================================ boot both services (mock mode = threads in this process)
def start_servers(coord_port=8000, agent_port=8001):
    os.environ["MOODSYNC_MOCK"] = "1"
    os.environ["AGENT_URL"] = f"http://127.0.0.1:{agent_port}"
    import uvicorn, httpx
    import agent_service, main  # noqa
    servers = []
    for app, port in ((agent_service.app, agent_port), (main.app, coord_port)):
        s = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=s.run, daemon=True).start(); servers.append(s)
    for port, path in ((agent_port, "/health"), (coord_port, "/api/health")):
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}{path}", timeout=1).status_code == 200: break
            except Exception: time.sleep(0.1)
        else: raise RuntimeError(f"server on {port} did not start")
    return servers


class Api:
    """Tiny HTTP client for the Coordinator."""
    def __init__(self, base): import httpx; self.base = base.rstrip("/"); self.c = httpx.Client(timeout=15)
    def signup(self, tag):
        r = self.c.post(f"{self.base}/api/auth/signup", json={"name": f"Test {tag}", "email": f"{tag}-{random.randrange(10**9)}@test.dev", "password": "secret123"})
        r.raise_for_status(); j = r.json(); self.h = {"Authorization": "Bearer " + j["token"]}; self.uid = j["user"]["id"]; return self
    def post(self, p, **kw): return self.c.post(f"{self.base}/api{p}", headers=self.h, **kw)
    def get(self, p, **kw): return self.c.get(f"{self.base}/api{p}", headers=self.h, **kw)
    def delete(self, p): return self.c.delete(f"{self.base}/api{p}", headers=self.h)
    def seed_wardrobe(self, rng, n=14):
        cats = ["Top"] * 4 + ["Bottom"] * 4 + ["Shoes"] * 3 + ["Accessory"] * 3
        for i, cat in enumerate(cats[:n]):
            r = self.post("/wardrobe_items", data={"name": f"{cat} {i}", "category": cat, "color": rng.choice(ALL_COLORS),
                                                  "style": rng.choice(STYLES), "season": "All season"}); r.raise_for_status()


# ============================================================ 1. styling re-ranking: 24 cases (4 moods x 6 occasions)
# Oracle = hand-written acceptable sets, independent of the scoring weights.
OK_STYLES = {"Casual": {"Casual", "Sporty", "Traditional"}, "Work": {"Formal", "Casual"}, "Party": {"Party", "Traditional", "Formal"},
             "Workout": {"Sporty"}, "Study": {"Casual", "Formal"}, "Rest day": {"Casual", "Sporty"}}
OK_FAMILIES = {"happy": {"warm", "cool"}, "energetic": {"warm", "cool"}, "calm": {"cool", "neutral"}, "low": {"cool", "neutral"}}


def _factorial_wardrobe():
    items, n = [], 0
    for st_ in STYLES:
        for fam, cols in PALETTE.items():
            for cat in ("Top", "Bottom", "Shoes", "Accessory"):
                n += 1; items.append({"id": f"w{n:03d}", "name": f"{st_} {fam} {cat}", "category": cat, "style": st_,
                                      "color": cols[0], "season": "All season", "worn_count": 0, "last_worn": None})
    return items


def exp_styling_reranking():
    import agents as A
    wardrobe, details, passed = _factorial_wardrobe(), [], 0
    for mood in MOODS:
        for occ in OCCASIONS:
            top = A.styling_rank(wardrobe, mood, occ, "Summer")[0]
            clothes = [i for i in top["items"] if i["category"] in ("Top", "Bottom", "Dress")]
            ok_style = all(i["style"] in OK_STYLES[occ] for i in clothes)
            ok_color = all(A.color_family(i["color"]) in OK_FAMILIES[mood] for i in clothes)
            passed += ok_style and ok_color
            details.append({"mood": mood, "occasion": occ, "pass": bool(ok_style and ok_color), "top": top["reason"]})
    # re-ranking: changing mood alone (same occasion) must be able to change the top outfit
    changed = sum(A.styling_rank(wardrobe, m1, "Casual", "Summer")[0]["item_ids"] != A.styling_rank(wardrobe, m2, "Casual", "Summer")[0]["item_ids"]
                  for m1 in MOODS for m2 in MOODS if m1 < m2)
    return {"passed": passed, "total": len(details), "details": details, "mood_pairs_that_change_top_outfit": f"{changed}/6"}


# ============================================================ 2. worn-count penalty: 50 trials x 3 cycles
def exp_worn_penalty(trials=50, cycles=3, seed_base=1000):
    """No outfit may repeat within `cycles` wears. Also reports the fit cost of rotating (mean fit relative to the no-penalty optimum)."""
    import agents as A
    passed, fails, ratios = 0, [], []
    for t in range(trials):
        rng = random.Random(seed_base + t)
        items = []
        for cat, k in (("Top", rng.randint(3, 5)), ("Bottom", rng.randint(3, 5)), ("Shoes", rng.randint(2, 3)), ("Accessory", rng.randint(2, 3))):
            for j in range(k):
                items.append({"id": f"{cat[:2]}{t}_{j}", "name": f"{cat}{j}", "category": cat, "style": rng.choice(STYLES),
                              "color": rng.choice(ALL_COLORS), "season": "All season", "worn_count": 0, "last_worn": None})
        mood, occ = rng.choice(MOODS), rng.choice(OCCASIONS)
        by = {i["id"]: i for i in items}
        fit = lambda ids: st.mean(A.item_score({**by[i], "worn_count": 0}, mood, occ, "Summer") for i in ids)
        best_fit = fit(A.styling_rank([{**i, "worn_count": 0} for i in items], mood, occ, "Summer")[0]["item_ids"])
        seen, repeat = [], False
        for _ in range(cycles):
            top = A.styling_rank(items, mood, occ, "Summer")[0]
            key = tuple(sorted(top["item_ids"]))
            repeat |= key in seen; seen.append(key)
            if best_fit > 0: ratios.append(fit(top["item_ids"]) / best_fit)
            for it in items:
                if str(it["id"]) in top["item_ids"]: it["worn_count"] += 1
        if repeat: fails.append(t)
        else: passed += 1
    return {"passed": passed, "total": trials, "failed_trials": fails, "worn_weight": A.W["worn"],
            "mean_fit_retained": round(st.mean(ratios), 3) if ratios else None,
            "note": "worn weight chosen on development seeds 7000-7199 (smallest weight with >=95% no-repeat); reported on held-out seeds"}


# ============================================================ 3. referential integrity: 500 outfits
def exp_referential_integrity(n_outfits=500, n_delete=15):
    from common import db, now
    import feedback as F
    rng = random.Random(5)
    u = db.users.insert_one({"name": "FK", "email": f"fk{rng.random()}@t.dev", "password_hash": "x", "created_at": now()}).inserted_id
    cats = ["Top", "Bottom", "Shoes", "Accessory"]
    item_ids = [db.wardrobe_items.insert_one({"user_id": u, "name": f"i{i}", "category": cats[i % 4], "style": rng.choice(STYLES), "color": "blue",
                                              "worn_count": 0, "created_at": now()}).inserted_id for i in range(40)]
    logs = [db.mood_logs.insert_one({"user_id": u, "mood": rng.choice(MOODS), "occasion": "Casual", "created_at": now()}).inserted_id for _ in range(20)]
    db.outfits.insert_many([{"user_id": u, "item_ids": rng.sample(item_ids, rng.randint(3, 5)), "mood_log_id": rng.choice(logs),
                             "accepted": rng.random() < .5, "created_at": now()} for _ in range(n_outfits)])
    mine = lambda: db.outfits.count_documents({"user_id": u})
    before = mine(); orphans_seeded = F.orphan_outfit_count()
    for iid in rng.sample(item_ids, n_delete): F.delete_wardrobe_item(u, iid)   # app-level cascade
    after, orphans_after = mine(), F.orphan_outfit_count()
    db.outfits.insert_one({"user_id": u, "item_ids": [__import__("bson").ObjectId()], "mood_log_id": None, "accepted": None, "created_at": now()})
    control = F.orphan_outfit_count()   # negative control: the checker must catch a planted orphan
    db.outfits.delete_many({"user_id": u, "mood_log_id": None})
    return {"outfits_seeded": before, "orphans_after_seeding": orphans_seeded, "items_deleted": n_delete, "outfits_removed_by_cascade": before - after,
            "orphans_after_deletes": orphans_after, "negative_control_detects_planted_orphan": control == orphans_after + 1,
            "passed": int(orphans_after == 0 and orphans_seeded == 0 and control == 1), "total": 1}


# ============================================================ 4. task agent vs independent oracle: 100 random cases
def _task_oracle(tasks, now, tz=330):
    n = len(tasks)
    if n == 0: return None
    done = [t for t in tasks if t["completed"]]
    off = dt.timedelta(minutes=tz)
    days = {(t["completed_at"] + off).date() for t in done}
    d = (now + off).date(); streak = 0
    if d not in days: d -= dt.timedelta(days=1)
    while d in days: streak += 1; d -= dt.timedelta(days=1)
    cur = sum(1 for t in done if now - dt.timedelta(days=7) < t["completed_at"] <= now)
    prev = sum(1 for t in done if now - dt.timedelta(days=14) < t["completed_at"] <= now - dt.timedelta(days=7))
    per = {}
    for t in tasks:
        k = t["mood"] or "unspecified"; a = per.setdefault(k, [0, 0]); a[0] += 1; a[1] += t["completed"]
    return {"completion_rate": round(len(done) / n * 100, 1), "streak_days": streak, "completed_this_week": cur, "completed_last_week": prev,
            "week_over_week_change": None if prev == 0 else round((cur - prev) / prev * 100, 1),
            "per_mood": {k: {"total": a[0], "completed": a[1], "rate": round(a[1] / a[0] * 100, 1)} for k, a in per.items()}}


def exp_task_analytics(cases=100):
    import agents as A
    now = dt.datetime(2026, 10, 18, 9, 0, tzinfo=dt.timezone.utc)
    passed, bad = 0, []
    for c in range(cases):
        rng = random.Random(2000 + c)
        tasks = []
        for _ in range(rng.randint(1, 60)):
            done = rng.random() < .6
            tasks.append({"completed": done, "mood": rng.choice(MOODS + [None]),
                          "completed_at": now - dt.timedelta(days=rng.random() * 30, hours=rng.random() * 12) if done else None})
        if c % 10 == 0:  # force a real streak in 10% of cases
            for k in range(rng.randint(1, 6)): tasks.append({"completed": True, "mood": "calm", "completed_at": now - dt.timedelta(days=k, hours=1)})
        got, exp = A.task_analytics(tasks, now), _task_oracle(tasks, now)
        keys = ["completion_rate", "streak_days", "completed_this_week", "completed_last_week", "week_over_week_change"]
        ok = all(got[k] == exp[k] for k in keys) and {m: (v["total"], v["completed"], v["rate"]) for m, v in got["per_mood"].items()} == \
             {m: (v["total"], v["completed"], v["rate"]) for m, v in exp["per_mood"].items()}
        passed += ok
        if not ok: bad.append(c)
    return {"passed": passed, "total": cases, "failed_cases": bad}


# ============================================================ 5. music + recipe agents (through the HTTP API)
def exp_music_recipe(api: Api):
    import agents as A
    res = {"music": [], "recipe": []}
    api.post("/grocery_items", json={"name": "paneer cubes"})
    for mood in MOODS:
        out = api.get(f"/suggest/music", params={"mood": mood}).json()
        res["music"].append(("category_match:" + mood, all(mood in t["moods"] for t in out["tracks"]) and len(out["tracks"]) > 0))
        first, second = out["tracks"][0]["key"], out["tracks"][1]["key"]
        for _ in range(5): api.post("/song_feedback", json={"track_key": first, "feedback": "skip", "mood": mood})   # repeated -> one doc (upsert)
        docs = [d for d in api.get("/song_feedback").json() if d["track_key"] == first]
        res["music"].append(("feedback_upsert_single_doc:" + mood, len(docs) == 1 and docs[0]["feedback"] == "skip"))
        out2 = api.get(f"/suggest/music", params={"mood": mood}).json()
        order = [t["key"] for t in out2["tracks"]]
        res["music"].append(("skipped_track_sinks:" + mood, order.index(first) > 0 if first in order else True))
        api.post("/song_feedback", json={"track_key": first, "feedback": "none", "mood": mood})
    # recipe: ranking is monotone in overlap and matches an independent oracle; a rejection demotes a recipe
    from common import SEED_RECIPES
    for t in range(100):
        rng = random.Random(3000 + t)
        pantry = [rng.choice(["paneer cubes", "tomatoes", "rice", "bread", "onions", "cabbage", "capsicums", "milk", "carrots", "banana", "dal", "noodles"]) for _ in range(rng.randint(1, 9))]
        ranked = A.recipe_rank([{**r, "id": r["_id"]} for r in SEED_RECIPES], pantry, {}, None, None, None, top_n=9)
        ov = [r["overlap"] for r in ranked]
        def oracle(r):
            hit = sum(1 for ing in r["ingredients"] if any(ing[:5] in g for g in pantry)); return round(hit / len(r["ingredients"]), 3)
        exp = {r["_id"]: oracle(r) for r in SEED_RECIPES}
        res["recipe"].append(("overlap_matches_oracle", all(abs(r["overlap"] - exp[r["id"]]) < 1e-9 for r in ranked) and ov == sorted(ov, reverse=True)))
    # rejection demotes top recipe (via API feedback path)
    top = api.get("/suggest/recipe", params={"mood": "low"}).json()["recipes"][0]["id"]
    api.post("/feedback", json={"domain": "recipe", "accepted": False, "recipe_id": top}); time.sleep(0.3)
    after = [r["id"] for r in api.get("/suggest/recipe", params={"mood": "low"}).json()["recipes"]]
    res["recipe"].append(("rejection_demotes_recipe", after[0] != top))
    return {k: {"passed": sum(ok for _, ok in v), "total": len(v), "failed": [n for n, ok in v if not ok]} for k, v in res.items()}


# ============================================================ 6. integration (Coordinator -> agent service over HTTP): 200 requests
def exp_integration(base, n=200):
    import httpx
    from schemas import AGENT_MODELS
    rng = random.Random(77)
    full, empty = Api(base).signup("full"), Api(base).signup("empty")
    full.seed_wardrobe(rng); full.post("/grocery_items", json={"name": "tomatoes"}); full.post("/tasks", json={"title": "x"})
    moods = MOODS + [m.upper() for m in MOODS] + [" Calm ", "sad", "excited", "relaxed"]
    occs = OCCASIONS + ["", "wedding 💍", "ÉVÉNEMENT", "x" * 40, "work"]
    ok = mismatches = errors = 0
    for i in range(n):
        who = full if i % 4 else empty   # a quarter of requests come from a user with no data
        r = who.post("/context", json={"mood": rng.choice(moods), "occasion": rng.choice(occs) or "Casual"})
        if r.status_code != 200: errors += 1; continue
        j = r.json()
        if j["errors"]:
            mismatches += sum("ValidationError" in e for e in j["errors"].values()); errors += 1; continue
        try:
            for name, model in AGENT_MODELS.items(): model.model_validate(j["suggestions"][name])
            ok += 1
        except Exception: mismatches += 1
    return {"completed_clean": ok, "total": n, "schema_mismatches": mismatches, "failed_requests": errors, "passed": ok, "base": base}


# ============================================================ 7. latency: 50 sequential outfit-suggestion requests
def exp_latency(base, n=50, warmup=3):
    rng = random.Random(9)
    u = Api(base).signup("lat"); u.seed_wardrobe(rng); u.post("/grocery_items", json={"name": "rice"})
    for _ in range(warmup): u.post("/context", json={"mood": "calm", "occasion": "Casual"})
    ms, disp = [], []
    for i in range(n):
        t0 = time.perf_counter(); r = u.post("/context", json={"mood": MOODS[i % 4], "occasion": OCCASIONS[i % 6]})
        ms.append((time.perf_counter() - t0) * 1000); disp.append(r.json()["dispatch_ms"])
    ms_sorted = sorted(ms)
    return {"runs": n, "warmup_discarded": warmup, "mean_ms": round(st.mean(ms), 1), "median_ms": round(st.median(ms), 1),
            "p95_ms": round(ms_sorted[int(.95 * n) - 1], 1), "max_ms": round(max(ms), 1), "coordinator_to_agents_mean_ms": round(st.mean(disp), 1),
            "target_ms": 500, "within_target": st.mean(ms) < 500, "all_ms": [round(x, 1) for x in ms]}


# ============================================================ 8. SIMULATION: shared mood context vs siloed modules (+ feedback learning)
def _user(rng, rho):
    import agents as A
    from common import SEED_RECIPES, SEED_TRACKS
    mix = lambda base: (1 - rho) * base + rho * rng.random()
    wardrobe = []
    for cat, k in (("Top", 4), ("Bottom", 4), ("Shoes", 3), ("Accessory", 3), ("Dress", 2)):
        for j in range(k):
            wardrobe.append({"id": f"{cat}{j}", "name": f"{cat}{j}", "category": cat, "style": rng.choice(STYLES), "color": rng.choice(ALL_COLORS),
                             "season": "All season", "worn_count": 0, "last_worn": None})
    vocab = sorted({i for r in SEED_RECIPES for i in r["ingredients"]})
    pantry = rng.sample(vocab, 7)
    latent = {"style": {m: {s: mix(A.STYLE_BY_MOOD[m][s]) for s in STYLES} for m in MOODS},
              "color": {m: {f: mix(A.COLOR_BY_MOOD[m][f]) for f in A.FAMILIES} for m in MOODS},
              "track": {m: {t["_id"]: mix(1. if m in t["moods"] else 0.) for t in SEED_TRACKS} for m in MOODS},
              "recipe": {m: {r["_id"]: mix(1. if set(r["tags"]) & A.MOOD_TAGS[m] else 0.) for r in SEED_RECIPES} for m in MOODS}}
    return {"wardrobe": wardrobe, "pantry": pantry, "latent": latent}


def _p_outfit(u, outfit, mood, occ):
    import agents as A
    its = outfit["items"]
    occ_fit = st.mean(min(1., A.STYLE_BY_OCCASION[occ].get(i["style"], 0.)) for i in its)
    mood_fit = st.mean(.5 * u["latent"]["style"][mood][i["style"]] + .5 * u["latent"]["color"][mood][A.color_family(i["color"])] for i in its)
    return min(1., max(0., .05 + .9 * (.5 * occ_fit + .5 * mood_fit)))


def _run_user(u, mode, rounds, seq, draws):
    import agents as A
    from common import SEED_RECIPES, SEED_TRACKS
    wardrobe = [dict(i) for i in u["wardrobe"]]
    tracks = [{**t, "key": t["_id"]} for t in SEED_TRACKS]
    recipes = [{**r, "id": r["_id"]} for r in SEED_RECIPES]
    prefs, fb, rejects = {}, {}, {}
    acc = {"styling": [], "music": [], "recipe": []}
    for r in range(rounds):
        mood, occ = seq[r]
        ctx = None if mode == "siloed" else mood        # siloed modules do not share the mood
        learn = mode == "shared+learning"
        # styling
        o = A.styling_rank(wardrobe, ctx, occ, "Summer", prefs if learn else None, top_n=1)[0]
        a = draws[r][0] < _p_outfit(u, o, mood, occ); acc["styling"].append(a)
        if a:
            for it in wardrobe:
                if it["id"] in o["item_ids"]: it["worn_count"] += 1
        if learn: A.update_styling_prefs(prefs, ctx, [i for i in wardrobe if i["id"] in o["item_ids"]], a)
        # music
        t = A.music_pick(tracks, ctx, fb if learn else {}, prefs if learn else None, top_n=1)["tracks"][0]
        a = draws[r][1] < min(1., max(0., .05 + .9 * u["latent"]["track"][mood][t["key"]])); acc["music"].append(a)
        if learn: A.update_music_prefs(prefs, ctx, t["key"], a); fb[t["key"]] = "like" if a else "skip"
        # recipe
        rc = A.recipe_rank(recipes, u["pantry"], rejects if learn else {}, ctx, prefs if learn else None, None, top_n=1)[0]
        a = draws[r][2] < min(1., max(0., .1 + .5 * rc["overlap"] + .4 * u["latent"]["recipe"][mood][rc["id"]])); acc["recipe"].append(a)
        if learn:
            A.update_recipe_prefs(prefs, ctx, rc["id"], a)
            if not a: rejects[rc["id"]] = rejects.get(rc["id"], 0) + 1
    return acc


def exp_simulation(n_users=200, rounds=30, rhos=(0.25, 0.5, 0.75), seed=11):
    modes = ["siloed", "shared", "shared+learning"]
    out = {"n_users": n_users, "rounds": rounds, "by_rho": {}}
    for rho in rhos:
        rng = random.Random(seed + int(rho * 100))
        per = {m: [] for m in modes}; curves = {m: [0.] * rounds for m in modes}
        dom = {m: {"styling": [], "music": [], "recipe": []} for m in modes}
        for _ in range(n_users):
            u = _user(rng, rho)
            seq = [(rng.choice(MOODS), rng.choice(OCCASIONS)) for _ in range(rounds)]
            draws = [(rng.random(), rng.random(), rng.random()) for _ in range(rounds)]      # common random numbers across modes
            for m in modes:
                acc = _run_user(u, m, rounds, seq, draws)
                rate = [st.mean([acc[d][r] for d in acc]) for r in range(rounds)]
                per[m].append(st.mean(rate))
                for r in range(rounds): curves[m][r] += rate[r] / n_users
                for d in acc: dom[m][d].append(st.mean(acc[d]))
        diff = lambda a, b: [x - y for x, y in zip(per[a], per[b])]
        out["by_rho"][str(rho)] = {
            "acceptance": {m: {"mean": round(st.mean(per[m]), 4), "ci95": round(_ci95(per[m]), 4)} for m in modes},
            "by_domain": {m: {d: round(st.mean(v), 4) for d, v in dom[m].items()} for m in modes},
            "shared_minus_siloed": {"mean": round(st.mean(diff("shared", "siloed")), 4), "ci95": round(_ci95(diff("shared", "siloed")), 4)},
            "learning_minus_shared": {"mean": round(st.mean(diff("shared+learning", "shared")), 4), "ci95": round(_ci95(diff("shared+learning", "shared")), 4)},
            "curves": {m: [round(x, 4) for x in curves[m]] for m in modes}}
    out["mood_entries_per_session"] = {"siloed": 4, "shared": 1, "note": "by design: siloed modules each ask for the mood; not a measured quantity"}
    return out


# ============================================================ 9. context normalisation
def exp_normalisation():
    import agents as A
    cases = [("happy", "happy"), ("  CALM ", "calm"), ("sad", "low"), ("Excited", "energetic"), ("chill", "calm"), ("LOW", "low")]
    ok = sum(A.normalize_mood(a) == b for a, b in cases)
    occ = [("work", "Work"), ("REST DAY", "Rest day"), ("wedding", "Casual"), ("", "Casual"), (None, "Casual")]
    ok += sum(A.normalize_occasion(a) == b for a, b in occ)
    bad = 0
    try: A.normalize_mood("furious")
    except ValueError: bad = 1
    return {"passed": ok + bad, "total": len(cases) + len(occ) + 1}
