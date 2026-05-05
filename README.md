# TRACKSIEVE

A self-hosted Spotify playlist duplicate removal desk.

TRACKSIEVE scans a Spotify playlist, groups duplicate tracks, previews what will be kept or removed, and removes the later copies only after confirmation.

## Duplicate Modes

- `Exact`: matches identical Spotify track URIs.
- `Soft`: matches normalized primary artist and title, which can catch some duplicate editions and remasters.

## Local Development

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_DEBUG="true"
python app.py
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Set the Spotify app redirect URI to `http://localhost:5000/api/auth/callback` for local testing.

## Docker

Copy `.env.example` to `.env`, fill in Spotify credentials, then run:

```powershell
docker compose up --build
```

## Production

Target domain: `https://tracksieve.emlw.dev`

On the server, the app lives at `/opt/tracksieve`. Caddy runs in Docker on the shared `web` network and reverse proxies `tracksieve.emlw.dev` to `tracksieve-frontend:80`; see `deploy/caddy.tracksieve.conf`.

GitHub Actions deploys on pushes to `main` over SSH. Required repository secrets:

- `SSH_HOST`
- `SSH_USER`
- `SSH_PORT`
- `SSH_PRIVATE_KEY`

The server also needs `/opt/tracksieve/.env` populated with Spotify credentials. The Spotify developer app must include `https://tracksieve.emlw.dev/api/auth/callback` as an allowed redirect URI.
