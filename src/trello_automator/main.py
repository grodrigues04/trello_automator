"""Session routine.

1. The PR opened by the routine comes first: merged -> card marked as complete in Trello;
   open with new review feedback -> the session only applies the corrections; open without
   feedback -> no new card until it is merged.
2. Otherwise: rate the cards, ask which one to implement, implement it and report.

Runs on Mondays 12:00, Thursdays 22:30 and Fridays 22:00 (systemd timer). Only one session runs
at a time (lock in data/).
"""

import argparse
import fcntl
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from interface_personal_whats import InterfacePersonalWhats, MessageNotSentError

from trello_automator import claude, messages
from trello_automator import pull_request as pull_requests
from trello_automator.config import DATA_DIR, SOURCE, Settings, load_settings
from trello_automator.pull_request import PullRequestState, TrackedPullRequest
from trello_automator.selection import (
    RatedCard,
    build_branch_slug,
    choose_automatically,
    filter_eligible,
    is_all_levels_session,
    is_confirmation,
    parse_card_number,
)

log = logging.getLogger("trello_automator")

LOCK_PATH = DATA_DIR / "session.lock"
PULL_REQUEST_PATH = DATA_DIR / "pull_request.json"
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


def rate_cards(settings: Settings) -> list[RatedCard]:
    # Cards without description have no task to implement
    cards = [card for card in claude.read_cards(settings) if card.description]
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
    notifier: Notifier, content: dict, subject: str, url: str, settings: Settings
) -> Optional[bool]:
    """True to go on, False when Gustavo said no, None when he did not reply."""
    review = claude.review_risk(content, settings)
    if not review.risky:
        log.info("Risk review: no risk")
        return True
    log.warning(f"Risk review: {review.reason}")
    message_id = notifier.to_gustavo(
        messages.build_risk_question(subject, url, review.reason), expect_unique_reply=True
    )
    reply_text = notifier.wait_for_reply_text(message_id)
    if reply_text is None:
        return None
    if is_confirmation(reply_text):
        log.info("Gustavo approved the risky content")
        return True
    return False


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_report(report_path: Path) -> Optional[dict]:
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def describe_missing_report(exit_code: int, settings: Settings) -> str:
    if exit_code == 124:
        return f"o Claude passou de {settings.implementation_timeout_minutes} minutos"
    return f"o Claude terminou (código {exit_code}) sem escrever o relatório"


def apply_corrections(
    notifier: Notifier,
    tracked: TrackedPullRequest,
    feedback: list[pull_requests.Feedback],
    settings: Settings,
    session_id: str,
) -> None:
    handled_until = now_utc()
    approval = is_approved_by_risk_review(
        notifier,
        {"pull_request": tracked.url, "comments": [item.format() for item in feedback]},
        f'nos comentários do PR do card "{tracked.card.name}"',
        tracked.url,
        settings,
    )
    if approval is not True:
        notifier.to_gustavo(messages.build_corrections_cancelled(tracked.card.name))
        if approval is False:
            # Refused by Gustavo: these comments are never offered again
            tracked.handled_until = handled_until
            pull_requests.save_tracked(PULL_REQUEST_PATH, tracked)
        return

    report_path = DATA_DIR / "reports" / f"{session_id}-correcoes.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{session_id}-claude.log"
    log.info(f"Applying {len(feedback)} review items to {tracked.url}, output in {log_path}")
    exit_code = claude.apply_corrections(tracked, feedback, report_path, log_path, settings)
    log.info(f"Claude finished with exit code {exit_code}")

    report = read_report(report_path)
    if report is None:
        # Nothing handled: the same feedback is applied again in the next session
        reason = describe_missing_report(exit_code, settings)
        notifier.to_gustavo(
            messages.build_corrections_failed(tracked.card.name, f"{reason}. Log: {log_path}")
        )
        notifier.to_squeaker(messages.build_corrections_failed(tracked.card.name, reason))
        return

    tracked.handled_until = handled_until
    pull_requests.save_tracked(PULL_REQUEST_PATH, tracked)
    summary = str(report.get("summary") or "").strip()
    if report.get("pushed"):
        notifier.to_both(messages.build_corrections_report(tracked.card.name, tracked.url, summary))
    else:
        notifier.to_both(
            messages.build_corrections_failed(tracked.card.name, summary or "sem motivo")
        )


