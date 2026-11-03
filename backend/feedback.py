"""Writes to the shared preference memory: outfit wear tracking, accept/reject feedback,
referential-integrity helpers. Used by the Coordinator (main.py) and the experiments."""
from bson import ObjectId
import agents as A
from common import db, fs, now, to_oid


def load_prefs(uid) -> dict:
    d = db.user_preferences.find_one({"user_id": uid})
    return (d or {}).get("data", {})


def save_prefs(uid, data: dict):
    db.user_preferences.update_one({"user_id": uid}, {"$set": {"data": data, "updated_at": now()}}, upsert=True)


def _mood_of(log_id):
    if not log_id: return None
    d = db.mood_logs.find_one({"_id": log_id})
    return d["mood"] if d else None


def apply_feedback(uid, domain: str, accepted: bool, mood_log_id=None, item_ids=None, track_key=None, recipe_id=None) -> dict:
    """Persist one accept/reject and adapt the user's preference memory."""
    log_oid = to_oid(mood_log_id) if mood_log_id else None
    mood = _mood_of(log_oid)
    prefs = load_prefs(uid)
    if domain == "styling":
        oids = [o for o in (to_oid(i) for i in (item_ids or [])) if o]
        items = list(db.wardrobe_items.find({"_id": {"$in": oids}, "user_id": uid}))
        if not items: return {"ok": False, "error": "no matching wardrobe items"}
        db.outfits.insert_one({"user_id": uid, "item_ids": [i["_id"] for i in items], "mood_log_id": log_oid,
                               "accepted": bool(accepted), "created_at": now()})
        if accepted:  # wearing it raises worn_count -> negative score next time
            db.wardrobe_items.update_many({"_id": {"$in": [i["_id"] for i in items]}},
                                          {"$inc": {"worn_count": 1}, "$set": {"last_worn": now()}})
        A.update_styling_prefs(prefs, mood, [{**i, "id": str(i["_id"])} for i in items], accepted)
    elif domain == "music":
        if not track_key: return {"ok": False, "error": "track_key required"}
        db.song_feedback.update_one({"user_id": uid, "track_key": track_key},
                                    {"$set": {"feedback": "like" if accepted else "skip", "mood": mood or "calm",
                                              "mood_log_id": log_oid}}, upsert=True)
        A.update_music_prefs(prefs, mood, track_key, accepted)
    elif domain == "recipe":
        if not recipe_id: return {"ok": False, "error": "recipe_id required"}
        if not accepted:
            db.recipe_rejections.insert_one({"user_id": uid, "recipe_id": recipe_id, "mood_log_id": log_oid, "created_at": now()})
        A.update_recipe_prefs(prefs, mood, recipe_id, accepted)
    else:
        return {"ok": False, "error": "unknown domain"}
    save_prefs(uid, prefs)
    return {"ok": True}


def delete_wardrobe_item(uid, item_id) -> bool:
    """Delete a wardrobe item, its GridFS photo, and (cascade) every outfit that references it."""
    oid = to_oid(item_id)
    it = db.wardrobe_items.find_one({"_id": oid, "user_id": uid}) if oid else None
    if not it: return False
    if it.get("photo_id"):
        try: fs.delete(it["photo_id"])
        except Exception: pass
    db.outfits.delete_many({"user_id": uid, "item_ids": it["_id"]})
    db.wardrobe_items.delete_one({"_id": it["_id"]})
    return True


def orphan_outfit_count() -> int:
    """Referential-integrity check: outfits that reference a missing wardrobe item or mood log."""
    bad = 0
    ids = {d["_id"] for d in db.wardrobe_items.find({}, {"_id": 1})}
    logs = {d["_id"] for d in db.mood_logs.find({}, {"_id": 1})}
    for o in db.outfits.find({}, {"item_ids": 1, "mood_log_id": 1}):
        if any(i not in ids for i in o.get("item_ids", [])) or (o.get("mood_log_id") and o["mood_log_id"] not in logs): bad += 1
    return bad
