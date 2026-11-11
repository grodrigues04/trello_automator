FROM node:22-bookworm-slim

ENV TZ=America/Sao_Paulo \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    # Outside the mounted project, so it never clashes with the .venv of the host
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates curl tzdata python3 python3-venv procps \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

RUN npm install -g @anthropic-ai/claude-code@2.1.322 && npm cache clean --force

# Same uid as the owner of ~/MyProjects on the host (node is 1000)
RUN mkdir -p /opt/venv && chown node:node /opt/venv
USER node

WORKDIR /home/vip-2002/MyProjects/trello_automator
CMD ["./scheduler.sh"]