def handle_tracked_pull_request(
    notifier: Notifier, settings: Settings, session_id: str
) -> bool:
    """Handles the routine's PR. True when the session ends here (no new card)."""
    tracked = pull_requests.load_tracked(PULL_REQUEST_PATH)
    if tracked is None:
        return False
    pull_request = pull_requests.view_pull_request(settings.github_repo, str(tracked.number))
    if pull_request is None:
        raise RuntimeError(f"PR {tracked.url} não encontrado no GitHub")
    state = PullRequestState(pull_request["state"])
    log.info(f"Tracked PR {tracked.url} is {state.value}")

    if state == PullRequestState.MERGED:
        claude.mark_card_complete(tracked.card, settings)
        PULL_REQUEST_PATH.unlink()
        notifier.to_both(messages.build_merged(tracked.card.name, tracked.url))
        return False
    if state == PullRequestState.CLOSED:
        PULL_REQUEST_PATH.unlink()
        notifier.to_gustavo(messages.build_closed_without_merge(tracked.card.name, tracked.url))
        return False

    feedback = pull_requests.fetch_new_feedback(settings.github_repo, tracked)
    if not feedback:
        notifier.to_gustavo(messages.build_waiting_merge(tracked.card.name, tracked.url))
        return True
    apply_corrections(notifier, tracked, feedback, settings, session_id)
    return True


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

    report = read_report(report_path)
    if report is None:
        reason = describe_missing_report(exit_code, settings)
        notifier.to_gustavo(
            messages.build_implementation_failed(rated_card, f"{reason}. Log: {log_path}")
        )
        notifier.to_squeaker(messages.build_implementation_failed(rated_card, reason))
        return

    branch = str(report.get("branch") or "").strip()
    summary = str(report.get("summary") or "").strip()
    if not branch:
        notifier.to_both(messages.build_implementation_failed(rated_card, summary or "sem motivo"))
        return

    pull_request = pull_requests.view_pull_request(settings.github_repo, branch)
    pr_url = pull_request["url"] if pull_request else report.get("pr_url") or None
    if pull_request is not None:
        # From now on the sessions follow this PR until it is merged or closed
        pull_requests.save_tracked(
            PULL_REQUEST_PATH,
            TrackedPullRequest(
                card=rated_card.card,
                complexity=rated_card.complexity,
                branch=branch,
                number=pull_request["number"],
                url=pull_request["url"],
                handled_until=now_utc(),
            ),
        )
    else:
        log.warning(f"No PR found for branch {branch}: the card may be offered again")
    branch_url = f"https://github.com/{settings.github_repo}/tree/{branch}"
    notifier.to_both(messages.build_report(rated_card, branch, branch_url, pr_url, summary))
    log.info(f"Report sent: branch {branch}, PR {pr_url}")


def run_session(settings: Settings, notifier: Notifier, all_levels: bool, dry_run: bool) -> None:
    session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if dry_run:
        log.info("Dry run: the routine's PR is not checked")
    elif handle_tracked_pull_request(notifier, settings, session_id):
        return

    rated_cards = rate_cards(settings)
    if not rated_cards:
        notifier.to_both(messages.build_no_cards())
        return

    chosen_card = choose_card(notifier, rated_cards, all_levels)
    if chosen_card is None:
        return
    approval = is_approved_by_risk_review(
        notifier,
        {"name": chosen_card.card.name, "description": chosen_card.card.description},
        f'no card "{chosen_card.card.name}"',
        chosen_card.card.url,
        settings,
    )
    if approval is not True:
        notifier.to_both(messages.build_risk_cancelled(chosen_card))
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
