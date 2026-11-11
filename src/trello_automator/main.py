"""Session routine: rate the cards, ask which one to implement, implement it and report.

Runs on Mondays 12:00, Thursdays 22:30 and Fridays 22:00 (systemd timer). Only one session runs
at a time (lock in data/).
"""

import argparse
import fcntl
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from interface_personal_whats import InterfacePersonalWhats, MessageNotSentError

from trello_automator import claude, messages
from trello_automator.config import DATA_DIR, SOURCE, Settings, load_settings
from trello_automator.selection import (
    RatedCard,
    build_branch_slug,
    choose_automatically,
    filter_eligible,
    is_all_levels_session,
    is_confirmation,
    parse_card_number,
)
from trello_automator.trello import TrelloClient

log = logging.getLogger("trello_automator")

LOCK_PATH = DATA_DIR / "session.lock"
IMPLEMENTED_PATH = DATA_DIR / "implemented.json"
LOGS_DIR = DATA_DIR / "logs"


class Notifier:
    """Sends to the default recipient (group Claudio) and to the Squeaker group."""

    def __init__(self, whats: InterfacePersonalWhats, squeaker_group: str, dry_run: bool):
        self._whats = whats
        # A dry run never writes to the Squeaker group
        self._squeaker_group = None if dry_run else squeaker_group

    def to_gustavo(self, text: str, expect_unique_reply: bool = False) -> str:
        return self._whats.send_message(
            SOURCE, text=text, expect_unique_reply=expect_unique_reply
        )

    def to_squeaker(self, text: str, expect_unique_reply: bool = False) -> str:
        return self._whats.send_message(
            SOURCE,
            text=text,
            recipient=self._squeaker_group,
            expect_unique_reply=expect_unique_reply,
        )

    def to_both(self, text: str) -> None:
        self.to_gustavo(text)
        if self._squeaker_group is not None:
            self.to_squeaker(text)

    def wait_for_reply_text(self, message_id: str) -> Optional[str]:
        try:
            reply = self._whats.wait_for_reply(message_id)
        except MessageNotSentError as error:
            log.error(f"Message {message_id} was not sent: {error}")
            return None
        return reply.text if reply is not None else None


def load_implemented_card_ids() -> set[str]:
    if not IMPLEMENTED_PATH.exists():
        return set()
    return set(json.loads(IMPLEMENTED_PATH.read_text(encoding="utf-8")))


def save_implemented_card_id(card_id: str) -> None:
    card_ids = load_implemented_card_ids() | {card_id}
    IMPLEMENTED_PATH.write_text(json.dumps(sorted(card_ids), indent=2), encoding="utf-8")


def rate_cards(settings: Settings) -> list[RatedCard]:
    trello = TrelloClient(settings.trello_api_key, settings.trello_token)
    try:
        board_id = trello.find_board_id(settings.trello_board_name)
        list_id = trello.find_list_id(board_id, settings.trello_list_name)
        cards = trello.list_cards(list_id)
    finally:
        trello.close()

    implemented_card_ids = load_implemented_card_ids()
    # Cards without description have no task to implement
    cards = [
        card for card in cards if card.description and card.id not in implemented_card_ids
    ]
    log.info(f"{len(cards)} cards with description to rate")
    if not cards:
        return []
    complexities = claude.evaluate_complexity(cards, settings)
    return [RatedCard(card=card, complexity=complexities[card.id]) for card in cards]


def ask_for_card(
    notifier: Notifier, rated_cards: list[RatedCard], text: str, to_squeaker: bool
) -> Optional[RatedCard]:
    """Sends the numbered list and returns the chosen card, None without a valid reply."""
    send = notifier.to_squeaker if to_squeaker else notifier.to_gustavo
    message_id = send(text, expect_unique_reply=True)
    reply_text = notifier.wait_for_reply_text(message_id)
    if reply_text is None:
        log.info("No reply")
        return None
    card_number = parse_card_number(reply_text, len(rated_cards))
    if card_number is None:
        log.info(f"Invalid reply: {reply_text!r}")
        send(messages.INVALID_REPLY)
        return None
    return rated_cards[card_number - 1]


def choose_card(
    notifier: Notifier, rated_cards: list[RatedCard], all_levels: bool
) -> Optional[RatedCard]:
    """Gustavo first (every card), then the Squeaker group, then the automatic rule."""
    chosen_card = ask_for_card(
        notifier,
        rated_cards,
        messages.build_gustavo_choice(rated_cards, all_levels),
        to_squeaker=False,
    )
    if chosen_card is not None:
        log.info(f"Gustavo chose {chosen_card.card.name!r}")
        notifier.to_both(messages.build_chosen(chosen_card))
        return chosen_card

    eligible_cards = filter_eligible(rated_cards, all_levels)
    if not eligible_cards:
        log.info("No card within the complexity range of this session")
        notifier.to_both(messages.build_out_of_range())
        return None

    chosen_card = ask_for_card(
        notifier,
        eligible_cards,
        messages.build_squeaker_choice(eligible_cards),
        to_squeaker=True,
    )
    if chosen_card is not None:
        log.info(f"Squeaker group chose {chosen_card.card.name!r}")
        notifier.to_both(messages.build_chosen(chosen_card))
        return chosen_card

    chosen_card = choose_automatically(eligible_cards, all_levels)
    log.info(f"Automatic choice: {chosen_card.card.name!r}")
    notifier.to_both(messages.build_automatic_choice(chosen_card))
    return chosen_card


