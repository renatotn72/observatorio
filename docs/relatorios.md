# Relatórios, PDFs e IA

## Fluxo local

1. Cadastre um PDF:
   `python -m obs report-add --ticker PETR4 --file /caminho/release.pdf --kind RELEASE --period 2026T2`
2. Extraia o texto localmente:
   `python -m obs report-extract --id 1`
3. Veja o relatório em `acao.html` e abra o PDF pelo painel.

O PDF fica em `data/reports/<ticker>/` e o texto extraído em `data/report_text/`.

## Análise por IA

A análise estruturada extrai fatos, resultados operacionais, guidance, riscos,
itens não recorrentes, dívida/caixa, números e trechos de evidência.

Por decisão do operador, **nenhum texto sai da máquina por padrão**. Para autorizar uma API
compatível com OpenAI, configure:

```text
OBS_LLM_URL
OBS_LLM_KEY
OBS_LLM_MODEL
OBS_ALLOW_EXTERNAL_LLM=1
```

Então execute:

```text
python -m obs report-analyze --id 1 --externo
```

Sem `--externo`, a análise é local e limitada a termos/trechos; ela não finge ser uma
interpretação contábil completa.

## Regras

- IA extrai fatos; não gera recomendação de compra ou venda.
- Toda conclusão da IA deve trazer trecho de evidência.
- Conteúdo de relatório pode ser sensível; autorização externa é explícita e revogável.
- O link remoto da CVM/RI pode ser cadastrado, mas para leitura local/IA é necessário o PDF local.
