"""Texts sent to WhatsApp. Every message starts with the (claude_automatico) tag."""

from typing import Optional

from trello_automator.selection import RatedCard

TAG = "(claude_automatico)"
MAX_SUMMARY_LENGTH = 6000

INVALID_REPLY = "Resposta invalida -> envie apenas um numero"


def format_card_list(rated_cards: list[RatedCard]) -> str:
    return "\n\n".join(
        f"{number}. {rated_card.card.name} *COMPLEXIDADE: {rated_card.complexity}*"
        for number, rated_card in enumerate(rated_cards, start=1)
    )


def build_gustavo_choice(rated_cards: list[RatedCard], all_levels: bool) -> str:
    session_rule = (
        "Sessão de quinta: todos os níveis podem ser escolhidos."
        if all_levels
        else "Fora da quinta, o grupo Squeaker e a escolha automática só usam complexidade até 7."
    )
    return (
        f"{TAG} Cards da coluna GUSTAVO. Envie apenas o número do card a implementar.\n"
        f"{session_rule}\n\n{format_card_list(rated_cards)}"
    )


def build_squeaker_choice(rated_cards: list[RatedCard]) -> str:
    return (
        f"{TAG} O Gustavo não viu a mensagem, decidam a task que vai ser implementada. "
        "Envie apenas o número. A primeira resposta é a que conta. "
        "Tempo limite de 10 minutos esperando mensagem\n\n"
        f"{format_card_list(rated_cards)}"
    )


def build_no_cards() -> str:
    return f"{TAG} Não há cards com descrição na coluna GUSTAVO. Nada será implementado nesta sessão."


def build_out_of_range() -> str:
    return (
        f"{TAG} Não há cards, ou os que existem estão fora da escala escolhida pelo Gustavo para "
        "ser implementada nesta sessão. Nada será implementado."
    )


def build_automatic_choice(rated_card: RatedCard) -> str:
    return (
        f'{TAG} Ninguém escolheu a tempo. Fazendo o card "{rated_card.card.name}" '
        f"(complexidade {rated_card.complexity})."
    )


def build_chosen(rated_card: RatedCard) -> str:
    return (
        f'{TAG} Card escolhido: "{rated_card.card.name}" (complexidade {rated_card.complexity}). '
        "Começando a implementação."
    )


def build_risk_question(rated_card: RatedCard, reason: str) -> str:
    return (
        f'{TAG} A revisão de segurança achou risco no card "{rated_card.card.name}":\n'
        f"{reason}\n\n{rated_card.card.url}\n\n"
        "Implementar mesmo assim? Responda *sim* para implementar. "
        "Qualquer outra resposta, ou nenhuma em 10 minutos, cancela."
    )


def build_risk_cancelled(rated_card: RatedCard) -> str:
    return f'{TAG} O card "{rated_card.card.name}" não será implementado nesta sessão.'


def build_report(
    rated_card: RatedCard, branch: str, branch_url: str, pr_url: Optional[str], summary: str
) -> str:
    if len(summary) > MAX_SUMMARY_LENGTH:
        summary = summary[:MAX_SUMMARY_LENGTH].rstrip() + "…"
    return (
        f'{TAG} Card "{rated_card.card.name}" implementado.\n\n'
        f"*Branch:* {branch}\n{branch_url}\n\n"
        f"*PR:* {pr_url or 'não encontrado'}\n\n"
        f"*Relatório:*\n{summary}"
    )


def build_implementation_failed(rated_card: RatedCard, reason: str) -> str:
    return f'{TAG} A implementação do card "{rated_card.card.name}" falhou: {reason}'


def build_routine_failed(reason: str) -> str:
    return f"{TAG} A rotina do trello_automator falhou: {reason}"
