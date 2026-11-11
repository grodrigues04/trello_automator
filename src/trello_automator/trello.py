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

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]).strip(),
            description=str(data.get("description") or "").strip(),
            url=str(data.get("url") or ""),
        )


class TrelloClient:
    def __init__(self, api_key: str, token: str):
        self._session = requests.Session()
        self._session.params = {"key": api_key, "token": token}

    def _request(self, method: str, path: str, **params: str):
        response = self._session.request(
            method, f"{TRELLO_API_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def find_board_id(self, board_name: str) -> str:
        boards = self._request("GET", "/members/me/boards", fields="name", filter="open")
        for board in boards:
            if board["name"].strip().lower() == board_name.lower():
                return board["id"]
        raise TrelloError(f'board "{board_name}" não encontrado na conta do Trello')

    def find_list_id(self, board_id: str, list_name: str) -> str:
        board_lists = self._request("GET", f"/boards/{board_id}/lists", fields="name", filter="open")
        for board_list in board_lists:
            if board_list["name"].strip().lower() == list_name.lower():
                return board_list["id"]
        raise TrelloError(f'coluna "{list_name}" não encontrada no board')

    def list_open_cards(self, list_id: str) -> list[Card]:
        """Cards of the list not marked as complete, in the order they appear on the board."""
        cards = self._request("GET", f"/lists/{list_id}/cards", fields="name,desc,shortUrl,dueComplete")
        return [
            Card(
                id=card["id"],
                name=card["name"].strip(),
                description=card["desc"].strip(),
                url=card["shortUrl"],
            )
            for card in cards
            if not card.get("dueComplete")
        ]

    def mark_complete(self, card_id: str) -> None:
        """Turns on the card's complete check."""
        card = self._request("PUT", f"/cards/{card_id}", dueComplete="true")
        if not card.get("dueComplete"):
            raise TrelloError(f"o card {card_id} não ficou marcado como concluído")

    def close(self) -> None:
        self._session.close()
