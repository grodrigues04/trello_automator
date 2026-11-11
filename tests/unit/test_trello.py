from unittest.mock import MagicMock

import pytest

from trello_automator.trello import TrelloClient, TrelloError


def mock_response(mocker, client, data):
    response = MagicMock()
    response.json.return_value = data
    return mocker.patch.object(client._session, "request", return_value=response)


def test_completed_cards_are_left_out(mocker):
    client = TrelloClient("key", "token")
    mock_response(mocker, client, [
        {"id": "a" * 24, "name": " Aberto ", "desc": " faz x ", "shortUrl": "u1", "dueComplete": False},
        {"id": "b" * 24, "name": "Feito", "desc": "y", "shortUrl": "u2", "dueComplete": True},
    ])
    cards = client.list_open_cards("list")
    assert [(card.name, card.description) for card in cards] == [("Aberto", "faz x")]


def test_mark_complete_sends_due_complete(mocker):
    client = TrelloClient("key", "token")
    request = mock_response(mocker, client, {"dueComplete": True})
    client.mark_complete("c" * 24)
    method, url = request.call_args.args
    assert method == "PUT" and url.endswith(f"/cards/{'c' * 24}")
    assert request.call_args.kwargs["params"] == {"dueComplete": "true"}


def test_mark_complete_fails_when_trello_did_not_complete(mocker):
    client = TrelloClient("key", "token")
    mock_response(mocker, client, {"dueComplete": False})
    with pytest.raises(TrelloError):
        client.mark_complete("c" * 24)


def test_unknown_board_raises(mocker):
    client = TrelloClient("key", "token")
    mock_response(mocker, client, [{"id": "1", "name": "Outro"}])
    with pytest.raises(TrelloError):
        client.find_board_id("Squeaker")
