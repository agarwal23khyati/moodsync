"""MoodSync domain agents - pure functions (no database, no HTTP).

Every agent receives plain Python data + the shared mood context and returns plain
data. The FastAPI agent service (agent_service.py) feeds them from MongoDB; the
experiments call them directly. Reasoning is rule-based; the only "learning" is the
accept/reject preference update (see update_* functions) - nothing here is a trained model.
"""
import functools, itertools, re
import datetime as dt
from typing import Optional

MOODS = ["happy", "energetic", "calm", "low"]
OCCASIONS = ["Casual", "Work", "Party", "Workout", "Study", "Rest day"]
STYLES = ["Casual", "Formal", "Party", "Sporty", "Traditional"]
SEASONS = ["All season", "Summer", "Winter", "Monsoon"]

# ------------------------------------------------------------------ context normalisation
MOOD_SYNONYMS = {"sad": "low", "down": "low", "tired": "low", "stressed": "low", "joyful": "happy",
                 "excited": "energetic", "pumped": "energetic", "relaxed": "calm", "chill": "calm",
                 "peaceful": "calm"}


def normalize_mood(m: Optional[str]) -> Optional[str]:
    if m is None: return None
    k = str(m).strip().lower()
    k = MOOD_SYNONYMS.get(k, k)
    if k not in MOODS: raise ValueError(f"unknown mood: {m!r}")
    return k


def normalize_occasion(o: Optional[str]) -> str:
    k = (o or "").strip().lower()
    for occ in OCCASIONS:
        if occ.lower() == k: return occ
    return "Casual"


def season_for(date: dt.date) -> str:
    return {3: "Summer", 4: "Summer", 5: "Summer", 6: "Summer", 7: "Monsoon", 8: "Monsoon", 9: "Monsoon"}.get(date.month, "Winter")


# ------------------------------------------------------------------ styling agent
STYLE_BY_MOOD = {
    "happy":     {"Party": .8, "Casual": .6, "Traditional": .6, "Sporty": .3, "Formal": .2},
    "energetic": {"Sporty": 1., "Casual": .6, "Party": .6, "Formal": .1, "Traditional": .1},
    "calm":      {"Casual": .8, "Formal": .5, "Traditional": .5, "Sporty": .2, "Party": .1},
    "low":       {"Casual": 1., "Sporty": .3, "Traditional": .3, "Formal": 0., "Party": 0.},
}
STYLE_BY_OCCASION = {
    "Casual":   {"Casual": 1., "Sporty": .4, "Traditional": .3, "Party": .2, "Formal": .1},
    "Work":     {"Formal": 1., "Casual": .4, "Traditional": .3, "Sporty": 0., "Party": 0.},
    "Party":    {"Party": 1., "Traditional": .6, "Formal": .4, "Casual": .2, "Sporty": 0.},
    "Workout":  {"Sporty": 1., "Casual": .2, "Formal": 0., "Party": 0., "Traditional": 0.},
    "Study":    {"Casual": 1., "Formal": .2, "Sporty": .2, "Traditional": .1, "Party": 0.},
    "Rest day": {"Casual": 1., "Sporty": .2, "Traditional": .2, "Formal": 0., "Party": 0.},
}
COLOR_FAMILY_WORDS = {
    "warm": {"red", "orange", "yellow", "pink", "coral", "peach", "mustard", "maroon", "gold", "rust", "magenta"},
    "cool": {"blue", "green", "teal", "mint", "purple", "lavender", "lilac", "turquoise", "aqua", "violet", "sky"},
    "neutral": {"black", "white", "grey", "gray", "beige", "cream", "brown", "navy", "tan", "khaki", "denim", "olive", "silver"},
}
COLOR_BY_MOOD = {
    "happy":     {"warm": 1., "cool": .5, "neutral": .3},
    "energetic": {"warm": 1., "cool": .6, "neutral": .2},
    "calm":      {"cool": 1., "neutral": .7, "warm": .2},
    "low":       {"neutral": 1., "cool": .6, "warm": .1},
}
W = dict(mood=1.0, occasion=1.5, color=0.5, season=0.5, worn=1.5, pref=1.0, coherence=0.15)
FAMILIES = ["warm", "cool", "neutral"]


def color_family(color: str) -> str:
    for w in re.findall(r"[a-z]+", (color or "").lower()):
        for fam, words in COLOR_FAMILY_WORDS.items():
            if w in words: return fam
    return "neutral"


PREF_SCALE, PREF_K = 1.0, 2.0          # preference boost = PREF_SCALE * (accepts - rejects) / (accepts + rejects + PREF_K)
FB_SCORE = {"like": 0.5, "skip": -1.0}  # explicit music feedback
REJECT_PENALTY = 0.3                    # per logged recipe rejection


