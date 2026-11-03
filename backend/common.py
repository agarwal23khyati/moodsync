"""Shared by the Coordinator (main.py) and the agent service (agent_service.py):
configuration, MongoDB connection (real or in-memory mock), schema validators, indexes and seed data."""
import os, re, sys, datetime as dt
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "moodsync")
SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
INTERNAL_KEY = os.getenv("INTERNAL_KEY", "moodsync-internal")     # Coordinator -> agent service
AGENT_URL = os.getenv("AGENT_URL", "http://127.0.0.1:8001")
TZ_OFFSET_MIN = int(os.getenv("TZ_OFFSET_MIN", "330"))             # IST
MOCK = os.getenv("MOODSYNC_MOCK") == "1"                           # in-memory DB for tests/experiments
now = lambda: dt.datetime.now(dt.timezone.utc)

if MOCK:
    import mongomock, mongomock.gridfs
    mongomock.gridfs.enable_gridfs_integration()
    client = mongomock.MongoClient()
else:
    import certifi
    from pymongo import MongoClient
    kw = {"serverSelectionTimeoutMS": 5000}
    if MONGO_URI.startswith("mongodb+srv"): kw["tlsCAFile"] = certifi.where()
    client = MongoClient(MONGO_URI, **kw)
db = client[DB_NAME]
import gridfs
fs = gridfs.GridFS(db)  # wardrobe photos live inside MongoDB (GridFS)

# ------------------------------------------------------------------ schema validation ($jsonSchema)
MOODS = ["happy", "energetic", "calm", "low"]


def schema(required, props):
    return {"$jsonSchema": {"bsonType": "object", "required": required, "properties": props}}


S = lambda lo=1, hi=200: {"bsonType": "string", "minLength": lo, "maxLength": hi}
OID = {"bsonType": "objectId"}
DATE = {"bsonType": "date"}
VALIDATORS = {
    "users": schema(["name", "email", "password_hash", "created_at"],
                    {"name": S(1, 60), "email": S(3, 120), "password_hash": {"bsonType": "string"}, "created_at": DATE}),
    "mood_logs": schema(["user_id", "mood", "occasion", "created_at"],
                        {"user_id": OID, "mood": {"enum": MOODS}, "occasion": S(1, 40), "created_at": DATE}),
    "tasks": schema(["user_id", "title", "completed", "created_at"],
                    {"user_id": OID, "title": S(1, 160), "completed": {"bsonType": "bool"},
                     "completed_at": {"bsonType": ["date", "null"]}, "mood": {"enum": MOODS + [None]},
                     "mood_log_id": {"bsonType": ["objectId", "null"]}, "created_at": DATE,
                     "priority": {"enum": ["high", "medium", "low"]}, "effort": {"enum": ["quick", "medium", "deep"]},
                     "category": S(1, 30), "due_date": {"bsonType": ["date", "null"]}, "pinned": {"bsonType": "bool"}}),
    "wardrobe_items": schema(["user_id", "name", "category", "worn_count", "created_at"],
                             {"user_id": OID, "name": S(1, 80), "category": S(1, 30),
                              "worn_count": {"bsonType": ["int", "long"], "minimum": 0},
                              "last_worn": {"bsonType": ["date", "null"]},
                              "photo_id": {"bsonType": ["objectId", "null"]}, "created_at": DATE}),
    "outfits": schema(["user_id", "item_ids", "created_at"],
                      {"user_id": OID, "item_ids": {"bsonType": "array", "minItems": 1, "items": OID},
                       "mood_log_id": {"bsonType": ["objectId", "null"]},
                       "accepted": {"bsonType": ["bool", "null"]}, "created_at": DATE}),
    "grocery_items": schema(["user_id", "name", "checked", "created_at"],
                            {"user_id": OID, "name": S(1, 80), "checked": {"bsonType": "bool"}, "created_at": DATE}),
    "recipes": schema(["_id", "name", "ingredients", "time", "tags"],
                      {"_id": S(1, 60), "name": S(1, 80), "time": {"bsonType": ["int", "long"]},
                       "ingredients": {"bsonType": "array", "items": S(1, 40)}, "tags": {"bsonType": "array"}}),
    "recipe_rejections": schema(["user_id", "recipe_id", "created_at"],
                                {"user_id": OID, "recipe_id": S(1, 60), "mood_log_id": {"bsonType": ["objectId", "null"]},
                                 "created_at": DATE}),
    "tracks": schema(["_id", "title", "artist", "moods"],
                     {"_id": S(1, 100), "title": S(1, 100), "artist": S(1, 100), "moods": {"bsonType": "array"}}),
    "song_feedback": schema(["user_id", "track_key", "feedback", "mood"],
                            {"user_id": OID, "track_key": S(1, 100), "feedback": {"enum": ["like", "skip", "none"]},
                             "mood": {"enum": MOODS}, "mood_log_id": {"bsonType": ["objectId", "null"]}}),
    "play_events": schema(["user_id", "track_key", "played_at"],
                          {"user_id": OID, "track_key": S(1, 100), "mood": {"enum": MOODS + [None]},
                           "seconds": {"bsonType": ["int", "long", "double"], "minimum": 0}, "completed": {"bsonType": "bool"},
                           "source": S(1, 20), "played_at": DATE}),
    "user_preferences": schema(["user_id", "data", "updated_at"],
                               {"user_id": OID, "data": {"bsonType": "object"}, "updated_at": DATE}),
}
INDEXES = {
    "users": [([("email", ASCENDING)], {"unique": True})],
    "mood_logs": [([("user_id", ASCENDING), ("created_at", DESCENDING)], {})],
    "tasks": [([("user_id", ASCENDING), ("created_at", DESCENDING)], {}), ([("user_id", ASCENDING), ("completed", ASCENDING)], {})],
    "wardrobe_items": [([("user_id", ASCENDING), ("category", ASCENDING)], {})],
    "outfits": [([("user_id", ASCENDING), ("created_at", DESCENDING)], {}), ([("item_ids", ASCENDING)], {})],
    "grocery_items": [([("user_id", ASCENDING), ("created_at", DESCENDING)], {})],
    "recipes": [], "tracks": [],
    "recipe_rejections": [([("user_id", ASCENDING), ("recipe_id", ASCENDING)], {})],
    "song_feedback": [([("user_id", ASCENDING), ("track_key", ASCENDING)], {"unique": True})],
    "user_preferences": [([("user_id", ASCENDING)], {"unique": True})],
    "play_events": [([("user_id", ASCENDING), ("played_at", DESCENDING)], {}), ([("user_id", ASCENDING), ("track_key", ASCENDING)], {})],
}

