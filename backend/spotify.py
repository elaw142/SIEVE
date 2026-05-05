import base64
import hashlib
import os
import re
import secrets
import time
from collections import defaultdict
from urllib.parse import urlencode

import requests
from flask import session
from requests import RequestException


SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private user-read-private"
SPOTIFY_TIMEOUT = float(os.environ.get("SPOTIFY_TIMEOUT", "12"))


class SpotifyError(RuntimeError):
    def __init__(self, message, status_code=502, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {"error": message}


def _client_id():
    return os.environ.get("SPOTIFY_CLIENT_ID", "")


def _client_secret():
    return os.environ.get("SPOTIFY_CLIENT_SECRET", "")


def _redirect_uri():
    return os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:5000/api/auth/callback")


def _base64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce_pair():
    verifier = _base64url(secrets.token_bytes(64))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url():
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    session["spotify_pkce_verifier"] = verifier
    session["spotify_oauth_state"] = state

    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": SCOPES,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


def exchange_code(code, state):
    if not code:
        raise SpotifyError("Missing authorization code", 400)
    if state != session.get("spotify_oauth_state"):
        raise SpotifyError("Invalid OAuth state", 400)

    verifier = session.get("spotify_pkce_verifier")
    data = {
        "client_id": _client_id(),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
        "code_verifier": verifier,
    }
    if _client_secret():
        data["client_secret"] = _client_secret()

    token = _token_request(data)
    save_token(token)
    session.pop("spotify_pkce_verifier", None)
    session.pop("spotify_oauth_state", None)


def _token_request(data):
    response = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=SPOTIFY_TIMEOUT)
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise SpotifyError("Spotify token exchange failed", response.status_code, payload)
    return payload


def save_token(token):
    session["spotify_token"] = {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token") or session.get("spotify_token", {}).get("refresh_token"),
        "expires_at": int(time.time()) + int(token.get("expires_in", 3600)) - 60,
        "scope": token.get("scope", ""),
        "token_type": token.get("token_type", "Bearer"),
    }


def clear_token():
    session.pop("spotify_token", None)


def current_token():
    token = session.get("spotify_token")
    if not token:
        raise SpotifyError("Not authenticated", 401)
    if token.get("expires_at", 0) <= int(time.time()):
        refresh_token(token)
    return session["spotify_token"]["access_token"]


def refresh_token(token):
    refresh = token.get("refresh_token")
    if not refresh:
        clear_token()
        raise SpotifyError("Session expired", 401)

    data = {
        "client_id": _client_id(),
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }
    if _client_secret():
        data["client_secret"] = _client_secret()
    save_token(_token_request(data))


def api_request(method, path, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {current_token()}"
    headers.setdefault("Content-Type", "application/json")

    try:
        response = requests.request(
            method,
            f"{SPOTIFY_API_BASE}{path}",
            headers=headers,
            timeout=SPOTIFY_TIMEOUT,
            **kwargs,
        )
    except RequestException as exc:
        raise SpotifyError("Spotify did not respond quickly enough", 504, {"error": str(exc)})

    if response.status_code == 204:
        return {}
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}
    if response.status_code >= 400:
        if response.status_code == 429:
            payload["retry_after"] = response.headers.get("Retry-After", "")
        raise SpotifyError("Spotify API request failed", response.status_code, payload)
    return payload


def me():
    return api_request("GET", "/me")


def list_playlists():
    items = []
    offset = 0
    while True:
        payload = api_request("GET", "/me/playlists", params={"limit": 50, "offset": offset})
        items.extend(payload.get("items") or [])
        if not payload.get("next"):
            break
        offset += 50
    return {"playlists": [compact_playlist(item) for item in items]}


def compact_playlist(playlist):
    images = playlist.get("images") or []
    owner = playlist.get("owner") or {}
    return {
        "id": playlist.get("id"),
        "name": playlist.get("name"),
        "description": playlist.get("description") or "",
        "image": images[0].get("url") if images else "",
        "owner": owner.get("display_name") or owner.get("id") or "",
        "tracksTotal": (playlist.get("tracks") or {}).get("total", 0),
        "public": playlist.get("public"),
    }


def playlist_snapshot(playlist_id):
    return api_request("GET", f"/playlists/{playlist_id}", params={"fields": "id,name,snapshot_id,tracks(total)"})


