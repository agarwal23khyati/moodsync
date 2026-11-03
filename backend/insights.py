"""Analytics for the Insights page - pure functions (no DB, no HTTP), so they are easy to unit-test.
Everything is descriptive ("so far", with sample sizes); nothing here claims causation."""
import datetime as dt
import statistics
from collections import Counter, defaultdict
from typing import Optional

MOODS = ["happy", "energetic", "calm", "low"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PARTS = ["morning", "afternoon", "evening", "night"]
MIN_N = 4          # smallest group we are willing to compare


def _utc(x):
    if x is None: return None
    if isinstance(x, str):
        try: x = dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
        except ValueError: return None
    return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)


def _part(h: int) -> str:
    return "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 22 else "night"


def _rate(done, total): return round(done / total * 100, 1) if total else 0.0


def _date(x):
    if isinstance(x, dt.datetime): return x.date()
    return x if isinstance(x, dt.date) else None


def build_insights(moods: list, tasks: list, feedback: list, plays: list, wardrobe: list, outfits: list,
                   track_names: dict, now: dt.datetime, tz_offset_min: int = 330) -> dict:
    tz = dt.timedelta(minutes=tz_offset_min)
    now = _utc(now); today = (now + tz).date()
    L = lambda x: (_utc(x) + tz) if _utc(x) else None            # to local time

    # ---------------------------------------------------------------- moods
    mc = Counter(m["mood"] for m in moods)
    per_day = {}
    for m in sorted(moods, key=lambda m: _utc(m["created_at"])):
        per_day[L(m["created_at"]).date()] = m["mood"]            # last check-in of the day wins
    last28 = [{"date": (today - dt.timedelta(days=i)).isoformat(), "mood": per_day.get(today - dt.timedelta(days=i))}
              for i in range(27, -1, -1)]
    wk = {d: Counter() for d in DAYS}; pt = {p: Counter() for p in PARTS}
    for m in moods:
        l = L(m["created_at"]); wk[DAYS[l.weekday()]][m["mood"]] += 1; pt[_part(l.hour)][m["mood"]] += 1
    mood = {"total": len(moods), "counts": {k: mc.get(k, 0) for k in MOODS}, "top": mc.most_common(1)[0][0] if mc else None,
            "last28": last28, "days_logged_28": sum(1 for x in last28 if x["mood"]),
            "by_weekday": {d: {k: wk[d].get(k, 0) for k in MOODS} for d in DAYS},
            "by_part_of_day": {p: {k: pt[p].get(k, 0) for k in MOODS} for p in PARTS}}

    # ---------------------------------------------------------------- tasks
    done = [t for t in tasks if t.get("completed")]
    open_ = [t for t in tasks if not t.get("completed")]
    overdue = sum(1 for t in open_ if _date(t.get("due_date")) and _date(t["due_date"]) < today)
    due_today = sum(1 for t in open_ if _date(t.get("due_date")) == today)
    created_by = Counter(L(t["created_at"]).date() for t in tasks if t.get("created_at"))
    done_by = Counter(L(t["completed_at"]).date() for t in done if t.get("completed_at"))
    last14 = [{"date": (today - dt.timedelta(days=i)).isoformat(), "created": created_by.get(today - dt.timedelta(days=i), 0),
               "completed": done_by.get(today - dt.timedelta(days=i), 0)} for i in range(13, -1, -1)]

    def group(key, order=None):
        g = defaultdict(lambda: [0, 0])
        for t in tasks:
            k = t.get(key) or ("unset" if key != "category" else "General"); g[k][0] += 1; g[k][1] += 1 if t.get("completed") else 0
        keys = order or sorted(g, key=lambda k: -g[k][0])
        return {k: {"total": g[k][0], "completed": g[k][1], "rate": _rate(g[k][1], g[k][0]), "enough_data": g[k][0] >= MIN_N}
                for k in keys if k in g}

    hrs = []
    for t in done:
        a, b = _utc(t.get("created_at")), _utc(t.get("completed_at"))
        if a and b and b >= a: hrs.append((b - a).total_seconds() / 3600)
    dd = Counter(DAYS[L(t["completed_at"]).weekday()] for t in done if t.get("completed_at"))
    dp = Counter(_part(L(t["completed_at"]).hour) for t in done if t.get("completed_at"))
    now_ts = now
    cur = sum(1 for t in done if t.get("completed_at") and now_ts - dt.timedelta(days=7) < _utc(t["completed_at"]) <= now_ts)
    prev = sum(1 for t in done if t.get("completed_at") and now_ts - dt.timedelta(days=14) < _utc(t["completed_at"]) <= now_ts - dt.timedelta(days=7))
    task = {"total": len(tasks), "completed": len(done), "open": len(open_), "overdue": overdue, "due_today": due_today,
            "rate": _rate(len(done), len(tasks)), "last14": last14,
            "by_mood": group("mood", MOODS), "by_priority": group("priority", ["high", "medium", "low", "unset"]),
            "by_effort": group("effort", ["quick", "medium", "deep", "unset"]),
            "by_category": dict(list(group("category").items())[:6]),
            "median_hours_to_complete": round(statistics.median(hrs), 1) if hrs else None,
            "completed_by_weekday": {d: dd.get(d, 0) for d in DAYS}, "completed_by_part": {p: dp.get(p, 0) for p in PARTS},
            "completed_this_week": cur, "completed_last_week": prev}

    # ---------------------------------------------------------------- music
    fbm = {m: {"like": 0, "skip": 0} for m in MOODS}
    liked = []
    for f in feedback:
        if f.get("feedback") in ("like", "skip") and f.get("mood") in fbm: fbm[f["mood"]][f["feedback"]] += 1
        if f.get("feedback") == "like": liked.append(f["track_key"])
    pc = Counter(p["track_key"] for p in plays); pm = Counter(p.get("mood") or "none" for p in plays)
    secs = sum(float(p.get("seconds") or 0) for p in plays)
    music = {"likes": sum(v["like"] for v in fbm.values()), "skips": sum(v["skip"] for v in fbm.values()), "by_mood": fbm,
             "plays": len(plays), "minutes_listened": round(secs / 60, 1),
             "finished_rate": _rate(sum(1 for p in plays if p.get("completed")), len(plays)),
             "plays_by_mood": {m: pm.get(m, 0) for m in MOODS},
             "top_played": [{"key": k, "title": track_names.get(k, {}).get("title", k), "artist": track_names.get(k, {}).get("artist", ""),
                             "plays": n} for k, n in pc.most_common(5)],
             "liked": [{"key": k, "title": track_names.get(k, {}).get("title", k), "artist": track_names.get(k, {}).get("artist", "")}
                       for k in liked[:8]]}

    # ---------------------------------------------------------------- wardrobe
    worn = sorted(wardrobe, key=lambda w: -int(w.get("worn_count") or 0))
    shown = len(outfits); acc = sum(1 for o in outfits if o.get("accepted"))
    ward = {"items": len(wardrobe), "never_worn": sum(1 for w in wardrobe if not w.get("worn_count")),
            "most_worn": [{"name": w.get("name", ""), "worn": int(w.get("worn_count") or 0)} for w in worn[:5] if w.get("worn_count")],
            "outfits_shown": shown, "outfits_accepted": acc, "accept_rate": _rate(acc, shown)}

    return {"generated_at": now.isoformat(), "mood": mood, "tasks": task, "music": music, "wardrobe": ward,
            "headlines": headlines(mood, task, music, ward)}


