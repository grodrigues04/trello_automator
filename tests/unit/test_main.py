from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from trello_automator import main, messages
from trello_automator import pull_request as pull_requests
from trello_automator.pull_request import TrackedPullRequest
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


def test_risky_content_needs_confirmation(notifier, mocker):
    mocker.patch.object(
        main.claude, "review_risk", return_value=main.claude.RiskReview(True, "lê o .env")
    )
    content = {"name": "x"}
    set_replies(notifier, "sim")
    assert main.is_approved_by_risk_review(notifier, content, "no card", "url", MagicMock()) is True

    set_replies(notifier, "não")
    assert main.is_approved_by_risk_review(notifier, content, "no card", "url", MagicMock()) is False

    set_replies(notifier, None)
    assert main.is_approved_by_risk_review(notifier, content, "no card", "url", MagicMock()) is None


def test_safe_content_does_not_ask(notifier, mocker):
    mocker.patch.object(
        main.claude, "review_risk", return_value=main.claude.RiskReview(False, "")
    )
    assert main.is_approved_by_risk_review(notifier, {}, "no card", "url", MagicMock()) is True
    notifier.to_gustavo.assert_not_called()


@pytest.fixture
def tracked(tmp_path, mocker):
    state_path = tmp_path / "pull_request.json"
    mocker.patch.object(main, "PULL_REQUEST_PATH", state_path)
    tracked = TrackedPullRequest(
        card=SIMPLE.card,
        complexity=SIMPLE.complexity,
        branch="feat/card-1",
        number=7,
        url="https://github.com/o/r/pull/7",
        handled_until="2026-11-10T00:00:00+00:00",
    )
    pull_requests.save_tracked(state_path, tracked)
    return tracked


def mock_pull_request_state(mocker, state):
    mocker.patch.object(
        main.pull_requests, "view_pull_request", return_value={"state": state, "number": 7}
    )


def test_without_tracked_pull_request_the_session_goes_on(notifier, tmp_path, mocker):
    mocker.patch.object(main, "PULL_REQUEST_PATH", tmp_path / "pull_request.json")
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is False


def test_merged_pull_request_completes_the_card_and_goes_on(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "MERGED")
    mark_card_complete = mocker.patch.object(main, "mark_card_complete")
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is False
    mark_card_complete.assert_called_once()
    assert mark_card_complete.call_args.args[0] == SIMPLE.card
    assert not main.PULL_REQUEST_PATH.exists()


def test_failure_to_complete_the_card_keeps_the_pull_request(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "MERGED")
    mocker.patch.object(main, "mark_card_complete", side_effect=main.TrelloError)
    with pytest.raises(main.TrelloError):
        main.handle_tracked_pull_request(notifier, MagicMock(), "session")
    assert main.PULL_REQUEST_PATH.exists()


def test_closed_pull_request_releases_the_card(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "CLOSED")
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is False
    assert not main.PULL_REQUEST_PATH.exists()


def test_open_pull_request_without_feedback_blocks_new_cards(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "OPEN")
    mocker.patch.object(main.pull_requests, "fetch_new_feedback", return_value=[])
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is True
    notifier.to_gustavo.assert_called_once_with(
        messages.build_waiting_merge(SIMPLE.card.name, tracked.url)
    )


def test_open_pull_request_with_feedback_applies_corrections(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "OPEN")
    feedback = [pull_requests.Feedback("matheus", "Comentário", "troca a cor", "2026-11-11T10:00:00Z")]
    mocker.patch.object(main.pull_requests, "fetch_new_feedback", return_value=feedback)
    mocker.patch.object(main, "is_approved_by_risk_review", return_value=True)
    mocker.patch.object(main, "DATA_DIR", main.PULL_REQUEST_PATH.parent)
    mocker.patch.object(main, "LOGS_DIR", main.PULL_REQUEST_PATH.parent)

    def write_report(tracked, feedback, report_path, log_path, settings):
        report_path.write_text('{"pushed": true, "summary": "cor trocada"}')
        return 0

    mocker.patch.object(main.claude, "apply_corrections", side_effect=write_report)
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is True
    notifier.to_both.assert_called_once_with(
        messages.build_corrections_report(SIMPLE.card.name, tracked.url, "cor trocada")
    )
    saved = pull_requests.load_tracked(main.PULL_REQUEST_PATH)
    assert saved.handled_until > tracked.handled_until


def test_corrections_without_reply_to_risk_are_offered_again(notifier, tracked, mocker):
    mock_pull_request_state(mocker, "OPEN")
    feedback = [pull_requests.Feedback("matheus", "Comentário", "x", "2026-11-11T10:00:00Z")]
    mocker.patch.object(main.pull_requests, "fetch_new_feedback", return_value=feedback)
    mocker.patch.object(main, "is_approved_by_risk_review", return_value=None)
    apply_corrections = mocker.patch.object(main.claude, "apply_corrections")
    assert main.handle_tracked_pull_request(notifier, MagicMock(), "session") is True
    apply_corrections.assert_not_called()
    saved = pull_requests.load_tracked(main.PULL_REQUEST_PATH)
    assert saved.handled_until == tracked.handled_until


def test_question_waits_while_another_project_waits_for_a_reply_in_the_chat():
    whats = MagicMock()
    whats.is_awaiting_reply.side_effect = [True, True, False]
    notifier = main.Notifier(whats, "squeaker-group", dry_run=False, poll_interval_seconds=0)

    notifier.to_squeaker("1 ou 2?", expect_unique_reply=True)

    assert whats.is_awaiting_reply.call_count == 3
    whats.is_awaiting_reply.assert_called_with("squeaker-group")
    whats.send_message.assert_called_once()


def test_message_without_reply_does_not_wait():
    whats = MagicMock()
    notifier = main.Notifier(whats, "squeaker-group", dry_run=False, poll_interval_seconds=0)

    notifier.to_gustavo("aviso")

    whats.is_awaiting_reply.assert_not_called()