def is_approved_by_risk_review(
    notifier: Notifier, rated_card: RatedCard, settings: Settings
) -> bool:
    review = claude.review_risk(rated_card.card, settings)
    if not review.risky:
        log.info("Risk review: no risk")
        return True
    log.warning(f"Risk review: {review.reason}")
    message_id = notifier.to_gustavo(
        messages.build_risk_question(rated_card, review.reason), expect_unique_reply=True
    )
    if is_confirmation(notifier.wait_for_reply_text(message_id)):
        log.info("Gustavo approved the risky card")
        return True
    notifier.to_both(messages.build_risk_cancelled(rated_card))
    return False


def run_git(repo_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments], cwd=repo_path, capture_output=True, text=True, timeout=300
    )


def prepare_repository(repo_path: Path) -> str:
    """Checkout of main and pull when the tree is clean; otherwise the state goes to Claude."""
    status = run_git(repo_path, "status", "--porcelain")
    if status.returncode != 0:
        return f"`git status` falhou: {status.stderr.strip()}. Resolva antes de continuar."
    if status.stdout.strip():
        current_branch = run_git(repo_path, "branch", "--show-current").stdout.strip()
        return (
            f"Há mudanças não commitadas na branch `{current_branch}` (veja `git status`). "
            "Resolva antes de continuar."
        )
    for arguments in (("checkout", "main"), ("pull", "--ff-only")):
        completed = run_git(repo_path, *arguments)
        if completed.returncode != 0:
            return (
                f"`git {' '.join(arguments)}` falhou: {completed.stderr.strip()}. "
                "Resolva antes de continuar."
            )
    return "O script já fez `git checkout main` e `git pull`: a `main` está limpa e atualizada."


def find_pr_url(settings: Settings, branch: str) -> Optional[str]:
    completed = subprocess.run(
        ["gh", "pr", "view", branch, "--repo", settings.github_repo, "--json", "url", "-q", ".url"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def implement_card(
    notifier: Notifier, rated_card: RatedCard, settings: Settings, session_id: str
) -> None:
    report_path = DATA_DIR / "reports" / f"{session_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{session_id}-claude.log"

    repository_state = prepare_repository(settings.repo_path)
    log.info(f"Repository: {repository_state}")
    log.info(f"Implementing {rated_card.card.name!r}, Claude output in {log_path}")
    exit_code = claude.implement(
        rated_card.card,
        build_branch_slug(rated_card.card.name),
        repository_state,
        report_path,
        log_path,
        settings,
    )
    log.info(f"Claude finished with exit code {exit_code}")

    if not report_path.exists():
        reason = (
            f"o Claude passou de {settings.implementation_timeout_minutes} minutos"
            if exit_code == 124
            else f"o Claude terminou (código {exit_code}) sem escrever o relatório"
        )
        notifier.to_gustavo(
            messages.build_implementation_failed(rated_card, f"{reason}. Log: {log_path}")
        )
        notifier.to_squeaker(messages.build_implementation_failed(rated_card, reason))
        return

    report = json.loads(report_path.read_text(encoding="utf-8"))
    branch = str(report.get("branch") or "").strip()
    summary = str(report.get("summary") or "").strip()
    if not branch:
        notifier.to_both(messages.build_implementation_failed(rated_card, summary or "sem motivo"))
        return

    pr_url = find_pr_url(settings, branch) or report.get("pr_url") or None
    branch_url = f"https://github.com/{settings.github_repo}/tree/{branch}"
    save_implemented_card_id(rated_card.card.id)
    notifier.to_both(messages.build_report(rated_card, branch, branch_url, pr_url, summary))
    log.info(f"Report sent: branch {branch}, PR {pr_url}")


def run_session(settings: Settings, notifier: Notifier, all_levels: bool, dry_run: bool) -> None:
    session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    rated_cards = rate_cards(settings)
    if not rated_cards:
        notifier.to_both(messages.build_no_cards())
        return

    chosen_card = choose_card(notifier, rated_cards, all_levels)
    if chosen_card is None:
        return
    if not is_approved_by_risk_review(notifier, chosen_card, settings):
        return
    if dry_run:
        log.info("Dry run: implementation skipped")
        return
    implement_card(notifier, chosen_card, settings, session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="tudo menos a implementação, e nenhuma mensagem para o grupo Squeaker",
    )
    parser.add_argument(
        "--all-levels", action="store_true", help="aceita todos os níveis, como na quinta"
    )
    arguments = parser.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[trello_automator %(asctime)s] %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOGS_DIR / "routine.log", encoding="utf-8"),
        ],
    )

    lock_file = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Another session is still running, skipping")
        sys.exit(0)

    settings = load_settings()
    whats = InterfacePersonalWhats(
        mongo_uri=settings.mongo_uri, encryption_password=settings.encryption_password
    )
    notifier = Notifier(whats, settings.squeaker_group, arguments.dry_run)
    all_levels = arguments.all_levels or is_all_levels_session(datetime.now())
    log.info(f"Session started (all levels: {all_levels}, dry run: {arguments.dry_run})")
    try:
        run_session(settings, notifier, all_levels, arguments.dry_run)
    except Exception as error:
        log.exception("Session failed")
        notifier.to_gustavo(messages.build_routine_failed(f"{type(error).__name__}: {error}"))
        sys.exit(1)
    finally:
        whats.close()


if __name__ == "__main__":
    main()