# ------------------------------------------------------------------ seed data (moved here from the frontend)
def _key(title): return re.sub(r"[^a-z0-9]", "_", title.lower())


_T = [("Golden Hour", "JVKE", ["happy", "calm"], "🌅", "warm, glowy, main-character energy"),
      ("Levitating", "Dua Lipa", ["happy", "energetic"], "🪩", "a little sparkle and a lot of bounce"),
      ("Sunflower", "Post Malone & Swae Lee", ["happy", "calm"], "🌻", "easygoing sunshine for your ears"),
      ("Good Days", "SZA", ["low", "calm"], "☁️", "soft thoughts, softer landing"),
      ("Ilahi", "Arijit Singh", ["happy", "energetic"], "🧳", "for when you want to feel free"),
      ("Kasoor", "Prateek Kuhad", ["low", "calm"], "🌙", "gentle, reflective, late-night feelings"),
      ("Aaj Kal Zindagi", "Shankar Mahadevan", ["happy", "energetic"], "🌈", "a little reminder to enjoy the now"),
      ("Weightless", "Marconi Union", ["calm", "low"], "🫧", "ambient sounds to slow the room down"),
      ("Love You Zindagi", "Jasleen Royal", ["happy", "low"], "💛", "a little hope in song form"),
      ("Believer", "Imagine Dragons", ["energetic"], "⚡", "turn the volume up and move"),
      ("Kho Gaye Hum Kahan", "Jasleen Royal & Prateek Kuhad", ["low", "calm"], "🌌", "for the feelings you cannot quite name"),
      ("Unstoppable", "Sia", ["energetic"], "🔥", "your get-up-and-go soundtrack")]
