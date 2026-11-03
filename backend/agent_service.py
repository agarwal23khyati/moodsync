"""MoodSync agent service (FastAPI, port 8001). Four stateless domain agents; each reads its own
data from MongoDB, applies its rule-based procedure and returns ranked suggestions.
Agents never call each other - they only share the mood context and the preference store."""
import datetime as dt
from fastapi import Depends, FastAPI, Header, HTTPException
import agents as A
import feedback as F
from common import INTERNAL_KEY, TZ_OFFSET_MIN, aware, db, init_db, now, to_oid
from schemas import AgentRequest, MusicOut, RecipeOut, StylingOut, TaskOut

init_db()
app = FastAPI(title="MoodSync Agent Service", description="Styling / Task / Music / Recipe agents")


def internal(x_internal_key: str = Header(None)):
    if x_internal_key != INTERNAL_KEY: raise HTTPException(403, "internal service")


def _uid(r: AgentRequest):
    u = to_oid(r.user_id)
    if not u: raise HTTPException(422, "bad user_id")
    return u


@app.get("/health")
def health(): return {"status": "ok", "service": "agents"}


@app.post("/agents/styling", response_model=StylingOut, dependencies=[Depends(internal)])
def styling(r: AgentRequest):
    uid = _uid(r)
    items = [{**d, "id": str(d["_id"])} for d in db.wardrobe_items.find({"user_id": uid})]
    season = r.season if r.season in A.SEASONS else A.season_for(now().date())
    out = A.styling_rank(items, r.mood, A.normalize_occasion(r.occasion), season, F.load_prefs(uid))
    return {"mood": r.mood, "occasion": A.normalize_occasion(r.occasion), "season": season, "wardrobe_size": len(items), "outfits": out}


@app.post("/agents/task", response_model=TaskOut, dependencies=[Depends(internal)])
def task(r: AgentRequest):
    uid = _uid(r)
    docs = list(db.tasks.find({"user_id": uid}))
    tasks = [{"completed": t.get("completed", False), "completed_at": aware(t.get("completed_at")), "mood": t.get("mood")} for t in docs]
    out = A.task_analytics(tasks, now(), TZ_OFFSET_MIN)
    out["focus"] = A.task_focus([{**t, "id": str(t["_id"])} for t in docs], r.mood, now(), TZ_OFFSET_MIN)
    return out


@app.post("/agents/music", response_model=MusicOut, dependencies=[Depends(internal)])
def music(r: AgentRequest):
    uid = _uid(r)
    tracks = [{**t, "key": t["_id"], "custom": bool(t.get("user_id"))}   # seed tracks + this user's own pasted tracks
              for t in db.tracks.find({"$or": [{"user_id": {"$exists": False}}, {"user_id": uid}]})]
    for t in tracks: t.pop("user_id", None)
    fb = {d["track_key"]: d["feedback"] for d in db.song_feedback.find({"user_id": uid})}
    return A.music_pick(tracks, r.mood, fb, F.load_prefs(uid), top_n=max(1, min(r.limit or 6, 60)))


@app.post("/agents/recipe", response_model=RecipeOut, dependencies=[Depends(internal)])
def recipe(r: AgentRequest):
    uid = _uid(r)
    recipes = [{**x, "id": x["_id"]} for x in db.recipes.find()]
    groceries = [g["name"] for g in db.grocery_items.find({"user_id": uid})]
    rej = {}
    for d in db.recipe_rejections.find({"user_id": uid}): rej[d["recipe_id"]] = rej.get(d["recipe_id"], 0) + 1
    return {"mood": r.mood, "pantry_size": len(groceries),
            "recipes": A.recipe_rank(recipes, groceries, rej, r.mood, F.load_prefs(uid), r.max_time)}
