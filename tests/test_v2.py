"""Tests for the v2 features (in-app music, richer to-do, mood-aware focus, insights). Uses the in-memory DB."""
import os, sys, datetime as dt
os.environ["MOODSYNC_MOCK"] = "1"
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments")); sys.path.insert(0, str(ROOT / "backend"))
import pytest
import suite as S
import agents as A, insights as I, music as M

NOW = dt.datetime(2026, 10, 31, 6, 0, tzinfo=dt.timezone.utc)      # 11:30 IST


@pytest.fixture(scope="module")
def stack():
    S.start_servers(8110, 8111)
    return "http://127.0.0.1:8110"


# ---------------------------------------------------------------- pure functions
def test_music_links_are_whitelisted():
    y = M.parse_music_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3")
    assert y["embed"].startswith("https://www.youtube.com/embed/dQw4w9WgXcQ")
    assert M.parse_music_link("youtu.be/dQw4w9WgXcQ")["ref"] == "dQw4w9WgXcQ"
    sp = M.parse_music_link("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=x")
    assert sp["embed"].startswith("https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M")
    for bad in ("https://evil.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/watch?v=<script>", "javascript:alert(1)", "", "hello"):
        assert M.parse_music_link(bad) is None


def test_itunes_match_picks_right_song():
    res = [{"trackName": "Golden Hour (Remix)", "artistName": "Someone", "previewUrl": "remix"},
           {"trackName": "Golden Hour", "artistName": "JVKE", "previewUrl": "ok", "artworkUrl100": "x/100x100bb.jpg"},
           {"trackName": "Golden Hour", "artistName": "JVKE", "previewUrl": ""},
           {"trackName": "Unrelated", "artistName": "JVKE", "previewUrl": "no"}]
    m = M.pick_itunes_match(res, "Golden Hour", "JVKE")
    assert m["previewUrl"] == "ok" and M.match_to_fields(m)["artwork"].endswith("400x400bb.jpg")
    assert M.pick_itunes_match([{"trackName": "Other", "artistName": "X", "previewUrl": "p"}], "Golden Hour", "JVKE") is None


def test_focus_low_mood_prefers_quick_but_overdue_wins():
    mk = lambda i, **k: {"id": i, "title": i, "completed": False, "created_at": NOW, **k}
    tasks = [mk("deep", effort="deep"), mk("quick", effort="quick"), mk("late", effort="deep", due_date=dt.datetime(2026, 10, 29))]
    f = A.task_focus(tasks, "low", NOW)
    assert f[0]["id"] == "late" and "overdue" in f[0]["reason"]
    assert [x["id"] for x in f].index("quick") < [x["id"] for x in f].index("deep")
    assert A.task_focus(tasks, "energetic", NOW)[1]["id"] == "deep"          # same tasks, other mood -> other order
    assert all(x["id"] != "done" for x in A.task_focus([mk("done", completed=True)], "calm", NOW))


def test_insights_small_samples_are_not_compared():
    t = [{"completed": True, "created_at": NOW, "completed_at": NOW, "mood": "happy"}] * 2 + [{"completed": False, "created_at": NOW, "mood": "low"}] * 2
    r = I.build_insights([], t, [], [], [], [], {}, NOW)
    assert not any("vs" in h and "mood" in h for h in r["headlines"])         # needs >= 4 tasks per mood
    assert r["tasks"]["by_mood"]["happy"]["enough_data"] is False


# ---------------------------------------------------------------- HTTP: to-do
def test_task_fields_edit_and_clear(stack):
    api = S.Api(stack).signup("todo")
    t = api.post("/tasks", json={"title": "Write report", "priority": "high", "effort": "deep", "category": "Study", "due_date": "2026-12-31"}).json()
    assert (t["priority"], t["effort"], t["category"], t["due_date"][:10]) == ("high", "deep", "Study", "2026-12-31")
    assert api.post("/tasks", json={"title": "x", "due_date": "31/12/2026"}).status_code == 422
    assert api.post("/tasks", json={"title": "x", "priority": "urgent"}).status_code == 422
    assert api.c.patch(f"{api.base}/api/tasks/{t['id']}", headers=api.h, json={"title": "Write the report", "due_date": None}).status_code == 200
    got = [x for x in api.get("/tasks").json() if x["id"] == t["id"]][0]
    assert got["title"] == "Write the report" and got["due_date"] is None and got["priority"] == "high"
    api.c.patch(f"{api.base}/api/tasks/{t['id']}", headers=api.h, json={"completed": True})
    first = [x for x in api.get("/tasks").json() if x["id"] == t["id"]][0]["completed_at"]
    api.c.patch(f"{api.base}/api/tasks/{t['id']}", headers=api.h, json={"completed": True})       # no state change
    assert [x for x in api.get("/tasks").json() if x["id"] == t["id"]][0]["completed_at"] == first
    other = api.post("/tasks", json={"title": "keep me"}).json()
    assert api.c.delete(f"{api.base}/api/tasks?completed=true", headers=api.h).json()["deleted"] == 1
    assert [x["id"] for x in api.get("/tasks").json()] == [other["id"]]
    assert api.c.patch(f"{api.base}/api/tasks/{other['id']}", headers=api.h, json={}).status_code == 422


