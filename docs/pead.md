# PEAD e surpresa trimestral

## O que é medido

Surpresa trimestral só existe se houver expectativa anterior:

```text
surpresa = (realizado - consenso) / dispersão
```

O projeto registra:
- `earnings_consensus`: consenso por ticker, período, métrica e timestamp;
- `earnings_actual`: realizado e horário de divulgação;
- `earnings_surprises`: diferença calculada.

## Importação de consenso

O CSV deve conter:

```text
ticker,period,metric,consensus,dispersion,n_analysts,asof_date,source
```

Campos mínimos: `ticker`, `period`, `metric`, `consensus`, `asof_date`, `source`.

Importar:

```text
python -m obs consensus-import --file consenso.csv
python -m obs earnings-compute --ticker PETR4
```

## Estado atual

Não há fonte de consenso configurada. Portanto a camada PEAD está estruturada, mas não
ativada como sinal. Não confundir lucro realizado, crescimento trimestral ou manchete
positiva com surpresa de resultado.

## Métricas a testar

- receita;
- EBITDA;
- lucro líquido ou lucro por ação;
- margem;
- guidance;
- D+5, D+10 e D+20 de retorno anormal.

O sinal só pode ser ativado após ganho incremental fora da amostra contra o baseline de preço/drivers.
