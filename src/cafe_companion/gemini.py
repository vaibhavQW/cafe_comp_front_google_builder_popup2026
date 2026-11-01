"""Gemini-powered features: menu recommendations, room vibe, icebreakers.

Every function has a deterministic fallback so the app works without an API key.
"""

import json
import logging
import time

from .config import settings

log = logging.getLogger(__name__)
_client = None
_cache: dict[str, tuple[float, dict]] = {}


def _get_client():
    global _client
    if _client is None and settings.gemini_api_key:
        from google import genai

        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _ask_json(prompt: str) -> dict | None:
    client = _get_client()
    if not client:
        return None
    try:
        from google.genai import types

        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.7),
        )
        return json.loads(resp.text or "{}")
    except Exception as e:  # network / quota / parse errors → fall back
        log.warning("Gemini call failed: %s", e)
        return None


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.monotonic(), val)
    return val


# ---------------------------------------------------------------- recommendations
def recommend(mood: str, menu: list[dict], wait_minutes: int) -> dict:
    prompt = f"""You are a friendly barista at a cafe. A guest describes what they feel like.
Pick 1-3 items ONLY from this menu (use the exact ids). Current kitchen wait is about {wait_minutes} min;
if the guest is in a hurry prefer items with low prep_minutes.

Menu JSON: {json.dumps(menu)}

Guest says: {mood[:300]!r}

Reply as JSON: {{"message": "one warm sentence", "picks": [{{"id": <menu id>, "reason": "short reason"}}]}}"""
    data = _ask_json(prompt)
    valid_ids = {m["id"] for m in menu}
    if data and isinstance(data.get("picks"), list):
        picks = [p for p in data["picks"] if isinstance(p, dict) and p.get("id") in valid_ids][:3]
        if picks:
            return {"message": str(data.get("message", ""))[:300], "picks": picks, "ai": True}

    # Fallback: simple keyword match, else quickest items.
    words = {w for w in mood.lower().split() if len(w) > 2}
    scored = sorted(
        menu,
        key=lambda m: (-sum(w in (m["name"] + " " + m["description"] + " " + " ".join(m["tags"])).lower() for w in words), m["prep_minutes"]),
    )
    return {
        "message": "Here are a few things guests love right now.",
        "picks": [{"id": m["id"], "reason": m["description"][:80] or m["category"]} for m in scored[:3]],
        "ai": False,
    }


# ---------------------------------------------------------------- understanding the room
def room_vibe(cafe_name: str, people: list[dict]) -> dict:
    if not people:
        return {"summary": "It's quiet right now — you're the first one here.", "themes": [], "icebreakers": [], "ai": False}

    key = "room:" + cafe_name + ":" + ",".join(sorted(str(p["id"]) for p in people))

    def build():
        prompt = f"""You help strangers at a cafe called {cafe_name!r} discover what they have in common.
Below are people who chose to share their public profile in this cafe right now.
Write a short, warm, non-creepy read of the room. Never guess sensitive traits
(health, religion, politics, sexuality, ethnicity). Base everything on the data only.

People JSON: {json.dumps(people)}

Reply as JSON: {{"summary": "2 sentences", "themes": ["up to 4 short shared-interest tags"], "icebreakers": ["up to 3 open questions anyone here could ask"]}}"""
        data = _ask_json(prompt)
        if data and data.get("summary"):
            return {
                "summary": str(data["summary"])[:500],
                "themes": [str(t)[:40] for t in data.get("themes", [])][:4],
                "icebreakers": [str(t)[:160] for t in data.get("icebreakers", [])][:3],
                "ai": True,
            }
        creators = sum(1 for p in people if p.get("youtube") or p.get("blogs"))
        return {
            "summary": f"{len(people)} people are open to meeting here. {creators} of them create content online.",
            "themes": ["coffee"] + (["creators"] if creators else []),
            "icebreakers": ["What brings you here today?", "What's your go-to order here?"],
            "ai": False,
        }

    return _cached(key, 120, build)


def icebreaker(me: dict, them: dict) -> dict:
    key = f"ice:{me['id']}:{them['id']}"

    def build():
        prompt = f"""Two people are at the same cafe. Suggest friendly, specific conversation openers
person A could use with person B, based ONLY on their shared public profile data. Keep it light,
respectful and non-creepy; do not reference anything not present below.

Person A: {json.dumps(me)}
Person B: {json.dumps(them)}

Reply as JSON: {{"common_ground": "one sentence or empty", "openers": ["2-3 short openers"]}}"""
        data = _ask_json(prompt)
        if data and data.get("openers"):
            return {
                "common_ground": str(data.get("common_ground", ""))[:240],
                "openers": [str(o)[:200] for o in data["openers"]][:3],
                "ai": True,
            }
        openers = [f"Hi {them['name'].split()[0]}! What are you having today?"]
        if them.get("youtube"):
            openers.append(f"I saw your channel “{them['youtube']['title']}” — what do you make videos about?")
        if them.get("blogs"):
            openers.append(f"You write “{them['blogs'][0]['name']}”? What's the latest post about?")
        return {"common_ground": "", "openers": openers, "ai": False}

    return _cached(key, 600, build)
