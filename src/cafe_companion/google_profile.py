"""Fetch a signed-in user's own public Google data using the access token they granted.

Only the user's *own* data is fetched, with their explicit OAuth consent. The access
token is used once at sign-in and never stored.
"""

import logging

import httpx
from fastapi import HTTPException

from .config import settings

log = logging.getLogger(__name__)

YT_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger.readonly"


def verify_token(client: httpx.Client, access_token: str) -> set[str]:
    """Validate the token was issued to *our* OAuth client; return its granted scopes."""
    r = client.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": access_token})
    if r.status_code != 200:
        raise HTTPException(401, "Invalid Google token")
    info = r.json()
    if settings.google_client_id and info.get("aud") != settings.google_client_id and info.get("azp") != settings.google_client_id:
        raise HTTPException(401, "Token was not issued for this app")
    return set(info.get("scope", "").split())


def fetch_userinfo(client: httpx.Client, token: str) -> dict:
    r = client.get(
        "https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code != 200:
        raise HTTPException(401, "Could not read Google profile")
    return r.json()


def fetch_youtube(client: httpx.Client, token: str) -> dict | None:
    h = {"Authorization": f"Bearer {token}"}
    try:
        r = client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            headers=h,
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            return None
        ch = items[0]
        sn, st = ch.get("snippet", {}), ch.get("statistics", {})
        custom = sn.get("customUrl")
        out = {
            "channel_id": ch["id"],
            "title": sn.get("title", ""),
            "description": (sn.get("description") or "")[:400],
            "thumbnail": (sn.get("thumbnails", {}).get("medium") or sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
            "url": f"https://www.youtube.com/{custom}" if custom else f"https://www.youtube.com/channel/{ch['id']}",
            "subscribers": None if st.get("hiddenSubscriberCount") else _int(st.get("subscriberCount")),
            "videos": _int(st.get("videoCount")),
            "views": _int(st.get("viewCount")),
            "recent": [],
        }
        uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if uploads and out["videos"]:
            r2 = client.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params={"part": "snippet,status", "playlistId": uploads, "maxResults": 6},
                headers=h,
            )
            if r2.status_code == 200:
                for it in r2.json().get("items", []):
                    # Only surface videos the owner made public.
                    if it.get("status", {}).get("privacyStatus") != "public":
                        continue
                    s = it["snippet"]
                    vid = s.get("resourceId", {}).get("videoId")
                    out["recent"].append({
                        "title": s.get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "thumbnail": (s.get("thumbnails", {}).get("medium") or {}).get("url", ""),
                        "published_at": s.get("publishedAt"),
                    })
                out["recent"] = out["recent"][:3]
        return out
    except httpx.HTTPError as e:
        log.warning("YouTube fetch failed: %s", e)
        return None


def fetch_blogs(client: httpx.Client, token: str) -> list | None:
    h = {"Authorization": f"Bearer {token}"}
    try:
        r = client.get("https://www.googleapis.com/blogger/v3/users/self/blogs", headers=h)
        if r.status_code == 404:
            return []  # no Blogger profile
        r.raise_for_status()
        blogs = []
        for b in (r.json().get("items") or [])[:3]:
            entry = {"name": b.get("name", ""), "url": b.get("url", ""), "post_count": b.get("posts", {}).get("totalItems", 0), "recent": []}
            r2 = client.get(
                f"https://www.googleapis.com/blogger/v3/blogs/{b['id']}/posts",
                params={"maxResults": 3, "fetchBodies": "false", "status": "live"},
                headers=h,
            )
            if r2.status_code == 200:
                entry["recent"] = [
                    {"title": p.get("title", ""), "url": p.get("url", ""), "published_at": p.get("published")}
                    for p in r2.json().get("items", [])
                ]
            blogs.append(entry)
        return blogs
    except httpx.HTTPError as e:
        log.warning("Blogger fetch failed: %s", e)
        return None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
