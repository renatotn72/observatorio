#!/usr/bin/env bash
# Sobe o proxy OpenAI-compatible e exporta as variaveis do Observatorio.
#
# O proxy roda com Flask quando instalado; sem Flask ele cai no adaptador de
# stdlib (proxy/_miniflask.py), entao funciona em ambiente sem pip.
set -euo pipefail
cd "$(dirname "$0")/.."

PORTA="$(grep -E '^server\.port=' proxy/mcp-models.properties | cut -d= -f2 | tr -d '[:space:]')"
PORTA="${PORTA:-8100}"

echo "Subindo proxy na porta ${PORTA}..."
( cd proxy && python3 main.py ) &
PROXY_PID=$!
sleep 4

if curl -sS --max-time 10 "http://127.0.0.1:${PORTA}/health" >/dev/null 2>&1; then
  echo "proxy OK em http://127.0.0.1:${PORTA}"
else
  echo "proxy NAO respondeu em /health -- veja o log acima" >&2
fi

cat <<EOF

Para o Observatorio usar o proxy, exporte no SEU shell:

  export OBS_LLM_URL="http://127.0.0.1:${PORTA}/v1/chat/completions"
  export OBS_LLM_KEY="local-proxy-client"
  export OBS_LLM_MODEL="sai-dev-gpt5"
  export OBS_ALLOW_EXTERNAL_LLM=1

PID do proxy: ${PROXY_PID}
EOF
wait ${PROXY_PID}