_T += [("Happy", "Pharrell Williams", ["happy", "energetic"], "😄", "clap along, instant good mood"),
       ("Can't Stop the Feeling!", "Justin Timberlake", ["happy", "energetic"], "🕺", "dance-in-the-kitchen energy"),
       ("Badtameez Dil", "Benny Dayal", ["happy", "energetic"], "🎉", "loud, silly and so much fun"),
       ("Chaiyya Chaiyya", "Sukhwinder Singh", ["energetic", "happy"], "🚂", "a classic that never gets old"),
       ("Zingaat", "Ajay-Atul", ["energetic", "happy"], "🥁", "pure dhol-and-dance energy"),
       ("Malhari", "Vishal Dadlani", ["energetic"], "🔱", "big, bold and unstoppable"),
       ("Shape of You", "Ed Sheeran", ["happy", "energetic"], "💃", "catchy and easy to move to"),
       ("Blinding Lights", "The Weeknd", ["energetic", "happy"], "🌃", "night-drive synth rush"),
       ("Uptown Funk", "Mark Ronson & Bruno Mars", ["energetic", "happy"], "🎺", "funk that refuses to sit still"),
       ("Don't Stop Me Now", "Queen", ["energetic", "happy"], "🚀", "feel-invincible anthem"),
       ("Eye of the Tiger", "Survivor", ["energetic"], "🥊", "workout-montage classic"),
       ("Lose Yourself", "Eminem", ["energetic"], "🎤", "focus, grind, go"),
       ("Three Little Birds", "Bob Marley", ["happy", "calm"], "🐦", "every little thing is gonna be alright"),
       ("Here Comes the Sun", "The Beatles", ["happy", "calm"], "🌞", "gentle morning optimism"),
       ("Better Together", "Jack Johnson", ["calm", "happy"], "🏖️", "lazy-sunday acoustic warmth"),
       ("Perfect", "Ed Sheeran", ["calm", "happy"], "💞", "slow-dance softness"),
       ("Tera Ban Jaunga", "Akhil Sachdeva", ["calm", "happy"], "🤍", "tender and easy"),
       ("Iktara", "Kavita Seth", ["calm", "happy"], "🪕", "light, free and a little dreamy"),
       ("Raabta", "Arijit Singh", ["calm", "happy"], "🔗", "soft romance, unhurried pace"),
       ("Sunset Lover", "Petit Biscuit", ["calm", "happy"], "🌇", "golden-hour electronica"),
       ("River Flows in You", "Yiruma", ["calm", "low"], "🎹", "quiet piano for a quiet mind"),
       ("Clair de Lune", "Claude Debussy", ["calm"], "🌕", "moonlit classical calm"),
       ("Kun Faya Kun", "A. R. Rahman", ["calm", "low"], "🕊️", "spiritual, grounding, deep breath"),
       ("Tum Se Hi", "Mohit Chauhan", ["calm", "low"], "🍃", "warm and wistful"),
       ("Kabira", "Tochi Raina", ["calm", "low"], "🧡", "mellow, reflective and comforting"),
       ("Ocean Eyes", "Billie Eilish", ["calm", "low"], "🌊", "hushed and floaty"),
       ("Holocene", "Bon Iver", ["calm", "low"], "🏔️", "wide-open, quiet and still"),
       ("Fix You", "Coldplay", ["low", "calm"], "🕯️", "a slow build for heavy days"),
       ("Someone Like You", "Adele", ["low"], "💔", "for letting it all out"),
       ("Let Her Go", "Passenger", ["low", "calm"], "🚉", "melancholy but gentle"),
       ("Skinny Love", "Bon Iver", ["low", "calm"], "🍂", "raw, sparse and honest"),
       ("Tum Hi Ho", "Arijit Singh", ["low", "calm"], "🌹", "big feelings, held softly"),
       ("Channa Mereya", "Arijit Singh", ["low"], "🌫️", "heartache you can sing along to"),
       ("Agar Tum Saath Ho", "Alka Yagnik", ["low", "calm"], "🫶", "aching and beautiful"),
       ("Phir Le Aaya Dil", "Arijit Singh", ["low"], "🌧️", "rainy-window slow song")]
SEED_TRACKS = [{"_id": _key(t), "title": t, "artist": a, "moods": m, "emoji": e, "description": d,
                "url": "https://open.spotify.com/search/" + t.replace(" ", "%20") + "%20" + a.split(" &")[0].replace(" ", "%20")}
               for t, a, m, e, d in _T]

