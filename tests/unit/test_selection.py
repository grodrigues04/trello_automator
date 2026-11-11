from datetime import datetime, timezone

import pytest

from trello_automator import messages
from trello_automator.selection import (
    RatedCard,
    build_branch_slug,
    choose_automatically,
    filter_eligible,
    is_all_levels_session,
    is_confirmation,
    parse_card_number,
)
from trello_automator.trello import Card


def build_rated_card(created_at: datetime, complexity: int, name: str = "Card") -> RatedCard:
    card_id = f"{int(created_at.timestamp()):08x}" + "0" * 16
    return RatedCard(
        card=Card(id=card_id, name=name, description="task", url="https://trello.com/c/x"),
        complexity=complexity,
    )


OLD_SIMPLE = build_rated_card(datetime(2026, 1, 1, tzinfo=timezone.utc), 3, "Antigo simples")
NEW_MEDIUM = build_rated_card(datetime(2026, 3, 1, tzinfo=timezone.utc), 7, "Novo médio")
NEWEST_HARD = build_rated_card(datetime(2026, 5, 1, tzinfo=timezone.utc), 9, "Mais novo difícil")
OLD_HARDEST = build_rated_card(datetime(2026, 2, 1, tzinfo=timezone.utc), 10, "Antigo dificílimo")
ZERO = build_rated_card(datetime(2026, 4, 1, tzinfo=timezone.utc), 0, "Zero")


def test_card_created_at_comes_from_the_id():
    assert OLD_SIMPLE.card.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 11, 12, 22, 30), True),  # Thursday
        (datetime(2026, 11, 9, 12, 0), False),  # Monday
        (datetime(2026, 11, 13, 22, 0), False),  # Friday
    ],
)
def test_only_thursday_accepts_all_levels(now, expected):
    assert is_all_levels_session(now) is expected


def test_regular_session_keeps_complexity_zero_to_seven():
    cards = [OLD_SIMPLE, NEW_MEDIUM, NEWEST_HARD, OLD_HARDEST, ZERO]
    assert filter_eligible(cards, all_levels=False) == [OLD_SIMPLE, NEW_MEDIUM, ZERO]


def test_thursday_session_keeps_every_card():
    cards = [OLD_SIMPLE, NEWEST_HARD]
    assert filter_eligible(cards, all_levels=True) == cards


def test_regular_automatic_choice_is_the_most_recent():
    assert choose_automatically([OLD_SIMPLE, NEW_MEDIUM, ZERO], all_levels=False) == ZERO


def test_thursday_automatic_choice_is_the_most_complex():
    cards = [OLD_SIMPLE, NEWEST_HARD, OLD_HARDEST]
    assert choose_automatically(cards, all_levels=True) == OLD_HARDEST


def test_thursday_tie_goes_to_the_most_recent():
    newer_hardest = build_rated_card(datetime(2026, 6, 1, tzinfo=timezone.utc), 10)
    assert choose_automatically([OLD_HARDEST, newer_hardest], all_levels=True) == newer_hardest


@pytest.mark.parametrize(
    "reply_text, expected",
    [("2", 2), (" 3 \n", 3), ("1", 1), ("0", None), ("4", None), ("o 2", None), ("2.", None),
     ("", None), (None, None)],
)
def test_parse_card_number(reply_text, expected):
    assert parse_card_number(reply_text, card_count=3) == expected


@pytest.mark.parametrize(
    "reply_text, expected",
    [("sim", True), ("Sim!", True), ("s", True), ("não", False), ("simm", False), (None, False)],
)
def test_is_confirmation(reply_text, expected):
    assert is_confirmation(reply_text) is expected


def test_branch_slug_removes_accents_and_symbols():
    assert build_branch_slug("Ajustar botão de Notificação!! (perfil)") == (
        "ajustar-botao-de-notificacao-perfil"
    )


def test_branch_slug_is_limited():
    assert len(build_branch_slug("palavra " * 30)) <= 50


def test_branch_slug_never_empty():
    assert build_branch_slug("!!!") == "task"


def test_card_list_is_numbered_with_blank_lines():
    assert messages.format_card_list([OLD_SIMPLE, NEW_MEDIUM]) == (
        "1. Antigo simples *COMPLEXIDADE: 3*\n\n2. Novo médio *COMPLEXIDADE: 7*"
    )


def test_squeaker_message_starts_with_the_warning():
    text = messages.build_squeaker_choice([OLD_SIMPLE])
    assert text.startswith(
        "(claude_automatico) O Gustavo não viu a mensagem, decidam a task que vai ser "
        "implementada. Envie apenas o número. A primeira resposta é a que conta. "
        "Tempo limite de 10 minutos esperando mensagem"
    )
    assert text.endswith("1. Antigo simples *COMPLEXIDADE: 3*")
