from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from trello_automator import main, messages
from trello_automator.selection import RatedCard
from trello_automator.trello import Card


def build_rated_card(month: int, complexity: int) -> RatedCard:
    created_at = datetime(2026, month, 1, tzinfo=timezone.utc)
    card_id = f"{int(created_at.timestamp()):08x}" + "0" * 16
    return RatedCard(
        card=Card(id=card_id, name=f"Card {month}", description="task", url="url"),
        complexity=complexity,
    )


SIMPLE = build_rated_card(1, 2)
HARD = build_rated_card(2, 9)
MEDIUM = build_rated_card(3, 5)
CARDS = [SIMPLE, HARD, MEDIUM]


@pytest.fixture
def notifier():
    notifier = MagicMock(spec=main.Notifier)
    notifier.to_gustavo.return_value = "gustavo-message"
    notifier.to_squeaker.return_value = "squeaker-message"
    return notifier


def set_replies(notifier, gustavo_reply, squeaker_reply=None):
    replies = {"gustavo-message": gustavo_reply, "squeaker-message": squeaker_reply}
    notifier.wait_for_reply_text.side_effect = lambda message_id: replies[message_id]


def test_gustavo_can_choose_any_complexity(notifier):
    set_replies(notifier, "2")
    assert main.choose_card(notifier, CARDS, all_levels=False) == HARD
    notifier.to_squeaker.assert_not_called()


def test_invalid_reply_is_answered_and_goes_to_squeaker(notifier):
    set_replies(notifier, "o segundo", "1")
    chosen_card = main.choose_card(notifier, CARDS, all_levels=False)
    notifier.to_gustavo.assert_any_call(messages.INVALID_REPLY)
    # Squeaker only sees cards up to 7, numbered again
    squeaker_text = notifier.to_squeaker.call_args_list[0].args[0]
    assert "COMPLEXIDADE: 9" not in squeaker_text
    assert chosen_card == SIMPLE


def test_without_replies_the_most_recent_eligible_card_is_chosen(notifier):
    set_replies(notifier, None, None)
    assert main.choose_card(notifier, CARDS, all_levels=False) == MEDIUM
    notifier.to_both.assert_called_with(messages.build_automatic_choice(MEDIUM))


def test_without_replies_on_thursday_the_most_complex_card_is_chosen(notifier):
    set_replies(notifier, None, None)
    assert main.choose_card(notifier, CARDS, all_levels=True) == HARD


def test_out_of_range_cards_are_not_implemented(notifier):
    set_replies(notifier, None)
    assert main.choose_card(notifier, [HARD], all_levels=False) is None
    notifier.to_squeaker.assert_not_called()
    notifier.to_both.assert_called_with(messages.build_out_of_range())


def test_risky_card_needs_confirmation(notifier, mocker):
    mocker.patch.object(
        main.claude, "review_risk", return_value=main.claude.RiskReview(True, "lê o .env")
    )
    set_replies(notifier, "sim")
    assert main.is_approved_by_risk_review(notifier, SIMPLE, MagicMock()) is True

    set_replies(notifier, None)
    assert main.is_approved_by_risk_review(notifier, SIMPLE, MagicMock()) is False
    notifier.to_both.assert_called_with(messages.build_risk_cancelled(SIMPLE))


def test_safe_card_does_not_ask(notifier, mocker):
    mocker.patch.object(
        main.claude, "review_risk", return_value=main.claude.RiskReview(False, "")
    )
    assert main.is_approved_by_risk_review(notifier, SIMPLE, MagicMock()) is True
    notifier.to_gustavo.assert_not_called()