_R = [("r_paneer_ramen", "Creamy paneer ramen", "🍜", 20, ["comfort", "quick", "spicy"], ["ramen", "paneer", "cabbage", "capsicum", "milk"],
       ["cream"], "Ramen, paneer, crunchy vegetables and a creamy chilli broth.",
       "Sauté sliced vegetables and paneer. Add water and ramen seasoning, then noodles. Finish with milk or cream and chilli sauce."),
      ("r_masala_toast", "Masala veggie toast", "🥪", 12, ["quick", "spicy"], ["bread", "onion", "capsicum", "tomato"], ["cheese"],
       "Crispy toast with a quick masala vegetable filling.", "Chop vegetables finely and sauté with salt, pepper and chilli. Pile onto toast."),
      ("r_dal_rice", "Comfort dal rice bowl", "🍚", 25, ["comfort"], ["rice", "dal", "cumin", "turmeric"], ["ghee"],
       "Warm, simple, dependable and endlessly customizable.", "Cook rice and dal. Temper cumin in oil, add to dal and serve warm."),
      ("r_paneer_salad", "Fresh paneer salad", "🥗", 15, ["fresh", "quick"], ["paneer", "cucumber", "tomato", "capsicum", "lemon"], [],
       "A colourful bowl with paneer, crunchy vegetables and lemon.", "Cube paneer, chop vegetables, toss with lemon, salt and pepper."),
      ("r_schezwan_rice", "Spicy Schezwan fried rice", "🍛", 20, ["spicy", "quick"], ["rice", "cabbage", "carrot", "capsicum", "schezwan"], [],
       "A punchy, veggie-loaded way to use leftover rice.", "Stir-fry vegetables on high heat. Add rice and a spoon of Schezwan sauce."),
      ("r_banana_smoothie", "Banana peanut smoothie", "🥤", 5, ["fresh", "quick"], ["banana", "milk", "peanut butter"], ["cinnamon"],
       "A creamy snack for low-effort nourishment.", "Blend banana, milk and peanut butter until smooth."),
      ("r_tomato_soup", "Tomato soup & toast", "🍅", 20, ["comfort", "fresh"], ["tomato", "pepper", "bread"], ["butter"],
       "A cosy bowl for slower evenings.", "Simmer chopped tomatoes with water until soft. Blend, season, serve with toast."),
      ("r_chilli_noodles", "Chilli garlic noodles", "🍝", 15, ["spicy", "quick"], ["noodles", "cabbage", "carrot", "capsicum", "chilli"], [],
       "A spicy noodle bowl with whatever vegetables are around.", "Boil noodles. Stir-fry vegetables, add noodles, chilli sauce, soy sauce and pepper."),
      ("r_yogurt_bowl", "Yogurt fruit bowl", "🍓", 5, ["fresh", "quick"], ["curd", "banana", "fruit"], ["nuts"],
       "Cool, colourful and ready in minutes.", "Spoon yogurt into a bowl, add chopped fruit, top with nuts.")]
SEED_RECIPES = [{"_id": i, "name": n, "emoji": e, "time": t, "tags": tg, "ingredients": ing, "optional": opt, "desc": d, "steps": st}
                for i, n, e, t, tg, ing, opt, d, st in _R]


_ready = False


def init_db():
    global _ready
    if _ready: return
    _ready = True
    try:
        client.admin.command("ping")
    except Exception as e:
        print("\n[MoodSync] Cannot connect to MongoDB at:", MONGO_URI.split("@")[-1])
        print("  -> Local: install MongoDB Community Server and make sure the 'MongoDB' service is running.")
        print("  -> Online: check MONGO_URI in backend/.env and Atlas > Network Access.\n", e)
        sys.exit(1)
    existing = db.list_collection_names()
    for name, validator in VALIDATORS.items():
        try:
            if name in existing: db.command("collMod", name, validator=validator, validationLevel="moderate")
            else: db.create_collection(name, validator=validator)
        except Exception as e:  # e.g. a restricted tier / mock DB: app still works without validators
            if not MOCK: print(f"[MoodSync] validator for {name} skipped: {e}")
        for keys, opts in INDEXES[name]: db[name].create_index(keys, **opts)
    for coll, docs in (("tracks", SEED_TRACKS), ("recipes", SEED_RECIPES)):
        for d in docs: db[coll].update_one({"_id": d["_id"]}, {"$setOnInsert": {k: v for k, v in d.items() if k != "_id"}}, upsert=True)
    print(f"[MoodSync] MongoDB ready -> database '{DB_NAME}'" + (" (in-memory mock)" if MOCK else ""))


# ------------------------------------------------------------------ helpers
def ser(doc):
    out = {}
    for k, v in doc.items():
        if k == "_id": out["id"] = str(v)
        elif k == "user_id": continue
        elif isinstance(v, ObjectId): out[k] = str(v)
        elif isinstance(v, list): out[k] = [str(x) if isinstance(x, ObjectId) else x for x in v]
        elif isinstance(v, dt.datetime): out[k] = (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).isoformat()
        else: out[k] = v
    return out


def to_oid(s):
    try: return ObjectId(s)
    except Exception: return None


def aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
