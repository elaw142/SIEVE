import os

from flask import Flask, jsonify, redirect, request
from flask_cors import CORS

from spotify import (
    SpotifyError,
    analyse_duplicates,
    build_authorize_url,
    clear_token,
    exchange_code,
    list_playlists,
    me,
    remove_duplicates,
)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    )
    cors_origins = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173,http://localhost:5174").split(",")
    CORS(app, supports_credentials=True, origins=cors_origins)

    @app.errorhandler(SpotifyError)
    def handle_spotify_error(error):
        return jsonify(error.payload), error.status_code

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": "tracksieve"}

    @app.get("/api/auth/login")
    def login():
        if not os.environ.get("SPOTIFY_CLIENT_ID"):
            return jsonify({"error": "SPOTIFY_CLIENT_ID is not configured"}), 500
        return redirect(build_authorize_url())

    @app.get("/api/auth/callback")
    def callback():
        exchange_code(request.args.get("code"), request.args.get("state"))
        return redirect(os.environ.get("AUTH_SUCCESS_REDIRECT", "http://localhost:5174"))

    @app.post("/api/auth/logout")
    def logout():
        clear_token()
        return {"ok": True}

    @app.get("/api/auth/me")
    def auth_me():
        return jsonify({"user": me()})

    @app.get("/api/playlists")
    def playlists():
        return jsonify(list_playlists())

    @app.get("/api/playlists/<playlist_id>/duplicates")
    def playlist_duplicates(playlist_id):
        return jsonify(analyse_duplicates(playlist_id, request.args.get("mode", "exact")))

    @app.post("/api/playlists/<playlist_id>/remove-duplicates")
    def playlist_remove_duplicates(playlist_id):
        payload = request.get_json(force=True) or {}
        return jsonify(remove_duplicates(playlist_id, payload.get("mode", "exact")))

    return app


app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug, threaded=True)