def pref_value(block: dict, key: str) -> float:
    """Smoothed net acceptance of `key` in [-1, 1]; unseen keys are 0. Robust to a single noisy reject."""
    a, r = (block or {}).get(key, (0, 0))
    return PREF_SCALE * (a - r) / (a + r + PREF_K)


def _pref_boost(prefs: dict, mood: Optional[str], item: dict) -> float:
    block = ((prefs or {}).get("styling") or {}).get(mood or "any") or {}
    return pref_value(block, "style:" + str(item.get("style"))) + pref_value(block, "color:" + color_family(item.get("color", "")))


def item_score(item: dict, mood: Optional[str], occasion: str, season: str, prefs: Optional[dict] = None) -> float:
    s = W["occasion"] * STYLE_BY_OCCASION[occasion].get(item.get("style"), 0.)
    if mood:
        s += W["mood"] * STYLE_BY_MOOD[mood].get(item.get("style"), 0.)
        s += W["color"] * COLOR_BY_MOOD[mood][color_family(item.get("color", ""))]
    it_season = item.get("season") or "All season"
    s += W["season"] * (1. if it_season in ("All season", season) else 0.)
    s -= W["worn"] * int(item.get("worn_count") or 0)  # frequently worn -> negative score
    s += W["pref"] * _pref_boost(prefs, mood, item)
    return s


def _tie_key(i: dict):  # deterministic tie-break: less worn first, then least recently worn, then id
    return (int(i.get("worn_count") or 0), str(i.get("last_worn") or ""), str(i["id"]))


def styling_rank(items: list, mood: Optional[str], occasion: str, season: str, prefs: Optional[dict] = None,
                 top_n: int = 3, per_cat: int = 4) -> list:
    """Rank complete outfits (Dress | Top+Bottom, optional Shoes, Accessory, Outerwear in winter)."""
    by = {}
    for it in items:
        sc = item_score(it, mood, occasion, season, prefs)
        by.setdefault(it.get("category"), []).append((sc, it))
    for c in by: by[c].sort(key=lambda x: (-x[0], _tie_key(x[1])))
    top = {c: v[:per_cat] for c, v in by.items()}
    bases = []
    if top.get("Dress"): bases += [(d,) for d in top["Dress"]]
    if top.get("Top") and top.get("Bottom"): bases += [(t, b) for t in top["Top"] for b in top["Bottom"]]
    if not bases: return []
    opts = [[None] + top.get(c, [])[:2] if c != "Shoes" else [None] + top.get(c, []) for c in ("Shoes", "Accessory")]
    if season == "Winter" and top.get("Outerwear"): opts.append([None] + top["Outerwear"][:2])
    outfits = []
    for base in bases:
        for extra in itertools.product(*opts):
            parts = list(base) + [e for e in extra if e]
            sc = sum(p[0] for p in parts) / len(parts)
            styles = [p[1].get("style") for p in parts]
            same = sum(1 for a, b in itertools.combinations(styles, 2) if a == b)
            sc += W["coherence"] * same
            sc += 0.05 * len(parts)  # prefer complete outfits over bare ones
            outfits.append((sc, parts))
    outfits.sort(key=lambda o: (-round(o[0], 9), tuple(_tie_key(p[1]) for p in o[1])))
    out = []
    for sc, parts in outfits[:top_n]:
        its = [p[1] for p in parts]
        fams = sorted({color_family(i.get("color", "")) for i in its})
        out.append({"score": round(sc, 4), "item_ids": [str(i["id"]) for i in its],
                    "items": [{"id": str(i["id"]), "name": i.get("name", ""), "category": i.get("category", ""),
                               "color": i.get("color", ""), "style": i.get("style", ""),
                               "worn_count": int(i.get("worn_count") or 0)} for i in its],
                    "reason": f"{'/'.join(dict.fromkeys(i.get('style','') for i in its))} for {occasion}"
                              + (f", {mood} mood" if mood else "") + f", {'/'.join(fams)} tones"})
    return out


