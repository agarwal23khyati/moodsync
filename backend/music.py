"""Music helpers: resolve a song to a playable 30-second preview (iTunes Search API, no key needed)
and turn a pasted YouTube / Spotify link into a safe embed URL. Pure functions + one async resolver."""
import asyncio, hashlib, re
from typing import Optional
from urllib.parse import urlparse, parse_qs

ITUNES = "https://itunes.apple.com/search"
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_SP = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist|episode|show)/([A-Za-z0-9]{10,30})")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def pick_itunes_match(results: list, title: str, artist: str) -> Optional[dict]:
    """Best iTunes hit with a preview: title must match; artist overlap breaks ties."""
    t, a = _norm(title), set(_norm(artist).split())
    best, best_s = None, 0.0
    for r in results or []:
        if not r.get("previewUrl"): continue
        rt = _norm(r.get("trackName", ""))
        if not rt: continue
        s = 0.0
        if rt == t: s += 3
        elif t in rt or rt in t: s += 1.5
        else: continue                                   # wrong song entirely
        ra = set(_norm(r.get("artistName", "")).split())
        if a and ra: s += 2.0 * len(a & ra) / len(a)
        if s > best_s: best, best_s = r, s
    return best


def match_to_fields(r: dict) -> dict:
    art = (r.get("artworkUrl100") or "").replace("100x100", "400x400")
    return {"preview_url": r["previewUrl"], "artwork": art, "apple_url": r.get("trackViewUrl", ""),
            "album": r.get("collectionName", ""), "duration_ms": r.get("trackTimeMillis")}


async def resolve_one(http, title: str, artist: str, country: str = "IN"):
    """-> (fields or None, reached). reached=False means iTunes could not be contacted at all (offline), so the
    caller must NOT remember a 'no match' - only a real empty answer is cached as a miss."""
    q = f"{title} {artist.split(' &')[0]}"
    reached = False
    for ctry in dict.fromkeys([country, "US"]):          # Indian catalogue first, then global
        try:
            r = await http.get(ITUNES, params={"term": q, "entity": "song", "limit": 8, "country": ctry})
            r.raise_for_status()
            reached = True
            m = pick_itunes_match(r.json().get("results", []), title, artist)
            if m: return match_to_fields(m), True
        except Exception:
            continue
    return None, reached


async def resolve_many(http, tracks: list, country: str = "IN", limit: int = 4) -> dict:
    sem = asyncio.Semaphore(limit)

    async def one(t):
        async with sem: return t["key"], await resolve_one(http, t["title"], t.get("artist", ""), country)
    return dict(await asyncio.gather(*[one(t) for t in tracks]))


async def link_meta(http, link: dict) -> dict:
    """Best-effort title / thumbnail for a pasted link via the providers' public oEmbed endpoints (no key)."""
    url = ("https://www.youtube.com/oembed" if link["provider"] == "youtube" else "https://open.spotify.com/oembed")
    try:
        r = await http.get(url, params={"url": link["external"], "format": "json"})
        r.raise_for_status(); j = r.json()
        return {"title": j.get("title", ""), "author": j.get("author_name", ""), "thumbnail": j.get("thumbnail_url", "")}
    except Exception:
        return {}


# ------------------------------------------------------------------ pasted links -> embeds
def parse_music_link(url: str) -> Optional[dict]:
    """Return {'provider','embed','external','kind','ref'} for YouTube/Spotify links, else None.
    The embed URL is rebuilt from a validated ID only - user text never goes into the iframe src."""
    url = (url or "").strip()
    if not url: return None
    if not re.match(r"^https?://", url): url = "https://" + url
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    vid = None
    if host == "youtu.be": vid = p.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if p.path == "/watch": vid = (parse_qs(p.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(?:shorts|embed|live)/([^/?]+)", p.path)
            vid = m.group(1) if m else None
        if not vid and p.path == "/playlist":
            lid = (parse_qs(p.query).get("list") or [""])[0]
            if re.match(r"^[A-Za-z0-9_-]{10,60}$", lid):
                return {"provider": "youtube", "kind": "playlist", "ref": lid,
                        "embed": f"https://www.youtube.com/embed/videoseries?list={lid}&autoplay=1&rel=0",
                        "external": f"https://www.youtube.com/playlist?list={lid}"}
    if vid and _YT_ID.match(vid):
        return {"provider": "youtube", "kind": "video", "ref": vid,
                "embed": f"https://www.youtube.com/embed/{vid}?autoplay=1&rel=0&playsinline=1",
                "external": f"https://www.youtube.com/watch?v={vid}"}
    if host == "open.spotify.com":
        m = _SP.search(url)
        if m:
            kind, ref = m.groups()
            return {"provider": "spotify", "kind": kind, "ref": ref,
                    "embed": f"https://open.spotify.com/embed/{kind}/{ref}?utm_source=moodsync",
                    "external": f"https://open.spotify.com/{kind}/{ref}"}
    return None


def custom_track_key(uid, ref: str) -> str:
    return "u" + hashlib.sha1(f"{uid}:{ref}".encode()).hexdigest()[:14]
