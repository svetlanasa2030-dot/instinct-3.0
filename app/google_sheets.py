from __future__ import annotations

import os
import sys
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

DEFAULT_SHEET_ID = "1DYeyplZAPFF34gv5zIZjkxO5MDSAGsJ1ef_YSj2oTgk"
DEFAULT_CREDENTIALS_FILE = "google-service-account.json"


class GoogleSheetsError(RuntimeError):
    pass


class PlayerSheet:
    """Writes recruited players to the clan Google Sheet.

    Columns are fixed by the current table layout:
    A nickname, C level, D class, G who accepted, H TS, I Telegram.
    """

    def __init__(self):
        self.sheet_id = os.getenv("GOOGLE_SHEETS_ID", DEFAULT_SHEET_ID).strip()
        self.worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET", "").strip()
        self.credentials_file = os.getenv(
            "GOOGLE_SHEETS_CREDENTIALS_FILE",
            DEFAULT_CREDENTIALS_FILE,
        ).strip()

    def _credentials_path(self) -> Path:
        path = Path(self.credentials_file).expanduser()
        if path.is_absolute():
            return path
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / path
        return Path.cwd() / path

    def _worksheet(self):
        if not self.sheet_id:
            raise GoogleSheetsError("GOOGLE_SHEETS_ID не настроен")

        path = self._credentials_path()
        if not path.exists():
            raise GoogleSheetsError(
                f"Файл Google credentials не найден: {path}"
            )

        try:
            credentials = Credentials.from_service_account_file(
                str(path),
                scopes=SCOPES,
            )
            client = gspread.authorize(credentials)
            spreadsheet = client.open_by_key(self.sheet_id)
            return (
                spreadsheet.worksheet(self.worksheet_name)
                if self.worksheet_name
                else spreadsheet.sheet1
            )
        except Exception as exc:
            raise GoogleSheetsError(
                f"Не удалось открыть Google Sheets: {exc}"
            ) from exc

    def add_player(
        self,
        nickname: str,
        level: str,
        player_class: str,
        accepted_by: str,
        ts: str,
        telegram: str,
    ):
        nickname = nickname.strip()
        if not nickname:
            raise GoogleSheetsError("Игровой ник не указан")

        ws = self._worksheet()

        existing = {
            str(value).strip().casefold()
            for value in ws.col_values(1)[1:]
            if str(value).strip()
        }
        if nickname.casefold() in existing:
            raise GoogleSheetsError(
                f"Игрок с ником «{nickname}» уже есть в таблице"
            )

        row = [
            nickname,
            "",
            level.strip(),
            player_class.strip(),
            "",
            "",
            accepted_by.strip(),
            ts.strip(),
            telegram.strip(),
        ]
        try:
            ws.append_row(
                row,
                value_input_option="USER_ENTERED",
                insert_data_option="INSERT_ROWS",
            )
        except Exception as exc:
            raise GoogleSheetsError(
                f"Ошибка записи в Google Sheets: {exc}"
            ) from exc
