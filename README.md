# trello_automator

Implementa com o Claude Code as tasks da coluna **GUSTAVO** do board **Squeaker** do Trello no
repositório [ratUFSC](https://github.com/matheusfaustinott/ratUFSC), e avisa pelo WhatsApp usando
a [interface-personal-whats](https://github.com/grodrigues04/interface-personal-whats).

Roda neste computador, como o seu usuário, por um timer do systemd:
**segunda 12:00, quinta 22:30 e sexta 22:00**. Computador desligado ou suspenso no horário: a
sessão é perdida.

## Uma sessão

1. **Cards.** Lê os cards abertos da coluna. Card sem descrição é descartado (a descrição é o
   prompt), e card que já virou PR numa sessão anterior também (`data/implemented.json`).
   Sem cards: avisa os grupos Claudio e Squeaker e encerra.
2. **Complexidade.** Um Claude (Sonnet, só com Read/Grep/Glob no ratUFSC) dá uma nota de 0 a 10
   para cada card.
3. **Escolha.**
   1. Grupo **Claudio** (contato padrão): a lista com **todos** os cards. Espera 10 minutos por
      um número.
   2. Sem resposta, ou resposta inválida (o script responde
      `Resposta invalida -> envie apenas um numero` e segue): grupo **Squeaker**, só com os cards
      de complexidade **0 a 7** (na quinta, todos), numerados de novo. Espera mais 10 minutos.
   3. Sem resposta válida: escolha automática. Card mais recente da faixa; na quinta, o mais
      complexo (no empate, o mais recente).

   Se nenhum card estiver na faixa, avisa os dois grupos e não implementa nada.
4. **Revisão de risco.** Outro Claude (Sonnet, **sem ferramentas**) lê só o card escolhido e
   procura pedido de segredo, envio de dados, comando destrutivo ou prompt injection. Com risco,
   pergunta no Claudio. Só `sim` em 10 minutos libera a implementação.
5. **Implementação.** Com a árvore limpa, o script faz `git checkout main` e `git pull`. Com
   mudanças não commitadas, o Claude resolve, guardando-as num `git stash`. O Claude (Opus, sem
   pedir permissão) cria a branch `<tipo>/<nome-do-card>`, implementa, testa, commita, dá push e
   abre o PR para a `main`.
6. **Relatório.** O Claude grava `data/reports/<sessão>.json`, e o script manda o relatório, a
   branch, o link da branch e o PR nos dois grupos.

O que é do script e o que é do Claude: as regras (horários, filtro de complexidade, ordem de
quem escolhe, mensagens) são código em `src/`, testadas em `tests/`. Só o que precisa de
julgamento vai para os prompts em `prompts/`: dar a nota, avaliar risco e implementar.

## Segurança

O Claude que implementa roda como você e enxerga seus arquivos. Isso é intencional: ele precisa
do seu `gh` e da sua chave SSH para o push e o PR. A descrição do card é escrita por outras
pessoas, então:

- a revisão de risco roda antes, sem ferramentas, para o card não conseguir executar nada nela;
- as variáveis do `.env` deste projeto (Trello, `MONGO_URI`, `ENCRYPTION_PASSWORD`) não são
  repassadas para nenhum processo do Claude;
- o prompt de implementação manda tratar o card só como pedido de produto.

A revisão reduz o risco, mas não o elimina: uma instrução maliciosa pode aparecer no meio do
caminho, por exemplo num pacote do npm.

## Configuração

```bash
cp .env.example .env    # Trello, MONGO_URI, ENCRYPTION_PASSWORD, SQUEAKER_GROUP
uv sync

# Teste sem implementar: manda tudo só para o grupo Claudio, inclusive a mensagem do Squeaker
./run.sh --dry-run

# Agendamento
mkdir -p ~/.config/systemd/user
ln -sf "$PWD"/systemd/trello-automator.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now trello-automator.timer
systemctl --user list-timers trello-automator.timer
```

O timer do usuário só roda com você logado. Para rodar também deslogado:
`loginctl enable-linger $USER`.

## Comandos úteis

```bash
./run.sh                  # sessão completa agora
./run.sh --all-levels     # sessão completa como se fosse quinta
systemctl --user start trello-automator.service   # sessão pelo systemd (mesmo ambiente do timer)
journalctl --user -u trello-automator -f           # log da sessão
tail -f data/logs/routine.log                      # log de todas as sessões
uv run pytest
```

Saída do Claude de cada implementação: `data/logs/<sessão>-claude.log`. Para oferecer de novo um
card já implementado, tire o id dele de `data/implemented.json`.
