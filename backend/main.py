"""MoodSync Coordinator + REST API (FastAPI, port 8000).

The Coordinator Agent is the entry point: it normalises the user's mood/occasion, writes a MoodLogs record,
dispatches the context CONCURRENTLY to the four domain agents (agent_service.py, port 8001), validates and
merges their responses, and writes accept/reject feedback to the shared preference memory in the background."""
import asyncio, time, contextlib
from pathlib import Path
from typing import Literal, Optional

import bcrypt, httpx, jwt
import datetime as dt
from bson import ObjectId
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError
import os

import agents as A
import feedback as F
import insights as INS
import music as MU
from common import AGENT_URL, INTERNAL_KEY, SECRET, TZ_OFFSET_MIN, aware, db, fs, init_db, now, ser, to_oid
from schemas import AGENT_MODELS, ContextIn, FeedbackIn2

ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
MAX_PHOTO = 3 * 1024 * 1024
ITUNES_COUNTRY = os.getenv("ITUNES_COUNTRY", "IN")
AGENTS = ["styling", "task", "music", "recipe"]
init_db()


def oid(s):
    o = to_oid(s)
    if not o: raise HTTPException(404, "Not found")
    return o


# ---------- auth helpers ----------
def token_for(uid): return jwt.encode({"sub": str(uid), "exp": now() + dt.timedelta(days=7)}, SECRET, algorithm="HS256")


def uid_from(token):
    try: return ObjectId(jwt.decode(token, SECRET, algorithms=["HS256"])["sub"])
    except Exception: raise HTTPException(401, "Please log in again.")


