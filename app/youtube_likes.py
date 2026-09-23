import json
import logging
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
DEFAULT_CLIENT_SECRET = "youtube_client_secret.json"


def _data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        path = Path(base) / "InstinctBot"
    else:
        path = Path.home() / ".instinct_bot"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _client_secret_path() -> Path:
    configured = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(DEFAULT_CLIENT_SECRET)


def _token_path() -> Path:
    configured = os.getenv("YOUTUBE_TOKEN_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _data_dir() / "youtube_token.json"


def _load_credentials() -> Credentials:
    token_path = _token_path()
    credentials = None

    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            logging.exception("Could not read YouTube OAuth token")
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    if credentials and credentials.valid:
        return credentials

    client_secret = _client_secret_path()
    if not client_secret.exists():
        raise FileNotFoundError(
            f"YouTube OAuth client file not found: {client_secret}. "
            "Create an OAuth Desktop client and set YOUTUBE_CLIENT_SECRET_FILE."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def get_video_rating(video_id: str) -> str:
    """Return the authorized account's current rating for a YouTube video."""
    if not video_id:
        return "unspecified"

    credentials = _load_credentials()
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = youtube.videos().getRating(id=video_id).execute()
    items = response.get("items", [])
    return items[0].get("rating", "unspecified") if items else "unspecified"


def like_video(video_id: str) -> bool:
    """Put a real Like on YouTube using the authorized Google account."""
    if not video_id:
        return False

    credentials = _load_credentials()
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    youtube.videos().rate(id=video_id, rating="like").execute()
    logging.info("YouTube video %s liked successfully", video_id)
    return True
