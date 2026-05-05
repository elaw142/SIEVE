import base64
import hashlib
import json
import os
import random
import secrets
import re
import time
from urllib.parse import urlencode

import requests
from flask import session


SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SCOPES = "playlist-modify-public playlist-modify-private user-read-private"
DEFAULT_GENRES = [
    "pop",
    "rock",
    "hip-hop",
    "electronic",
    "dance",
    "r-n-b",
    "indie",
    "alternative",
    "metal",
    "punk",
    "jazz",
    "soul",
    "country",
    "folk",
    "latin",
    "reggae",
    "classical",
]
DEFAULT_MARKET = os.environ.get("SPOTIFY_MARKET", "NZ")


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
    response = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=15)
    if response.status_code >= 400:
        raise SpotifyError("Spotify token exchange failed", response.status_code, response.json())
    return response.json()


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

    response = requests.request(
        method,
        f"{SPOTIFY_API_BASE}{path}",
        headers=headers,
        timeout=20,
        **kwargs,
    )
    if response.status_code == 204:
        return {}
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}
    if response.status_code >= 400:
        raise SpotifyError("Spotify API request failed", response.status_code, payload)
    return payload


def me():
    return api_request("GET", "/me")


def clamp_page_limit(limit):
    return min(max(int(limit), 1), 10)


def clamp_total_limit(limit):
    return min(max(int(limit), 1), 50)


def search_page(query, item_type="track", limit=10, offset=0):
    return api_request(
        "GET",
        "/search",
        params={
            "q": query,
            "type": item_type,
            "limit": clamp_page_limit(limit),
            "offset": max(int(offset), 0),
            "market": DEFAULT_MARKET,
        },
    )


def search_artists(query, limit=10):
    return search_page(query, "artist", limit)


