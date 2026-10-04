# Protocolo de validação

## Pergunta correta

A pergunta não é “o modelo consegue classificar texto econômico?”.  
A pergunta é: **adicionar a informação disponível na notícia antes do desfecho melhora a previsão fora da amostra, além do baseline de preço?**

## Regras obrigatórias

### 1. Integridade temporal
- Features de uma notícia usam somente texto e metadados existentes até `published_ts`.
- O alvo é retorno anormal posterior ao instante do sinal.
- `ingested_ts` não pode substituir `published_ts` no backtest.
- Toda divisão é temporal; nunca aleatória.

### 2. Unidade de análise
A unidade recomendada é:

```text
(ticker, cluster de notícia, instante da primeira publicação independente)
```

Não usar cada republicação como observação independente.

### 3. Baselines
Avaliar, no mesmo conjunto de teste:
1. taxa-base;
2. preço/drivers apenas;
3. texto apenas;
4. preço/drivers + texto;
5. preço/drivers + texto + features psicológicas.

A informação de texto só é útil se o item 4 superar o 2 fora da amostra.

### 4. Métricas
- IC de Spearman para alvo contínuo;
- AUC para classificação binária;
- Brier skill para probabilidades;
- curvas por decil;
- Fama–MacBeth ou agrupamento por data para sinais transversais;
- teste de permutação;
- custo e turnover para qualquer alegação econômica.

### 5. Testes negativos
- deslocar cada notícia 1, 5 e 20 pregões no tempo;
- embaralhar timestamp dentro do mesmo ticker;
- comparar com textos irrelevantes;
- comparar primeira publicação com republicações;
- remover fontes sindicais duplicadas.

Se a métrica continuar alta após o deslocamento ou embaralhamento, o resultado é provavelmente artefato.

## Critérios para liberar o canal de notícias

Liberar somente se todos forem verdadeiros:
- ganho fora da amostra sobre preço/drivers;
- IC incremental acima de zero com intervalo ou permutação favorável;
- direção dos decis monotônica;
- sem degradação material de Brier skill;
- efeito não desaparece ao agrupar por dia e por cluster;
- timestamp e corpo de texto auditáveis.

Caso contrário, o canal permanece “implementado, não validado”.
