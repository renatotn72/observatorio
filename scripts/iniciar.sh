#!/usr/bin/env bash
# Sobe o Observatorio inteiro: proxy, dados base, painel e worker.
# Uso:  bash scripts/iniciar.sh [--reiniciar]
#
# --reiniciar derruba proxy e painel antes de subir. Use SEMPRE que mexer em
# codigo: processo no ar guarda o modulo que importou no arranque, entao sem
# reiniciar voce testa a versao velha e conclui que a correcao nao funcionou.
set -uo pipefail
REINICIAR=0
[ "${1:-}" = "--reiniciar" ] && REINICIAR=1
cd "$(dirname "$0")/.."
PORTA_PAINEL="${PORTA_PAINEL:-8105}"
PORTA_PROXY="$(grep -E '^server\.port=' proxy/mcp-models.properties 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
PORTA_PROXY="${PORTA_PROXY:-8100}"

ok(){ printf "  \033[32m✓\033[0m %s\n" "$1"; }
aviso(){ printf "  \033[33m!\033[0m %s\n" "$1"; }

if [ "$REINICIAR" = "1" ]; then
  echo "== 0. Derrubando processos antigos =="
  pkill -f "obs.cli worker" 2>/dev/null && ok "worker derrubado"
  pkill -f "obs.cli serve"  2>/dev/null && ok "painel derrubado"
  pkill -f "proxy/main.py"  2>/dev/null
  pkill -f "^python3 main.py" 2>/dev/null
  ( cd proxy && pkill -f "main.py" 2>/dev/null ) && ok "proxy derrubado"
  sleep 2
  # Job que estava rodando quando o worker morreu fica preso em 'running' e
  # trava o grupo dele. Liberar aqui evita que o arranque novo ja comece com
  # um grupo bloqueado -- foi assim que quatro jobs de documento ficaram
  # parados em 'queued' sem explicacao.
  python3 -c "
from obs import ops
from obs.db import connect
con = connect(); ops.init(con)
n = ops.recupera_orfaos(con); con.close()
print(f'  \033[32m✓\033[0m {n} run(s) orfao(s) liberado(s)' if n else '  \033[32m✓\033[0m nenhum run orfao')
" 2>/dev/null || aviso "nao consegui checar runs orfaos"
fi

echo "== 1. Banco =="
python3 -m obs.cli init >/dev/null 2>&1 && ok "esquema pronto"

echo "== 2. Proxy de IA =="
if curl -sS --max-time 5 "http://127.0.0.1:${PORTA_PROXY}/health" >/dev/null 2>&1; then
  ok "ja estava no ar na porta ${PORTA_PROXY}"
else
  ( cd proxy && nohup python3 main.py > ../data/proxy.log 2>&1 & )
  sleep 4
  curl -sS --max-time 8 "http://127.0.0.1:${PORTA_PROXY}/health" >/dev/null 2>&1 \
    && ok "subiu na porta ${PORTA_PROXY}" || aviso "nao respondeu — veja data/proxy.log"
fi

echo "== 3. Dados base =="
python3 -m obs.cli prices --fonte yahoo --range 10y >/dev/null 2>&1 && ok "precos"
python3 -m obs.cli drivers --range 10y        >/dev/null 2>&1 && ok "drivers macro"

echo "== 4. Painel =="
if curl -sS --max-time 5 "http://127.0.0.1:${PORTA_PAINEL}/api/status" >/dev/null 2>&1; then
  ok "ja estava no ar"
else
  nohup python3 -m obs.cli serve --port "${PORTA_PAINEL}" > data/painel.log 2>&1 &
  sleep 5
  curl -sS --max-time 8 "http://127.0.0.1:${PORTA_PAINEL}/api/status" >/dev/null 2>&1 \
    && ok "subiu" || aviso "nao respondeu — veja data/painel.log"
fi

echo "== 5. Worker =="
if pgrep -f "python3 -m obs.cli worker" >/dev/null 2>&1; then
  ok "ja estava rodando"
else
  nohup python3 -m obs.cli worker --seconds 20 > data/worker.log 2>&1 &
  sleep 3
  pgrep -f "python3 -m obs.cli worker" >/dev/null 2>&1 \
    && ok "subiu (log em data/worker.log)" || aviso "nao subiu — veja data/worker.log"
fi

cat <<EOF

  Painel     http://127.0.0.1:${PORTA_PAINEL}/
  Operações  http://127.0.0.1:${PORTA_PAINEL}/admin.html

Para a IA ler documentos, exporte NO SEU SHELL:

  export OBS_LLM_URL="http://127.0.0.1:${PORTA_PROXY}/v1/chat/completions"
  export OBS_LLM_KEY="local-proxy-client"
  export OBS_LLM_MODEL="sai-dev-gpt5"
  export OBS_ALLOW_EXTERNAL_LLM=1

O worker ja esta rodando em segundo plano. Para acompanhar:

  tail -f data/worker.log

EOF