# ------------------------------------------------------------------ task agent (analytics, does not rank)
def task_analytics(tasks: list, now: dt.datetime, tz_offset_min: int = 330) -> dict:
    import pandas as pd
    tz = dt.timedelta(minutes=tz_offset_min)
    total = len(tasks)
    if total == 0:
        return {"total": 0, "completed": 0, "completion_rate": 0.0, "streak_days": 0, "completed_this_week": 0,
                "completed_last_week": 0, "week_over_week_change": None, "per_mood": {}}
    df = pd.DataFrame(tasks)
    df["completed"] = df["completed"].astype(bool)
    if "completed_at" not in df: df["completed_at"] = None
    df["mood"] = df["mood"].where(df["mood"].notna(), "unspecified") if "mood" in df else "unspecified"
    done = int(df["completed"].sum())
    ca = pd.to_datetime(df["completed_at"], utc=True, errors="coerce")
    ca = ca.where(df["completed"])
    local_now = now + tz
    days = set((ca.dropna() + tz).dt.date.tolist())
    d, streak = local_now.date(), 0
    if d not in days: d = d - dt.timedelta(days=1)
    while d in days: streak += 1; d -= dt.timedelta(days=1)
    now_ts = pd.Timestamp(now) if now.tzinfo else pd.Timestamp(now, tz="UTC")
    cur = int(((ca > now_ts - pd.Timedelta(days=7)) & (ca <= now_ts)).sum())
    prev = int(((ca > now_ts - pd.Timedelta(days=14)) & (ca <= now_ts - pd.Timedelta(days=7))).sum())
    per = {}
    for m, g in df.groupby("mood"):
        per[str(m)] = {"total": int(len(g)), "completed": int(g["completed"].sum()),
                       "rate": round(float(g["completed"].mean()) * 100, 1)}
    return {"total": total, "completed": done, "completion_rate": round(done / total * 100, 1), "streak_days": streak,
            "completed_this_week": cur, "completed_last_week": prev,
            "week_over_week_change": None if prev == 0 else round((cur - prev) / prev * 100, 1), "per_mood": per}


# Mood-aware "what should I do next" - ranks OPEN tasks (the analytics above stay unchanged).
PRIORITY_W = {"high": 1.5, "medium": 0.75, "low": 0.0}
EFFORT_FIT = {   # how well a task's effort suits the current mood (low mood -> small wins first, energetic -> deep work)
    "low":       {"quick": 1.0, "medium": 0.3, "deep": -0.5},
    "calm":      {"quick": 0.5, "medium": 1.0, "deep": 0.6},
    "happy":     {"quick": 0.4, "medium": 0.8, "deep": 0.7},
    "energetic": {"quick": 0.2, "medium": 0.5, "deep": 1.0},
}
FOCUS_NOTE = {"low": "small enough for a low-energy day", "calm": "steady, doable pace", "happy": "good use of a good mood",
              "energetic": "worth your high energy"}


def _as_date(x):
    if x is None: return None
    if isinstance(x, dt.datetime): return x.date()
    if isinstance(x, dt.date): return x
    try: return dt.date.fromisoformat(str(x)[:10])
    except ValueError: return None


def task_focus(tasks: list, mood: Optional[str], now: dt.datetime, tz_offset_min: int = 330, top_n: int = 3) -> list:
    today = (now + dt.timedelta(minutes=tz_offset_min)).date()
    out = []
    for t in tasks:
        if t.get("completed"): continue
        due = _as_date(t.get("due_date"))
        pr = t.get("priority") or "medium"
        ef = t.get("effort") or "medium"
        reasons, urg = [], 0.0
        if due is not None:
            d = (due - today).days
            if d < 0: urg, _ = 3.0, reasons.append("overdue")
            elif d == 0: urg, _ = 2.5, reasons.append("due today")
            elif d == 1: urg, _ = 1.5, reasons.append("due tomorrow")
            elif d <= 3: urg, _ = 0.8, reasons.append(f"due in {d} days")
            elif d <= 7: urg = 0.3
        if pr == "high": reasons.append("high priority")
        fit = EFFORT_FIT[mood][ef] if mood in EFFORT_FIT else 0.0
        if mood in EFFORT_FIT and fit >= 0.9: reasons.append(f"{ef} task - {FOCUS_NOTE[mood]}")
        created = t.get("created_at")
        age = max(0, (today - _as_date(created)).days) if _as_date(created) else 0
        score = urg + PRIORITY_W.get(pr, 0.75) + 0.8 * fit + 0.03 * min(age, 14)
        out.append((score, str(created or ""), str(t.get("id", "")), t, reasons, due))
    out.sort(key=lambda x: (-round(x[0], 9), x[1], x[2]))
    return [{"id": str(t.get("id", "")), "title": t.get("title", ""), "priority": t.get("priority") or "medium",
             "effort": t.get("effort") or "medium", "category": t.get("category") or "General",
             "due_date": due.isoformat() if due else None, "score": round(sc, 3),
             "reason": ", ".join(rs) if rs else "next in your list"} for sc, _, _, t, rs, due in out[:top_n]]


