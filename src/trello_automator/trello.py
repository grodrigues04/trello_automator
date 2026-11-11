from dataclasses import dataclass
from datetime import datetime, timezone

import requests

TRELLO_API_URL = "https://api.trello.com/1"
REQUEST_TIMEOUT_SECONDS = 30


class TrelloError(Exception):
    pass


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    description: str
    url: str

    @property
    def created_at(self) -> datetime:
        """Trello ids start with the creation timestamp, in hexadecimal seconds."""
        return datetime.fromtimestamp(int(self.id[:8], 16), tz=timezone.utc)


class TrelloClient:
    def __init__(self, api_key: str, token: str):
        self._session = requests.Session()
        self._session.params = {"key": api_key, "token": token}

    def _get(self, path: str, **params: str) -> list[dict]:
        response = self._session.get(
            f"{TRELLO_API_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def find_board_id(self, board_name: str) -> str:
        boards = self._get("/members/me/boards", fields="name", filter="open")
        for board in boards:
            if board["name"].strip().lower() == board_name.lower():
                return board["id"]
        raise TrelloError(f'board "{board_name}" não encontrado na conta do Trello')

    def find_list_id(self, board_id: str, list_name: str) -> str:
        board_lists = self._get(f"/boards/{board_id}/lists", fields="name", filter="open")
        for board_list in board_lists:
            if board_list["name"].strip().lower() == list_name.lower():
                return board_list["id"]
        raise TrelloError(f'coluna "{list_name}" não encontrada no board')

    def list_cards(self, list_id: str) -> list[Card]:
        """Open cards of the list, in the order they appear on the board."""
        cards = self._get(f"/lists/{list_id}/cards", fields="name,desc,shortUrl")
        return [
            Card(
                id=card["id"],
                name=card["name"].strip(),
                description=card["desc"].strip(),
                url=card["shortUrl"],
            )
            for card in cards
        ]

    def close(self) -> None:
        self._session.close()
