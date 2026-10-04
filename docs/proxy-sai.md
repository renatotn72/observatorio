# Proxy SAI OpenAI-compatible

O proxy integrado é a versão original `proxy/main.py` (baseada em `main3.py`).
A fonte única de configuração é:

```text
proxy/mcp-models.properties
```

## Instalação

```bash
cd proxy
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp mcp-models.properties.example mcp-models.properties
# preencha sai.cookie no arquivo
python main.py
```

O proxy sobe na porta configurada em `server.port`, por padrão `8100`.

## Configuração obrigatória para o Observatório

No `mcp-models.properties`:

```text
proxy.promptMode=raw
```

Esse modo preserva o `system` prompt enviado pelo Observatório. O modo `surgical`
foi desenvolvido para Hermes/agentes de código e substitui instruções por um prompt de
engenharia, portanto não é apropriado para leitura financeira.

No ambiente do Observatório:

```text
OBS_LLM_URL=http://127.0.0.1:8100/v1/chat/completions
OBS_LLM_KEY=qualquer-valor-obrigatorio-para-o-cliente
OBS_LLM_MODEL=sai-dev-gpt5
OBS_ALLOW_EXTERNAL_LLM=1
```

A autenticação real e os parâmetros SAI continuam em `mcp-models.properties`, como no
proxy original.

## Relatórios

O Observatório extrai o PDF localmente, adiciona marcadores de página, divide texto em
chunks e envia mensagens OpenAI-compatible ao proxy. O proxy não recebe PDF binário.