def test_task_agent_returns_focus_without_changing_analytics(stack):
    api = S.Api(stack).signup("focus")
    api.post("/tasks", json={"title": "tiny", "effort": "quick"}); api.post("/tasks", json={"title": "big", "effort": "deep"})
    j = api.get("/suggest/task", params={"mood": "low"}).json()
    assert j["total"] == 2 and j["completed"] == 0 and [f["title"] for f in j["focus"]][0] == "tiny"
    assert api.get("/suggest/task", params={"mood": "energetic"}).json()["focus"][0]["title"] == "big"


# ---------------------------------------------------------------- HTTP: music
def test_resolve_is_cached_and_offline_is_not_remembered(stack, monkeypatch):
    import main
    api = S.Api(stack).signup("music")
    calls = []

    async def fake(http, tracks, country="IN", limit=4):
        calls.append([t["key"] for t in tracks])
        return {t["key"]: ({"preview_url": "https://a/p.m4a", "artwork": "https://a/a.jpg", "apple_url": "https://a/x"}, True) for t in tracks}
    monkeypatch.setattr(main.MU, "resolve_many", fake)
    keys = [t["key"] for t in api.get("/suggest/music", params={"mood": "calm", "limit": 12}).json()["tracks"]]
    assert len(keys) == 12                                                        # limit honoured, more tracks than before
    r1 = api.post("/music/resolve", json={"keys": keys[:3]}).json()["resolved"]
    r2 = api.post("/music/resolve", json={"keys": keys[:3]}).json()["resolved"]
    assert len(calls) == 1 and r1 == r2 and r1[keys[0]]["preview_url"].endswith("p.m4a")      # second call served from MongoDB
    got = api.get("/suggest/music", params={"mood": "calm", "limit": 12}).json()["tracks"]
    assert got[0]["preview_url"] or any(t["preview_url"] for t in got)           # suggestions now carry the cached preview

    async def offline(http, tracks, country="IN", limit=4): return {t["key"]: (None, False) for t in tracks}
    monkeypatch.setattr(main.MU, "resolve_many", offline)
    k = keys[-1]
    assert api.post("/music/resolve", json={"keys": [k]}).json()["resolved"][k] is None
    assert "resolve_failed_at" not in main.db.tracks.find_one({"_id": k})        # offline must not poison the cache

    async def nomatch(http, tracks, country="IN", limit=4): return {t["key"]: (None, True) for t in tracks}
    monkeypatch.setattr(main.MU, "resolve_many", nomatch)
    assert api.post("/music/resolve", json={"keys": [k]}).json()["resolved"][k] is None
    assert "resolve_failed_at" in main.db.tracks.find_one({"_id": k})            # real "no match" is remembered


def test_custom_tracks_are_private_and_playable(stack):
    a, b = S.Api(stack).signup("ca"), S.Api(stack).signup("cb")
    assert a.post("/tracks", json={"url": "https://example.com/x"}).status_code == 422
    r = a.post("/tracks", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "My jam", "moods": ["happy"]}).json()
    mine = [t for t in a.get("/suggest/music", params={"mood": "happy", "limit": 60}).json()["tracks"] if t["key"] == r["key"]]
    assert mine and mine[0]["embed"].startswith("https://www.youtube.com/embed/dQw4w9WgXcQ") and mine[0]["custom"] is True
    assert not [t for t in b.get("/suggest/music", params={"mood": "happy", "limit": 60}).json()["tracks"] if t["key"] == r["key"]]   # not visible to b
    assert b.delete(f"/tracks/{r['key']}").status_code == 404                     # b cannot delete a's track
    assert a.delete(f"/tracks/{r['key']}").status_code == 204


def test_plays_feed_insights(stack):
    api = S.Api(stack).signup("ins")
    key = api.get("/suggest/music", params={"mood": "calm"}).json()["tracks"][0]["key"]
    for i in range(5): assert api.post("/plays", json={"track_key": key, "mood": "calm", "seconds": 30, "completed": i % 2 == 0}).status_code == 201
    api.post("/context", json={"mood": "calm", "occasion": "Casual"})
    api.post("/tasks", json={"title": "a"})
    j = api.get("/insights").json()
    assert j["music"]["plays"] == 5 and j["music"]["minutes_listened"] == 2.5 and j["music"]["top_played"][0]["plays"] == 5
    assert j["mood"]["total"] == 1 and j["tasks"]["total"] == 1 and len(j["mood"]["last28"]) == 28 and len(j["tasks"]["last14"]) == 14
    assert api.post("/plays", json={"track_key": key, "seconds": -1}).status_code == 422
