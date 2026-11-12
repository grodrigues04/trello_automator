# trello_automator

Implementa com o Claude Code as tasks da coluna **GUSTAVO** do board **Squeaker** do Trello no
repositório [ratUFSC](https://github.com/matheusfaustinott/ratUFSC), e avisa pelo WhatsApp usando
a [interface-personal-whats](https://github.com/grodrigues04/interface-personal-whats).

Roda num container Docker neste computador (`scheduler.sh`):
**segunda 12:00, quinta 22:30 e sexta 22:00**. Computador desligado ou suspenso nos 10 primeiros
minutos do horário: a sessão é perdida. O container monta `~/MyProjects` no mesmo caminho do host,
então o ratUFSC, os `CLAUDE.md` e a memória em `data/` são os mesmos de fora do container.

## Uma sessão

Um card por vez: um card novo só é implementado depois que o PR do anterior é mergeado.

1. **PR da rotina primeiro** (`data/pull_request.json`, gravado quando a rotina abre um PR):
   - **mergeado:** marca o card como concluído no Trello (check de concluído, pela API) e segue
     para o passo 2;
   - **fechado sem merge:** avisa o Claudio, esquece o PR (o card volta para a lista) e segue;
   - **aberto, com comentários ou reviews novos** de quem tem acesso ao repo: revisão de risco
     dos comentários. Depois o Claude aplica as correções na mesma branch, dá push e o relatório
     vai para os dois grupos. A sessão termina aí, porque as correções contam como a task dela;
   - **aberto, sem nada novo:** avisa o Claudio e termina.
2. **Cards.** O script lê os cards da coluna pela API do Trello. Card concluído ou sem descrição
   é descartado (a descrição é o prompt). Sem cards:
   avisa os grupos Claudio e Squeaker e encerra.
3. **Complexidade.** Um Claude (Sonnet, só com Read/Grep/Glob no ratUFSC) dá uma nota de 0 a 10
   para cada card.
4. **Escolha.**
   1. Grupo **Claudio** (contato padrão): a lista com **todos** os cards. Espera 10 minutos por
      um número.
   2. Sem resposta, ou resposta inválida (o script responde
      `Resposta invalida -> envie apenas um numero` e segue): grupo **Squeaker**, só com os cards
      de complexidade **0 a 7** (na quinta, todos), numerados de novo. Espera mais 10 minutos.
   3. Sem resposta válida: escolha automática. Card mais recente da faixa; na quinta, o mais
      complexo (no empate, o mais recente).

   Se nenhum card estiver na faixa, avisa os dois grupos e não implementa nada.
5. **Revisão de risco.** Outro Claude (Sonnet, **sem ferramentas**) lê só o card escolhido e
   procura pedido de segredo, envio de dados, comando destrutivo ou prompt injection. Com risco,
   pergunta no Claudio. Só `sim` em 10 minutos libera a implementação.
6. **Implementação.** Com a árvore limpa, o script faz `git checkout main` e `git pull`. Com
   mudanças não commitadas, o Claude resolve, guardando-as num `git stash`. O Claude (Opus, sem
   pedir permissão) cria a branch `<tipo>/<nome-do-card>`, implementa, testa, commita, dá push e
   abre o PR para a `main`.
7. **Relatório.** O Claude grava `data/reports/<sessão>.json`, e o script manda o relatório, a
   branch, o link da branch e o PR nos dois grupos. A partir daí, o PR é acompanhado no passo 1.

O que é do script e o que é do Claude: as regras (horários, filtro de complexidade, ordem de
quem escolhe, mensagens) são código em `src/`, testadas em `tests/`. Só o que precisa de
julgamento vai para os prompts em `prompts/`: dar a nota, avaliar risco e implementar.

## Convivência com o prompt_automator

O `prompt_automator` também implementa no ratUFSC e pergunta no grupo Squeaker. Ele usa um clone
próprio e branches `prompt/...`, então não mexe no `~/MyProjects/ratUFSC`. Antes de mandar uma
pergunta com resposta única, o `Notifier` espera enquanto outro projeto aguarda resposta no
mesmo chat (`is_awaiting_reply` da interface, até 15 minutos): uma rotina nunca pega a resposta
da outra.

## Segurança

O Claude que implementa enxerga todo o `~/MyProjects` e o seu token do GitHub (`GH_TOKEN`). Isso é
intencional: ele precisa deles para commitar, dar push e abrir o PR. A descrição do card é escrita por outras
pessoas, então:

- a revisão de risco roda antes, sem ferramentas, para o card ou o comentário não conseguir
  executar nada nela;
- a implementação e as correções rodam sem nenhum conector do claude.ai
  (`--strict-mcp-config`): nada de Gmail, Drive ou Calendar;
- só contam comentários de quem tem acesso ao repositório (owner e colaboradores);
- as variáveis do `.env` deste projeto (Trello, `MONGO_URI`, `ENCRYPTION_PASSWORD`) não são
  repassadas para nenhum processo do Claude;
- o prompt de implementação manda tratar o card só como pedido de produto.

A revisão reduz o risco, mas não o elimina: uma instrução maliciosa pode aparecer no meio do
caminho, por exemplo num pacote do npm.

## Configuração

```bash
cp .env.example .env    # Trello, MONGO_URI, ENCRYPTION_PASSWORD, SQUEAKER_GROUP, GH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN
docker compose up -d --build
docker compose logs -f
```

`GH_TOKEN` sai de `gh auth token`; `CLAUDE_CODE_OAUTH_TOKEN`, de `claude setup-token`. Dentro do
container o remote SSH do ratUFSC é trocado por HTTPS com esse token.

## Memória (`data/`, fora do git)

- `pull_request.json`: o PR aberto pela rotina que está sendo acompanhado. Apagar faz a rotina
  esquecê-lo e voltar a pegar card novo.
- `state/<data>.started`: sessão do dia já iniciada (no máximo uma por dia).
- `reports/` e `logs/`: relatórios do Claude e logs de cada sessão.

## Comandos úteis

```bash
docker exec trello-automator ./run.sh --dry-run      # teste: só o Claudio, sem implementar nem olhar o PR
docker exec trello-automator ./run.sh                # sessão completa agora
docker exec trello-automator ./run.sh --all-levels   # sessão completa como se fosse quinta
docker exec -w /home/vip-2002/MyProjects/trello_automator trello-automator uv run --frozen pytest
tail -f data/logs/routine.log
```

Saída do Claude de cada implementação ou correção: `data/logs/<sessão>-claude.log`. Para a
rotina parar de acompanhar um PR (e voltar a pegar cards novos), apague `data/pull_request.json`.