def playlist_items(playlist_id):
    items = []
    offset = 0
    while True:
        payload = api_request(
            "GET",
            f"/playlists/{playlist_id}/tracks",
            params={
                "limit": 100,
                "offset": offset,
                "fields": (
                    "next,items(added_at,is_local,track(id,uri,name,duration_ms,"
                    "album(release_date,images),artists(name)))"
                ),
            },
        )
        page_items = payload.get("items") or []
        for index, item in enumerate(page_items):
            item["position"] = offset + index
            items.append(item)
        if not payload.get("next"):
            break
        offset += 100
    return items


def normalize_track(track):
    album = track.get("album") or {}
    artists = track.get("artists") or []
    images = album.get("images") or []
    return {
        "id": track.get("id") or "",
        "uri": track.get("uri") or "",
        "name": track.get("name") or "Unknown track",
        "artist": ", ".join(artist.get("name", "") for artist in artists if artist.get("name")),
        "year": (album.get("release_date") or "")[:4],
        "image": images[-1].get("url") if images else "",
        "durationMs": track.get("duration_ms") or 0,
    }


def normalized_text(value):
    value = (value or "").lower()
    value = re.sub(r"\([^)]*(remaster|deluxe|edition|version|explicit|clean|radio edit)[^)]*\)", "", value)
    value = re.sub(r"\[[^]]*(remaster|deluxe|edition|version|explicit|clean|radio edit)[^]]*\]", "", value)
    value = re.sub(r"[-–—]\s*(remaster(ed)?|deluxe|explicit|clean|radio edit).*$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def duplicate_key(track, mode):
    if mode == "soft":
        first_artist = (track.get("artists") or [{}])[0].get("name", "")
        return f"{normalized_text(first_artist)}::{normalized_text(track.get('name'))}"
    return track.get("uri") or track.get("id") or ""


def analyse_duplicates(playlist_id, mode="exact"):
    mode = "soft" if mode == "soft" else "exact"
    snapshot = playlist_snapshot(playlist_id)
    groups = defaultdict(list)
    skipped = 0

    for item in playlist_items(playlist_id):
        track = item.get("track") or {}
        if item.get("is_local") or not track.get("uri"):
            skipped += 1
            continue
        key = duplicate_key(track, mode)
        if not key:
            skipped += 1
            continue
        groups[key].append(
            {
                "position": item["position"],
                "addedAt": item.get("added_at") or "",
                "track": normalize_track(track),
            }
        )

    duplicate_groups = []
    duplicate_count = 0
    for key, occurrences in groups.items():
        if len(occurrences) < 2:
            continue
        occurrences.sort(key=lambda item: item["position"])
        duplicate_count += len(occurrences) - 1
        duplicate_groups.append({"key": key, "keep": occurrences[0], "remove": occurrences[1:], "count": len(occurrences)})

    duplicate_groups.sort(key=lambda group: group["keep"]["position"])
    return {
        "playlist": {
            "id": snapshot.get("id"),
            "name": snapshot.get("name"),
            "snapshotId": snapshot.get("snapshot_id"),
            "tracksTotal": (snapshot.get("tracks") or {}).get("total", 0),
        },
        "mode": mode,
        "groups": duplicate_groups,
        "duplicateCount": duplicate_count,
        "groupCount": len(duplicate_groups),
        "skippedCount": skipped,
    }


def remove_duplicates(playlist_id, mode="exact"):
    analysis = analyse_duplicates(playlist_id, mode)
    removals_by_uri = defaultdict(list)
    for group in analysis["groups"]:
        for occurrence in group["remove"]:
            removals_by_uri[occurrence["track"]["uri"]].append(occurrence["position"])

    removals = [{"uri": uri, "positions": sorted(positions)} for uri, positions in removals_by_uri.items()]
    snapshot_id = analysis["playlist"].get("snapshotId")
    removed_count = sum(len(item["positions"]) for item in removals)

    next_snapshot = snapshot_id
    for index in range(0, len(removals), 100):
        payload = {"tracks": removals[index : index + 100]}
        if next_snapshot:
            payload["snapshot_id"] = next_snapshot
        result = api_request("DELETE", f"/playlists/{playlist_id}/tracks", json=payload)
        next_snapshot = result.get("snapshot_id") or next_snapshot

    return {
        "removedCount": removed_count,
        "groupCount": analysis["groupCount"],
        "snapshotId": next_snapshot,
        "mode": analysis["mode"],
    }
