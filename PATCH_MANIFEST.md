# Patch do Observatório

Este ZIP contém somente arquivos adicionados ou alterados em relação ao ZIP original.

## Como aplicar

1. Faça backup do projeto original.
2. Extraia este ZIP **dentro da raiz do projeto `observatorio/`**.
3. Permita sobrescrever arquivos existentes.
4. Instale dependências novas:

```bash
pip install -r requirements.txt
pip install -r proxy/requirements.txt
```

5. Crie a configuração do proxy:

```bash
cp proxy/mcp-models.properties.example proxy/mcp-models.properties
```

6. Não coloque cookies, chaves ou dados em versionamento.

## Arquivos modificados
- `obs/api.py`
- `obs/cli.py`
- `obs/contabil.py`
- `obs/db.py`
- `obs/externo.py`
- `obs/volatility.py`
- `requirements.txt`
- `web/acao.html`
- `web/index.html`

## Arquivos adicionados
- `config/empresas.yml`
- `docs/README.md`
- `docs/api.md`
- `docs/arquitetura.md`
- `docs/auto-discovery.md`
- `docs/canal-noticias.md`
- `docs/decision-log.md`
- `docs/direcao.md`
- `docs/fontes-de-dados.md`
- `docs/implementacao-configurada.md`
- `docs/macro.md`
- `docs/metricas.md`
- `docs/operacoes.md`
- `docs/pead.md`
- `docs/proxy-sai.md`
- `docs/psicologia.md`
- `docs/relatorios.md`
- `docs/universo.md`
- `docs/validacao.md`
- `obs/earnings.py`
- `obs/llm_client.py`
- `obs/ops.py`
- `obs/reports.py`
- `obs/ri.py`
- `obs/universe.py`
- `proxy/main.py`
- `proxy/mcp-models.properties.example`
- `proxy/requirements.txt`
- `scripts/start_proxy.sh`
- `web/admin.html`

## Observações

- Nenhum arquivo de `data/` foi incluído.
- Nenhuma credencial, cookie, token ou configuração privada foi incluída.
- O patch não exclui arquivos existentes do seu projeto.
- Para processar a fila da Central de Operações, inicie:

```bash
python -m obs.cli worker --seconds 20
```
