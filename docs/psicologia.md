# Psicologia, propagação e o canal de notícias

## Estado em 2026-10-02 — o que saiu do papel

| Feature | Onde | Estado |
|---|---|---|
| `fontes_efetivas` | `obs/atencao.py` | implementada, verificada |
| `velocidade_cascata` | `obs/atencao.py` | implementada, verificada |
| `razao_repeticao` | `obs/atencao.py` | implementada, verificada |
| `medo` (excitação) | `obs/atencao.py` | implementada, verificada |
| `surto` (attention burst) | `obs/atencao.py` | implementada, verificada |
| ligação na cabeça de agitação | `volatility.build_features` | ligada, **não medida** |
| `frame_loss`, `novelty_semantic` | — | não implementadas |

**O calibrador aprovado de agitação (AUC 0,590) não usa nenhuma delas.** Ele
roda com cinco features de preço e calendário. Portanto a hipótese central
desta página — atenção + propagação + emoção elevam a chance de movimento
grande — segue **não testada**. O que falta é histórico de notícia casado com
retorno, que `obs backfill` produz; `scripts/atencao_test.py` mede quando houver.

## A distinção que faltava: novidade ≠ atenção

O sistema só tinha novidade, e com isso jogava fora informação real.

| | pergunta | serve a | onde |
|---|---|---|---|
| **Novidade** | isso é novo para o mercado? | direção | `dedupe.novelty` |
| **Atenção** | quanto interesse despertou? | magnitude | `obs/atencao.py` |

As duas não se contradizem. A 20ª cópia é informação velha (novidade 0,22) e
ao mesmo tempo prova de que vinte redações julgaram o assunto publicável.

Mas cópia não é voto. `fontes_efetivas` usa o número de Hill (exp da entropia
dos domínios). Medido em clusters reais do banco:

| artigos | domínios | fontes efetivas | caso |
|---|---|---|---|
| 13 | 1 | **1,00** | um veículo se republicando |
| 7 | 2 | 1,51 | dois veículos |
| 3 | 3 | **3,00** | descoberta da Petrobras, três redações |

A contagem bruta diria 13 > 3. A medida de interesse real diz 1,00 < 3,00.

## Tese central

A teoria psicológica do TCC de 2013 é útil **como fonte de hipóteses de features**, não como prova de previsão de preço.

Ela é especialmente compatível com o produto de **agitação**, porque atenção, medo, repetição, incerteza e propagação social tendem a alterar a intensidade da reação. Não se deve pressupor que eles indiquem a direção correta do retorno.

## Mapa teoria → feature observável

| Hipótese comportamental | Feature implementável | Uso recomendado |
|---|---|---|
| Atenção / disponibilidade | primeira notícia, cobertura recente, diversidade de fontes, velocidade de republicação | prever magnitude e priorizar alertas |
| Repetição / familiaridade | número de fontes independentes e recorrência do cluster | medir cascata, nunca contar cópias como votos |
| Prova social / julgamento de grupo | concentração de fontes, prestígio aprendido, confirmação por domínios distintos | materialidade e confiança do evento |
| Medo / aversão à perda | léxico de risco, perda, default, fraude, corte, investigação, urgência e incerteza | magnitude, especialmente em ações alavancadas |
| Enquadramento | ganho versus perda, certeza versus possibilidade, agente causal e intensidade verbal | direção textual e materialidade |
| Ancoragem | referência explícita a preço-alvo, pico anterior, guidance ou consenso | comparar notícia com expectativa disponível antes do evento |
| Representatividade | similaridade com casos passados e novidade semântica | identificar “caso novo” versus narrativa conhecida |
| Memória / decaimento | recência e meia-vida de clusters anteriores | evitar tratar notícia velha como nova |
| Otimismo ilusório | linguagem de certeza sem evidência, alvo extremo, promessa vaga | alerta de baixa confiabilidade, não sinal direcional |

## Implementação recomendada

### 1. Não usar “sentimento” como sinônimo de psicologia
Polaridade positiva/negativa já existe no léxico. A contribuição nova é medir:
- **quem** publicou;
- **quantas fontes independentes** confirmam;
- **quão rápido** a narrativa se espalhou;
- **se o conteúdo é novidade ou repetição**;
- **se há incerteza, ameaça, perda ou enquadramento extremo**.

### 2. Separar repetição de confirmação
Dez cópias da mesma agência devem equivaler a um evento.  
Duas investigações independentes de fontes distintas podem ser um sinal de confirmação.

### 3. Usar a psicologia primeiro na cabeça de volatilidade
A hipótese a testar é:

> alto estado de atenção + propagação rápida + emoção/risco + materialidade elevam a probabilidade de movimento grande, independentemente do lado.

Essa hipótese é mais compatível com a evidência atual do projeto do que “tom negativo prevê queda amanhã”.

### 4. Aprender pesos, não fixá-los por teoria
O TCC propunha peso por popularidade/prestígio. No projeto atual, o peso da fonte deve ser aprendido somente no treino temporal e validado em janela posterior, de preferência por par `(fonte, tipo de evento)` ou `(fonte, driver)`.

## Features de cascata propostas

```text
cascade_speed      = fontes_independentes nas primeiras 2 horas
source_diversity   = número efetivo de domínios no cluster
first_source_score = peso aprendido da primeira fonte
repeat_ratio       = republicações / fontes independentes
attention_burst    = artigos por hora contra baseline do ticker
fear_score         = risco + perda + incerteza + urgência
frame_loss         = enquadramento de perda versus ganho
novelty_semantic   = distância para clusters anteriores
```

Essas variáveis só viram sinal depois de demonstrarem ganho incremental fora da amostra.