def headlines(mood, task, music, ward) -> list:
    h = []
    if mood["total"] >= 5 and mood["top"]:
        pct = round(mood["counts"][mood["top"]] / mood["total"] * 100)
        h.append(f"Your most-logged mood is {mood['top']} ({pct}% of {mood['total']} check-ins).")
    ok = {m: v for m, v in task["by_mood"].items() if v["enough_data"]}
    if len(ok) >= 2:
        best = max(ok, key=lambda m: ok[m]["rate"]); worst = min(ok, key=lambda m: ok[m]["rate"])
        if ok[best]["rate"] - ok[worst]["rate"] >= 15:
            h.append(f"So far you finish {ok[best]['rate']:.0f}% of tasks made in a {best} mood vs {ok[worst]['rate']:.0f}% in a {worst} mood "
                     f"({ok[best]['total']} and {ok[worst]['total']} tasks - a small sample, not a rule).")
    if task["completed"] >= 5:
        part = max(task["completed_by_part"], key=task["completed_by_part"].get)
        day = max(task["completed_by_weekday"], key=task["completed_by_weekday"].get)
        h.append(f"You tend to tick tasks off in the {part}, and {day} has been your busiest day.")
    c, p = task["completed_this_week"], task["completed_last_week"]
    if c or p:
        h.append(f"{c} task(s) completed in the last 7 days vs {p} the week before" + (f" ({(c - p) / p * 100:+.0f}%)." if p else "."))
    if task["overdue"]: h.append(f"{task['overdue']} open task(s) are past their due date - maybe pick the smallest one first.")
    if task["median_hours_to_complete"] is not None and task["completed"] >= 3:
        h.append(f"Typical time from adding a task to finishing it: about {task['median_hours_to_complete']} hour(s).")
    if music["plays"] >= 5:
        top = max(music["plays_by_mood"], key=music["plays_by_mood"].get)
        h.append(f"You have played {music['plays']} tracks (~{music['minutes_listened']:.0f} min); most while feeling {top}.")
    elif music["likes"] + music["skips"] >= 3:
        h.append(f"Music feedback so far: {music['likes']} liked, {music['skips']} skipped.")
    if ward["items"] and ward["never_worn"]:
        h.append(f"{ward['never_worn']} of your {ward['items']} wardrobe pieces have not been worn yet.")
    return h or ["Add a few check-ins and tasks - patterns usually start to show after about a week."]