def auth(authorization: str = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "): raise HTTPException(401, "Please log in.")
    return uid_from(authorization[7:])


def hash_pw(p): return bcrypt.hashpw(p.encode()[:72], bcrypt.gensalt()).decode()
def check_pw(p, h): return bcrypt.checkpw(p.encode()[:72], h.encode())
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# ---------- models ----------
class Signup(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(pattern=EMAIL, max_length=120)
    password: str = Field(min_length=6, max_length=72)
class Login(BaseModel):
    email: str
    password: str
class MoodIn(BaseModel):
    mood: Literal["happy", "energetic", "calm", "low"]
    occasion: str = Field("Casual", min_length=1, max_length=40)
Mood = Literal["happy", "energetic", "calm", "low"]
Priority = Literal["high", "medium", "low"]
Effort = Literal["quick", "medium", "deep"]
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    priority: Priority = "medium"
    effort: Effort = "medium"
    category: str = Field("General", min_length=1, max_length=30)
    due_date: Optional[str] = Field(None, pattern=DATE_RE)
class TaskPatch(BaseModel):          # every field optional -> one PATCH route handles tick, edit, reschedule
    completed: Optional[bool] = None
    title: Optional[str] = Field(None, min_length=1, max_length=160)
    priority: Optional[Priority] = None
    effort: Optional[Effort] = None
    category: Optional[str] = Field(None, min_length=1, max_length=30)
    due_date: Optional[str] = Field(None, pattern=DATE_RE)      # send null to clear
    pinned: Optional[bool] = None
class TrackIn(BaseModel):
    url: str = Field(min_length=3, max_length=300)
    title: str = Field("", max_length=100)
    artist: str = Field("", max_length=100)
    moods: list[Mood] = Field(default_factory=list, max_length=4)
class ResolveIn(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=40)
class PlayIn(BaseModel):
    track_key: str = Field(min_length=1, max_length=100)
    mood: Optional[Mood] = None
    seconds: float = Field(0, ge=0, le=36000)
    completed: bool = False
    source: Literal["preview", "embed"] = "preview"
class GroceryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
class GroceryPatch(BaseModel):
    checked: bool
class FeedbackIn(BaseModel):
    track_key: str = Field(min_length=1, max_length=100)
    feedback: Literal["like", "skip", "none"]
    mood: Literal["happy", "energetic", "calm", "low"]


# ---------- app ----------
@contextlib.asynccontextmanager
async def lifespan(app):
    app.state.http = httpx.AsyncClient(timeout=10.0, headers={"X-Internal-Key": INTERNAL_KEY})   # Coordinator -> agents only
    app.state.web = httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers={"User-Agent": "MoodSync/2.0"})  # iTunes / oEmbed
    yield
    await app.state.http.aclose(); await app.state.web.aclose()


app = FastAPI(title="MoodSync Coordinator API", description="Coordinator Agent + REST API (FastAPI + MongoDB)", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
async def health():
    db.command("ping")
    agents_ok = True
    try:
        r = await app.state.http.get(f"{AGENT_URL}/health"); agents_ok = r.status_code == 200
    except Exception: agents_ok = False
    return {"status": "ok", "database": db.name, "agent_service": "up" if agents_ok else "DOWN"}


# --- auth ---
@app.post("/api/auth/signup")
def signup(b: Signup):
    email = b.email.strip().lower()
    try:
        r = db.users.insert_one({"name": b.name.strip(), "email": email, "password_hash": hash_pw(b.password), "created_at": now()})
    except DuplicateKeyError:
        raise HTTPException(409, "An account with this email already exists. Try logging in.")
    return {"token": token_for(r.inserted_id), "user": {"id": str(r.inserted_id), "name": b.name.strip(), "email": email}}


@app.post("/api/auth/login")
def login(b: Login):
    u = db.users.find_one({"email": b.email.strip().lower()})
    if not u or not check_pw(b.password, u["password_hash"]): raise HTTPException(401, "Incorrect email or password.")
    return {"token": token_for(u["_id"]), "user": {"id": str(u["_id"]), "name": u["name"], "email": u["email"]}}


@app.get("/api/auth/me")
def me(uid=Depends(auth)):
    u = db.users.find_one({"_id": uid})
    if not u: raise HTTPException(401, "Please log in again.")
    return {"id": str(u["_id"]), "name": u["name"], "email": u["email"]}


def listing(col, uid): return [ser(d) for d in db[col].find({"user_id": uid}).sort("created_at", DESCENDING)]
def remove(col, uid, id_):
    if db[col].delete_one({"_id": oid(id_), "user_id": uid}).deleted_count == 0: raise HTTPException(404, "Not found")
    return Response(status_code=204)


# =====================================================================  COORDINATOR AGENT
async def call_agent(name: str, payload: dict) -> dict:
    t0 = time.perf_counter()
    r = await app.state.http.post(f"{AGENT_URL}/agents/{name}", json=payload)
    r.raise_for_status()
    data = AGENT_MODELS[name].model_validate(r.json()).model_dump()   # schema check: counts as a mismatch if it fails
    return {"name": name, "data": data, "ms": round((time.perf_counter() - t0) * 1000, 1)}


async def dispatch(payload: dict, names=AGENTS) -> dict:
    t0 = time.perf_counter()
    res = await asyncio.gather(*[call_agent(n, payload) for n in names], return_exceptions=True)  # concurrent fan-out
    out = {"suggestions": {}, "errors": {}, "agent_ms": {}}
    for n, r in zip(names, res):
        if isinstance(r, Exception): out["errors"][n] = f"{type(r).__name__}: {r}"[:300]
        else: out["suggestions"][n] = r["data"]; out["agent_ms"][n] = r["ms"]
    out["dispatch_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


@app.post("/api/context")
async def context(b: ContextIn, uid=Depends(auth)):
    """Select a mood/occasion once -> all four modules update."""
    try: mood = A.normalize_mood(b.mood)
    except ValueError: raise HTTPException(422, "mood must be one of happy / energetic / calm / low")
    occasion = A.normalize_occasion(b.occasion)
    log_id = (await run_in_threadpool(db.mood_logs.insert_one, {"user_id": uid, "mood": mood, "occasion": occasion, "created_at": now()})).inserted_id
    payload = {"user_id": str(uid), "mood": mood, "occasion": occasion, "mood_log_id": str(log_id), "season": b.season, "max_time": b.max_time}
    out = await dispatch(payload)
    return {"mood_log_id": str(log_id), "mood": mood, "occasion": occasion, **out}


@app.get("/api/health/itunes")
async def health_itunes():
    """Can THIS server reach iTunes and get a playable preview? (open /api/health/itunes in the browser to debug 'no audio')"""
    fields, reached = await MU.resolve_one(app.state.web, "Believer", "Imagine Dragons", ITUNES_COUNTRY)
    return {"itunes_reachable": reached, "preview_found": bool(fields), "preview_url": (fields or {}).get("preview_url")}


@app.get("/api/suggest/{domain}")
async def suggest(domain: Literal["styling", "task", "music", "recipe"], mood: Optional[str] = None, occasion: str = "Casual",
                  max_time: Optional[int] = Query(None, ge=1, le=600),
                  limit: Optional[int] = Query(None, ge=1, le=60), uid=Depends(auth)):
    """Ad-hoc call of one agent without writing a mood log (used by the Music/Food tabs)."""
    m = None
    if mood:
        try: m = A.normalize_mood(mood)
        except ValueError: raise HTTPException(422, "bad mood")
    payload = {"user_id": str(uid), "mood": m, "occasion": occasion, "max_time": max_time, "limit": limit}
    try: return (await call_agent(domain, payload))["data"]
    except Exception as e: raise HTTPException(502, f"agent service error: {e}")


@app.post("/api/feedback", status_code=202)
async def feedback(b: FeedbackIn2, bg: BackgroundTasks, uid=Depends(auth)):
    """Accept/reject is written to the shared preference memory AFTER the response (asynchronous)."""
    bg.add_task(F.apply_feedback, uid, b.domain, b.accepted, b.mood_log_id, b.item_ids, b.track_key, b.recipe_id)
    return {"queued": True}


@app.get("/api/preferences")
def preferences(uid=Depends(auth)): return F.load_prefs(uid)


# --- mood logs ---
@app.get("/api/mood_logs")
def mood_list(uid=Depends(auth)): return listing("mood_logs", uid)
@app.post("/api/mood_logs")
def mood_add(b: MoodIn, uid=Depends(auth)):
    d = {"user_id": uid, "mood": b.mood, "occasion": b.occasion, "created_at": now()}
    d["_id"] = db.mood_logs.insert_one(d).inserted_id
    return ser(d)


# --- tasks (each task remembers the mood it was created in -> per-mood analytics) ---
def _due(s):
    if not s: return None
    try: return dt.datetime.strptime(s, "%Y-%m-%d")        # stored as a calendar date (00:00), shown without time zones
    except ValueError: raise HTTPException(422, "due_date must look like 2026-12-31")
@app.get("/api/tasks")
def task_list(uid=Depends(auth)): return listing("tasks", uid)
@app.post("/api/tasks")
def task_add(b: TaskIn, uid=Depends(auth)):
    last = db.mood_logs.find_one({"user_id": uid}, sort=[("created_at", DESCENDING)])
    cur = last if last and (now() - aware(last["created_at"])) < dt.timedelta(hours=24) else None
    d = {"user_id": uid, "title": b.title.strip(), "completed": False, "completed_at": None, "created_at": now(),
         "mood": cur["mood"] if cur else None, "mood_log_id": cur["_id"] if cur else None,
         "priority": b.priority, "effort": b.effort, "category": b.category.strip() or "General", "due_date": _due(b.due_date), "pinned": False}
    d["_id"] = db.tasks.insert_one(d).inserted_id
    return ser(d)
@app.patch("/api/tasks/{id_}")
def task_patch(id_: str, b: TaskPatch, uid=Depends(auth)):
    cur = db.tasks.find_one({"_id": oid(id_), "user_id": uid})
    if not cur: raise HTTPException(404, "Not found")
    ch, upd = b.model_dump(exclude_unset=True), {}
    if ch.get("completed") is not None and ch["completed"] != cur.get("completed"):
        upd.update(completed=ch["completed"], completed_at=now() if ch["completed"] else None)
    for k in ("title", "category", "priority", "effort", "pinned"):
        if ch.get(k) is not None: upd[k] = ch[k].strip() if isinstance(ch[k], str) else ch[k]
    if "due_date" in ch: upd["due_date"] = _due(ch["due_date"])
    if upd: db.tasks.update_one({"_id": cur["_id"]}, {"$set": upd})
    elif not ch: raise HTTPException(422, "Nothing to change")
    return {"ok": True}
@app.delete("/api/tasks/{id_}", status_code=204)
def task_del(id_: str, uid=Depends(auth)): return remove("tasks", uid, id_)
@app.delete("/api/tasks")
def task_clear_done(completed: bool = Query(True), uid=Depends(auth)):
    """Bulk 'clear completed' (only ever deletes tasks that are already done)."""
    if not completed: raise HTTPException(400, "Only completed=true is supported")
    return {"deleted": db.tasks.delete_many({"user_id": uid, "completed": True}).deleted_count}

# --- groceries ---
@app.get("/api/grocery_items")
def grocery_list(uid=Depends(auth)): return listing("grocery_items", uid)
@app.post("/api/grocery_items")
def grocery_add(b: GroceryIn, uid=Depends(auth)):
    d = {"user_id": uid, "name": b.name.strip(), "checked": False, "created_at": now()}
    d["_id"] = db.grocery_items.insert_one(d).inserted_id
    return ser(d)
@app.patch("/api/grocery_items/{id_}")
def grocery_patch(id_: str, b: GroceryPatch, uid=Depends(auth)):
    r = db.grocery_items.update_one({"_id": oid(id_), "user_id": uid}, {"$set": {"checked": b.checked}})
    if r.matched_count == 0: raise HTTPException(404, "Not found")
    return {"ok": True}
@app.delete("/api/grocery_items/{id_}", status_code=204)
def grocery_del(id_: str, uid=Depends(auth)): return remove("grocery_items", uid, id_)

# --- song feedback (one document per user+track, upserted; also adapts the preference memory) ---
@app.get("/api/song_feedback")
def feedback_list(uid=Depends(auth)): return [ser(d) for d in db.song_feedback.find({"user_id": uid})]
@app.post("/api/song_feedback")
def feedback_set(b: FeedbackIn, uid=Depends(auth)):
    db.song_feedback.update_one({"user_id": uid, "track_key": b.track_key}, {"$set": {"feedback": b.feedback, "mood": b.mood}}, upsert=True)
    if b.feedback in ("like", "skip"):
        p = F.load_prefs(uid); A.update_music_prefs(p, b.mood, b.track_key, b.feedback == "like"); F.save_prefs(uid, p)
    return {"ok": True}

# --- wardrobe (photo goes into GridFS, item stores photo_id; worn_count feeds the Styling Agent) ---
@app.get("/api/wardrobe_items")
def wardrobe_list(uid=Depends(auth)): return listing("wardrobe_items", uid)
@app.post("/api/wardrobe_items")
async def wardrobe_add(name: str = Form(..., min_length=1, max_length=80), category: str = Form("Top"), color: str = Form(""),
                       style: str = Form("Casual"), season: str = Form("All season"), photo: Optional[UploadFile] = File(None), uid=Depends(auth)):
    pid = None
    if photo and photo.filename:
        data = await photo.read()
        if len(data) > MAX_PHOTO: raise HTTPException(413, "Please use a photo under 3 MB.")
        if not (photo.content_type or "").startswith("image/"): raise HTTPException(400, "Only image files are allowed.")
        pid = fs.put(data, filename=photo.filename, content_type=photo.content_type, user_id=uid)
    d = {"user_id": uid, "name": name.strip(), "category": category, "color": color.strip(), "style": style, "season": season,
         "photo_id": pid, "worn_count": 0, "last_worn": None, "created_at": now()}
    d["_id"] = db.wardrobe_items.insert_one(d).inserted_id
    return ser(d)
@app.delete("/api/wardrobe_items/{id_}", status_code=204)
def wardrobe_del(id_: str, uid=Depends(auth)):
    if not F.delete_wardrobe_item(uid, id_): raise HTTPException(404, "Not found")   # cascades to outfits
    return Response(status_code=204)
@app.get("/api/photos/{pid}")
def photo(pid: str, t: str = Query(...)):
    uid = uid_from(t)
    try: f = fs.get(oid(pid))
    except Exception: raise HTTPException(404, "Not found")
    if f.user_id != uid: raise HTTPException(403, "Not yours")
    return Response(f.read(), media_type=f.content_type or "image/jpeg")

# --- music: in-app playback (30-second previews resolved once and cached in MongoDB) + user-added tracks ---
def _visible_tracks(uid, keys=None):
    q = {"$or": [{"user_id": {"$exists": False}}, {"user_id": uid}]}
    if keys is not None: q["_id"] = {"$in": keys}
    return list(db.tracks.find(q))
@app.post("/api/music/resolve")
async def music_resolve(b: ResolveIn, uid=Depends(auth)):
    """Find a playable preview + artwork for tracks that don't have one yet; the answer is cached on the track document,
    so each song is looked up once, ever. Misses are remembered for a day; 'could not reach iTunes' is NOT remembered."""
    out, todo = {}, []
    for d in _visible_tracks(uid, list(dict.fromkeys(b.keys))):
        k = d["_id"]
        if d.get("embed"): continue
        if d.get("preview_url"): out[k] = {f: d.get(f, "") for f in ("preview_url", "artwork", "apple_url")}
        elif d.get("resolve_failed_at") and now() - aware(d["resolve_failed_at"]) < dt.timedelta(days=1): out[k] = None
        else: todo.append({"key": k, "title": d["title"], "artist": d.get("artist", "")})
    for k, (fields, reached) in ((await MU.resolve_many(app.state.web, todo, ITUNES_COUNTRY)) if todo else {}).items():
        if fields: db.tracks.update_one({"_id": k}, {"$set": {**fields, "resolved_at": now()}}); out[k] = {f: fields.get(f, "") for f in ("preview_url", "artwork", "apple_url")}
        else:
            if reached: db.tracks.update_one({"_id": k}, {"$set": {"resolve_failed_at": now()}})
            out[k] = None
    return {"resolved": out}
@app.post("/api/tracks")
async def track_add(b: TrackIn, uid=Depends(auth)):
    """Paste a YouTube / Spotify link (song or playlist) -> it becomes a track that plays inside MoodSync."""
    link = MU.parse_music_link(b.url)
    if not link: raise HTTPException(422, "Paste a YouTube or Spotify link (a song or a playlist).")
    meta = await MU.link_meta(app.state.web, link)
    title = b.title.strip() or meta.get("title") or f"My {link['provider'].title()} {link['kind']}"
    artist = b.artist.strip() or meta.get("author") or link["provider"].title()
    key = MU.custom_track_key(uid, link["ref"])
    doc = {"user_id": uid, "title": title[:100], "artist": artist[:100], "moods": list(dict.fromkeys(b.moods)) or ["happy", "energetic", "calm", "low"],
           "emoji": "📻" if link["kind"] in ("playlist", "album", "show") else "🎧", "description": "added by you", "url": link["external"],
           "external": link["external"], "embed": link["embed"], "provider": link["provider"], "artwork": meta.get("thumbnail", ""), "created_at": now()}
    db.tracks.update_one({"_id": key}, {"$set": doc}, upsert=True)
    return {"key": key, "title": doc["title"], "provider": link["provider"]}
@app.delete("/api/tracks/{key}", status_code=204)
def track_del(key: str, uid=Depends(auth)):
    if db.tracks.delete_one({"_id": key, "user_id": uid}).deleted_count == 0: raise HTTPException(404, "Not found")
    db.song_feedback.delete_many({"user_id": uid, "track_key": key})
    return Response(status_code=204)
@app.post("/api/plays", status_code=201)
def play_log(b: PlayIn, uid=Depends(auth)):
    db.play_events.insert_one({"user_id": uid, "track_key": b.track_key, "mood": b.mood, "seconds": float(b.seconds),
                               "completed": b.completed, "source": b.source, "played_at": now()})
    return {"ok": True}

# --- insights page (descriptive analytics; the maths lives in insights.py) ---
@app.get("/api/insights")
def insights(uid=Depends(auth)):
    own = lambda col: list(db[col].find({"user_id": uid}))
    names = {t["_id"]: {"title": t.get("title", ""), "artist": t.get("artist", "")} for t in _visible_tracks(uid)}
    return INS.build_insights(own("mood_logs"), own("tasks"), own("song_feedback"), own("play_events"), own("wardrobe_items"),
                              own("outfits"), names, now(), TZ_OFFSET_MIN)

# --- aggregation pipelines (good to show in the viva) ---
@app.get("/api/stats/mood-mix")
def mood_mix(uid=Depends(auth)):
    return list(db.mood_logs.aggregate([{"$match": {"user_id": uid}}, {"$group": {"_id": "$mood", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]))
@app.get("/api/stats/tasks")
def task_stats(uid=Depends(auth)):
    r = list(db.tasks.aggregate([{"$match": {"user_id": uid}}, {"$group": {"_id": "$completed", "count": {"$sum": 1}}}]))
    done = sum(x["count"] for x in r if x["_id"]); total = sum(x["count"] for x in r)
    return {"completed": done, "total": total, "percent": round(done / total * 100) if total else 0}
@app.get("/api/stats/acceptance")
def acceptance(uid=Depends(auth)):
    """Accept rate of styling suggestions per mood (outfits -> mood_logs, a $lookup join)."""
    return list(db.outfits.aggregate([{"$match": {"user_id": uid}},
        {"$lookup": {"from": "mood_logs", "localField": "mood_log_id", "foreignField": "_id", "as": "m"}},
        {"$unwind": "$m"}, {"$group": {"_id": "$m.mood", "shown": {"$sum": 1}, "accepted": {"$sum": {"$cond": ["$accepted", 1, 0]}}}}]))

FRONT = Path(__file__).resolve().parent.parent / "frontend"
if FRONT.exists(): app.mount("/", StaticFiles(directory=FRONT, html=True), name="web")