def compact_name(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def parse_prompt_artists(prompt):
    if "," not in prompt:
        return []

    candidates = []
    for item in re.split(r",|\n|;|/|\betc\b", prompt, flags=re.IGNORECASE):
        cleaned = re.sub(r"\([^)]*\)", "", item).strip(" .:-")
        if not cleaned or len(cleaned) > 40:
            continue
        if len(cleaned.split()) > 4:
            continue
        if compact_name(cleaned) in {"and", "similar", "artists", "music", "songs"}:
            continue
        candidates.append(cleaned)
    return candidates[:12]


def best_artist_match(name):
    payload = search_artists(name, 5)
    artists = payload.get("artists", {}).get("items") or []
    if not artists:
        return None

    target = compact_name(name)
    exact = [artist for artist in artists if compact_name(artist.get("name")) == target]
    if exact:
        return exact[0]
    return artists[0]


def artist_top_tracks(artist_id):
    payload = api_request("GET", f"/artists/{artist_id}/top-tracks", params={"market": DEFAULT_MARKET})
    return payload.get("tracks") or []


def artist_seed_tracks(artist_id=None, artist_name="", limit=12):
    if artist_id:
        try:
            tracks = artist_top_tracks(artist_id)
            if tracks:
                return tracks[:limit]
        except SpotifyError:
            pass
    if not artist_name:
        return []
    payload = search_tracks(f'artist:"{artist_name}"', limit, variance=True, min_popularity=0)
    return payload.get("tracks", {}).get("items") or []


def unique_tracks(items, min_popularity=0):
    seen = set()
    tracks = []
    for track in items:
        track_id = track.get("id")
        if not track_id or track_id in seen:
            continue
        if int(track.get("popularity") or 0) < min_popularity:
            continue
        seen.add(track_id)
        tracks.append(track)
    return tracks


def search_tracks(query, limit=20, offset=0, variance=False, min_popularity=0):
    total_limit = clamp_total_limit(limit)
    page_offsets = list(range(max(int(offset), 0), max(int(offset), 0) + total_limit + 30, 10))
    if variance:
        base_offsets = list(range(0, 200, 10))
        random.shuffle(base_offsets)
        page_offsets = base_offsets[: max(6, (total_limit // 10) + 3)]

    items = []
    last_payload = None
    for page_offset in page_offsets:
        payload = search_page(query, "track", 10, page_offset)
        last_payload = payload
        page_items = payload.get("tracks", {}).get("items") or []
        items.extend(page_items)
        items = unique_tracks(items, min_popularity)
        if len(items) >= total_limit:
            break
        if not payload.get("tracks", {}).get("next"):
            break

    payload = last_payload or {"tracks": {"items": []}}
    payload["tracks"]["items"] = items[:total_limit]
    payload["tracks"]["limit"] = total_limit
    payload["tracks"]["offset"] = int(offset or 0)
    return payload


def search_track_variants(queries, limit=20, variance=True, shuffle_queries=True, shuffle_results=True, min_popularity=0):
    total_limit = clamp_total_limit(limit)
    items = []
    usable_queries = [query for query in queries if query.strip()]
    if shuffle_queries:
        random.shuffle(usable_queries)
    for query in usable_queries:
        payload = search_tracks(query, max(10, total_limit), variance=variance, min_popularity=min_popularity)
        items.extend(payload.get("tracks", {}).get("items") or [])
        items = unique_tracks(items, min_popularity)
        if len(items) >= total_limit:
            break
    if shuffle_results:
        random.shuffle(items)
    return {"tracks": {"items": items[:total_limit], "limit": total_limit, "offset": 0}}


def balanced_search_variants(queries, limit=20, min_popularity=0):
    total_limit = clamp_total_limit(limit)
    items = []
    usable_queries = [query for query in queries if query.strip()]
    for query in usable_queries:
        payload = search_tracks(query, min(10, total_limit), variance=True, min_popularity=min_popularity)
        query_items = payload.get("tracks", {}).get("items") or []
        random.shuffle(query_items)
        items.extend(query_items[: max(2, total_limit // max(len(usable_queries), 1))])
        items = unique_tracks(items, min_popularity)

    if len(items) < total_limit:
        for query in usable_queries:
            payload = search_tracks(query, total_limit, variance=True, min_popularity=min_popularity)
            items.extend(payload.get("tracks", {}).get("items") or [])
            items = unique_tracks(items, min_popularity)
            if len(items) >= total_limit:
                break

    random.shuffle(items)
    return items[:total_limit]


def adjacent_swap_variants(word):
    variants = []
    if len(word) < 4 or len(word) > 12:
        return variants
    for index in range(len(word) - 1):
        chars = list(word)
        chars[index], chars[index + 1] = chars[index + 1], chars[index]
        variants.append("".join(chars))
    return variants


def forgiving_queries(query):
    clean = re.sub(r"\s+", " ", query.strip())
    words = clean.split(" ")
    variants = [clean]
    if len(words) > 1:
        variants.append(" ".join(words[:-1]))
    for word_index, word in enumerate(words):
        for swapped in adjacent_swap_variants(word.lower()):
            next_words = words[:]
            next_words[word_index] = swapped
            variants.append(" ".join(next_words))
    deduped = []
    for variant in variants:
        if variant and variant not in deduped:
            deduped.append(variant)
    return deduped[:35]


def generous_search(query, limit=20):
    return search_track_variants(
        forgiving_queries(query),
        limit,
        variance=False,
        shuffle_queries=False,
        shuffle_results=False,
    )


def recommendations(params):
    genres = [genre for genre in (params.get("seed_genres") or "").split(",") if genre]
    artist_ids = [artist_id for artist_id in (params.get("seed_artist_ids") or "").split(",") if artist_id]
    artist_names = [artist for artist in (params.get("seed_artist_names") or "").split(",") if artist]
    total_limit = clamp_total_limit(params.get("limit", 20))
    items = []
    queries = []

    if artist_ids:
        for index, artist_id in enumerate(artist_ids[:8]):
            artist_name = artist_names[index] if index < len(artist_names) else ""
            items.extend(artist_seed_tracks(artist_id, artist_name, 12))
        random.shuffle(items)

    if genres and artist_names:
        for genre in genres[:3]:
            for artist in artist_names[:5]:
                queries.append(f'genre:{genre} artist:"{artist}"')
    elif genres:
        queries.extend([f"genre:{genre}" for genre in genres[:5]])
    elif artist_names:
        queries.extend([f'artist:"{artist}"' for artist in artist_names[:8]])
        queries.extend(artist_names[:8])
    elif not items:
        queries.extend(["tag:new", "tag:hipster", "year:2020-2026"])

    if queries:
        payload = search_track_variants(queries, max(total_limit, 30), min_popularity=10)
        items.extend(payload.get("tracks", {}).get("items") or [])

    tracks = unique_tracks(items)
    random.shuffle(tracks)
    return {"tracks": {"items": tracks[:total_limit], "limit": total_limit, "offset": 0}}


def era_search(params):
    genre = (params.get("genre") or "").strip()
    start = int(params.get("yearStart") or params.get("year_start") or 2010)
    end = int(params.get("yearEnd") or params.get("year_end") or start)
    if start > end:
        start, end = end, start

    years = list(range(start, end + 1))
    random.shuffle(years)
    decade_query = f"genre:{genre} year:{start}-{end}" if genre else f"year:{start}-{end}"
    queries = [decade_query, f"{genre} {start}s" if genre else f"{start}s"]
    queries.extend(f"genre:{genre} year:{year}" if genre else f"year:{year}" for year in years[:10])
    payload = search_track_variants(queries, params.get("limit", 30), min_popularity=35)
    if len(payload.get("tracks", {}).get("items") or []) < 10:
        payload = search_track_variants(queries, params.get("limit", 30), min_popularity=15)
    return payload


def genres():
    return {"genres": DEFAULT_GENRES}


def vibe_plan(prompt):
    model = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct")
    ollama_url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
    response = requests.post(
        f"{ollama_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": "json",
            "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "2m"),
            "options": {"temperature": 0.2, "num_ctx": 2048},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You convert loose playlist vibes into practical Spotify discovery inputs. "
                        "Return only JSON with keys: genre, yearStart, yearEnd, seedArtists, seedGenres, manualQuery, "
                        "queryVariants, notes. queryVariants must be usable Spotify track search strings. "
                        "If the user gives artist names, preserve each artist and correct obvious misspellings. "
                        "Prefer widely available English-language music unless asked otherwise."
                    ),
                },
                {"role": "user", "content": prompt[:1200]},
            ],
        },
        timeout=90,
    )
    payload = response.json()
    if response.status_code >= 400:
        raise SpotifyError("Local AI vibe planning failed", response.status_code, payload)

    text = (payload.get("message", {}) or {}).get("content", "").strip()
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpotifyError("AI returned an invalid plan", 502, {"error": str(exc), "raw": text})
    return {"plan": plan}


def vibe_search(prompt, limit=30):
    total_limit = clamp_total_limit(limit)
    prompt_artists = parse_prompt_artists(prompt)
    plan = {"seedArtists": prompt_artists, "queryVariants": forgiving_queries(prompt)[:6]} if len(prompt_artists) >= 2 else vibe_plan(prompt).get("plan") or {}
    plan_artists = plan.get("seedArtists") if isinstance(plan.get("seedArtists"), list) else []
    artist_names = []
    for name in [*prompt_artists, *plan_artists]:
        if isinstance(name, str) and compact_name(name) and compact_name(name) not in [compact_name(item) for item in artist_names]:
            artist_names.append(name)

    items = []
    matched_artists = []
    for artist_name in artist_names[:10]:
        artist = best_artist_match(artist_name)
        if not artist:
            continue
        matched_artists.append({"id": artist.get("id"), "name": artist.get("name")})
        top_tracks = artist_seed_tracks(artist["id"], artist.get("name", ""), 12)
        random.shuffle(top_tracks)
        items.extend(top_tracks[:4])

    query_variants = plan.get("queryVariants") if isinstance(plan.get("queryVariants"), list) else []
    manual_query = plan.get("manualQuery") if isinstance(plan.get("manualQuery"), str) else ""
    seed_genres = plan.get("seedGenres") if isinstance(plan.get("seedGenres"), list) else []
    genre = plan.get("genre") if isinstance(plan.get("genre"), str) else ""

    queries = []
    queries.extend(query for query in query_variants if isinstance(query, str))
    if manual_query:
        queries.append(manual_query)
    for artist in matched_artists[:6]:
        queries.append(f'artist:"{artist["name"]}"')
        for seed_genre in seed_genres[:2]:
            if isinstance(seed_genre, str):
                queries.append(f'{artist["name"]} {seed_genre}')
    if genre:
        queries.append(genre)
    queries.extend(forgiving_queries(prompt)[:4])

    if queries:
        items.extend(balanced_search_variants(queries, max(total_limit, 30), min_popularity=8))

    tracks = unique_tracks(items)
    random.shuffle(tracks)
    return {
        "plan": plan,
        "matchedArtists": matched_artists,
        "tracks": {"items": tracks[:total_limit], "limit": total_limit, "offset": 0},
    }


def create_playlist(user_id, name, description, track_uris):
    playlist = api_request(
        "POST",
        f"/users/{user_id}/playlists",
        json={
            "name": name,
            "description": description or "",
            "public": False,
        },
    )
    playlist_id = playlist["id"]
    for index in range(0, len(track_uris), 100):
        api_request(
            "POST",
            f"/playlists/{playlist_id}/tracks",
            json={"uris": track_uris[index : index + 100]},
        )
    return playlist
