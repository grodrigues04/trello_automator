# trello_automator

Rotina que implementa os cards da coluna GUSTAVO do Trello no ratUFSC. Funcionamento completo no
[`README.md`](README.md).

## Onde fica cada coisa

- **Regras determinísticas são código** (`src/trello_automator/`): horários, PR da rotina antes de
  card novo (`pull_request.py`), filtro de complexidade (0 a 7, quinta todos), ordem de quem
  escolhe (Claudio → Squeaker → automático), textos das mensagens, git antes da implementação,
  envio do relatório. Toda regra nova entra aqui,
  com teste em `tests/unit/`.
- **Julgamento é prompt** (`prompts/`): a nota de complexidade, a revisão de risco e as instruções da implementação e das correções no ratUFSC
  (branch, commits, PR, relatório). As instruções para o Claude que
  implementa ficam em `prompts/implementation.md`, e **não** no `CLAUDE.md` do ratUFSC, que é
  compartilhado com os outros devs.
- Textos das mensagens: `messages.py`. Todos começam com `(claude_automatico)`. Os textos que o
  Gustavo definiu (aviso do grupo Squeaker, `Resposta invalida -> envie apenas um numero`, fora da
  escala) têm teste e não mudam sem pedido.

## Regras

- O Claude que implementa tem acesso aos arquivos do Gustavo (decisão dele). Por isso: a revisão
  de risco roda antes, **sem ferramentas** (`--tools ""`); implementação e correções rodam com
  `--strict-mcp-config` (sem conectores); e as variáveis de `SECRET_VARIABLES` (`config.py`) nunca são repassadas aos processos
  do Claude. Não afrouxar nenhuma dessas proteções.
- O Trello é acessado só pelo script, pela API REST (`trello.py`). Nenhum Claude fala com o Trello.
- Mensagens só pela `interface-personal-whats` (regra do `~/MyProjects/CLAUDE.md`). `--dry-run`
  nunca escreve no grupo Squeaker.
- `data/` não vai para o git: tem conteúdo dos cards, logs e relatórios.
- Código em inglês, mensagens e documentação em português. Bump de versão em `version.py`.