# ------------------------------------------------------------------ music agent
PLAYLISTS = {"happy": "Sunshine Pop", "energetic": "Power Hour", "calm": "Slow Breath", "low": "Soft Landing"}


def music_pick(tracks: list, mood: Optional[str], feedback: dict, prefs: Optional[dict] = None, top_n: int = 6) -> dict:
    block = (((prefs or {}).get("music") or {}).get(mood or "any")) or {}
    scored = []
    for t in tracks:
        ms = t.get("moods") or []
        s = 0.
        if mood:
            if mood in ms: s = 1.0 if ms[0] == mood else 0.6
            else: continue
        fb = (feedback or {}).get(t["key"], "none")
        s += FB_SCORE.get(fb, 0.) + pref_value(block, t["key"])
        scored.append((s, t))
    scored.sort(key=lambda x: (-x[0], x[1]["key"]))
    return {"mood_category": mood, "playlist": PLAYLISTS.get(mood, "All tracks"),
            "tracks": [{**{k: t.get(k) for k in ("key", "title", "artist", "emoji", "description", "url", "moods", "preview_url", "artwork",
                                                        "apple_url", "embed", "external", "provider", "custom")},
                        "score": round(s, 3)} for s, t in scored[:top_n]]}


# ------------------------------------------------------------------ recipe agent
SYN = {"yogurt": "curd", "yoghurt": "curd", "chili": "chilli", "chillies": "chilli", "capsicums": "capsicum",
       "bellpepper": "capsicum"}
MOOD_TAGS = {"happy": {"fresh", "spicy"}, "energetic": {"quick", "spicy", "fresh"}, "calm": {"comfort", "fresh"},
             "low": {"comfort", "quick"}}


def _stem(w: str) -> str:
    w = SYN.get(w, w)
    if w.endswith("ies") and len(w) > 4: w = w[:-3] + "y"
    elif w.endswith("oes"): w = w[:-2]
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3: w = w[:-1]
    return SYN.get(w, w)


@functools.lru_cache(maxsize=4096)
def tokens(text: str) -> frozenset:
    return frozenset(_stem(w) for w in re.findall(r"[a-z]+", (text or "").lower()))


def recipe_rank(recipes: list, groceries: list, rejects: dict, mood: Optional[str], prefs: Optional[dict] = None,
                max_time: Optional[int] = None, top_n: int = 5) -> list:
    have = [tokens(g) for g in groceries]
    rej_pref = (((prefs or {}).get("recipe") or {}).get(mood or "any")) or {}
    out = []
    for r in recipes:
        if max_time and r.get("time", 0) > max_time: continue
        need = r.get("ingredients") or []
        hit = [i for i in need if any(tokens(i) <= h for h in have)]
        overlap = len(hit) / len(need) if need else 0.
        s = 2.0 * overlap
        if mood and set(r.get("tags") or []) & MOOD_TAGS[mood]: s += 0.5
        s -= REJECT_PENALTY * int((rejects or {}).get(r["id"], 0))
        s += pref_value(rej_pref, r["id"])
        out.append((s, overlap, r, [i for i in need if i not in hit]))
    out.sort(key=lambda x: (-round(x[0], 9), x[2]["id"]))
    return [{"id": r["id"], "name": r["name"], "emoji": r.get("emoji", ""), "time": r.get("time"), "tags": r.get("tags", []),
             "desc": r.get("desc", ""), "overlap": round(ov, 3), "missing": miss, "score": round(s, 3)}
            for s, ov, r, miss in out[:top_n]]


# ------------------------------------------------------------------ shared-preference updates (accept/reject feedback)
def _bump(d: dict, k: str, accepted: bool):
    a, r = d.get(k, (0, 0))
    d[k] = [a + 1, r] if accepted else [a, r + 1]


def update_styling_prefs(prefs: dict, mood: Optional[str], items: list, accepted: bool) -> dict:
    block = prefs.setdefault("styling", {}).setdefault(mood or "any", {})
    for it in items:
        _bump(block, "style:" + str(it.get("style")), accepted)
        _bump(block, "color:" + color_family(it.get("color", "")), accepted)
    return prefs


def update_music_prefs(prefs: dict, mood: Optional[str], key: str, liked: bool) -> dict:
    _bump(prefs.setdefault("music", {}).setdefault(mood or "any", {}), key, liked)
    return prefs


def update_recipe_prefs(prefs: dict, mood: Optional[str], recipe_id: str, accepted: bool) -> dict:
    _bump(prefs.setdefault("recipe", {}).setdefault(mood or "any", {}), recipe_id, accepted)
    return prefs
