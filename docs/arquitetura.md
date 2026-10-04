# Arquitetura

## Objetivo

O Observatório combina notícias, preços e variáveis macro para explicar e, somente quando validado, estimar comportamento relativo entre ações.

O alvo principal não deve ser confundido com retorno bruto: a rotulagem usa **retorno anormal transversal**. Assim, o sistema busca informação específica de cada ação e não apenas o movimento geral do mercado.

## Pipeline

```text
Fontes de notícias ─┐
                    ├─> ingestão ─> entidade/relevância ─> deduplicação
Drivers de mercado ─┘                                      │
                                                           v
                             leitura: LLM (padrão) | léxico (piso/rede)
                                                           │
                               cadeia de afetação ─> roteamento de consultas
                                                           │
                                                           v
                         agregação ponderada por ação ─> calibração / faixas
                                                           │
                                              painel, API e alarmes
```

## Etapas

1. **Ingestão**
   - `obs/ingest.py` consulta GDELT 2.0 e feeds RSS/Atom.
   - `published_ts` e `ingested_ts` são persistidos separadamente.
   - A separação é obrigatória para medir atraso de fonte e impedir look-ahead.

2. **Entidade e relevância**
   - Menções vinculam artigo e ticker.
   - Aliases ambíguos devem ser bloqueados; código de ação é sensível a caixa.
   - O objetivo não é somente achar o nome da empresa, mas diferenciar matéria material de citação incidental.

3. **Deduplicação e novidade**
   - SimHash, Jaccard e impressão numérica agrupam repercussões.
   - O primeiro relato e confirmações independentes são mais informativos que republicações idênticas.

4. **Leitura da notícia** (quem pontua)
   - `obs/score.py` produz sempre o mesmo schema, qualquer que seja o leitor:
     `s` (direção), `magnitude` e `event_type`.
   - **Desde 2026-10-04 o leitor padrão é o LLM** (`SCORER_PADRAO = "llm"`,
     sobrescrito por `OBS_SCORER`). Ele preenche também `papel_no_fato`,
     `ja_precificado`, `is_rumor` e `quote`, que são colunas de `scores`.
   - O **léxico** PT+EN continua, com dois papéis: piso auditável contra o qual
     o ganho do LLM é medido, e rede quando não há proxy autorizado. A queda
     para o léxico é sempre anunciada — terminal, `/api/status.scorer` e painel.
   - O LLM é **sensor de fatos estruturados; não prevê preço**. O prompt proíbe
     pedir data, preço ou desfecho (`docs/decision-log.md`).
   - No **backfill histórico** o padrão permanece o léxico, por contaminação:
     um modelo com cutoff conhece o desfecho da manchete antiga. Ver
     `docs/canal-noticias.md`.
   - Estado da evidência: **implementado, não validado**. O ganho de leitura
     ainda não foi medido contra retorno realizado (`docs/parecer.md`, seção 4).

4b. **Classificação do evento** (`obs/evento.py`)
   - Duas dimensões **independentes**, gravadas em `scores`:
     `tipo_evento` (corporativo, macro, judicial, legislativo, calendário) e
     `orientacao` (conjunto de passado, presente, futuro).
   - `orientacao` é CONJUNTO: decisão proferida mais recurso pendente é
     `passado,futuro`. Campo único obrigaria a escolher, e a resposta certa
     são os dois.
   - **Nenhuma das duas entra no sinal.** Elas descrevem e filtram. Errar aqui
     polui a leitura da tela, não a medição — diferente do `s`, onde errar o
     lado estraga o resultado.
   - Ver `docs/eventos.md`.

5. **Cadeia de afetação**
   - `obs/drivers.py` estima exposição por regressão ridge usando somente dados anteriores ao ponto `asof`.
   - Cada exposição possui `beta`, `share`, `r2` e número de observações.
   - `share` é a fração da exposição relativa do papel a um driver, não uma probabilidade de alta.

6. **Roteamento**
   - `obs/ingest.py::fetch_roteado()` permite que uma ação receba matéria sobre um driver relevante.
   - Exemplo: notícia sobre petróleo pode ser roteada a PETR4; o peso depende do `share` e o sinal pode ser invertido se o beta for negativo.

7. **Agregação**
   - `obs/aggregate.py` usa:
     `w = peso_da_fonte × relevância × novidade × materialidade × decaimento × peso_do_driver`
   - Meia-vida padrão de notícia: 8 horas.
   - Notícias roteadas recebem multiplicação pelo `share` do driver.
   - A direção é invertida quando a exposição estimada ao driver é negativa.

8. **Rotulagem e apresentação**
   - `obs/label.py` cria classes alta/neutro/queda a partir de retorno anormal futuro.
   - `obs/calibrate.py` e `obs/volatility.py` somente devem expor probabilidades quando as portas de calibração forem aprovadas.
   - Caso contrário, a interface mostra faixa ordinal ou status “não calibrado”.

## Cabeças do sistema

- **Direção:** alta ou queda anormal em D+1.
- **Agitação:** magnitude/volatilidade anormal em D+1.
- **Meta-label:** confiança de que a direção está correta; permanece desligada enquanto reprovada.

## Princípios de arquitetura

- Sem timestamp confiável, não há feature de backtest.
- Sem incremento fora da amostra, não há “sinal”.
- Fonte, notícia e macro são entradas distintas; não se deve somar sinais correlacionados como se fossem independentes.
- A cadeia de afetação é prioritariamente um **roteador de notícias**, não licença para afirmar causalidade de preço.
