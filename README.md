# Observatório de Ações — notícias → probabilidade de retorno anormal

Protótipo funcional da modernização do TCC *Mineração de Notícias Econômicas*,
reapontado de FX (EUR/USD) para ações da B3.

**Dependências:** `requests`, `numpy`, `pyyaml`. Nada mais. Servidor web, banco,
parser de RSS, clusterização e regressão isotônica são stdlib ou escritos à mão —
dá para rodar em qualquer máquina sem `pip install`.

```bash
python3 -m obs.cli init
python3 -m obs.cli cycle          # pipeline completo
python3 -m obs.cli serve          # painel em http://127.0.0.1:8000
```

No painel, clique no **nome de um papel** para abrir `/acao.html?t=PETR4`: o
gráfico de preço de fechamento com cada notícia marcada no dia em que saiu —
verde (▲) quando o texto sugere subida, vermelho (▼) quando sugere descida,
cinza quando é neutra; o tamanho é o peso da notícia. Os dados vêm de
`GET /api/chart/<T>?dias=365` (`dias=0` = histórico inteiro).

### O que o painel mostra, e com que lastro

- **Horizonte** (Próxima abertura · D+1 · D+5): cada cabeça só mostra valor no
  horizonte em que foi medida; nos outros a tela diz "não medido". O mapa e os
  selos de qualidade vivem em `obs/medidas.py` — o HTML não tem número escrito.
- **Agitação**: percentual só com calibrador aprovado fora da amostra
  (`python3 -m obs.cli calibrate-vol`; `--simular` só mede). A porta exige
  AUC ≥ 0,55 com IC95 acima de 0,5 e skill de Brier ≥ 0,01. Sem isso a coluna
  mostra uma **faixa** (baixa/média/alta) relativa à watchlist — nunca %.
- **Cadeia de afetação**: top-4 drivers por papel (`drivers.fit_exposures`),
  em `/api/ticker/<T>` e nas duas telas. Descritiva; teste de permutação não feito.
- **Surpresa macro**: estado da camada em `/api/status` (`surpresa.estado()`),
  com o motivo da porta fechada. `ATIVO = False`: não influencia nenhum número.

## Os dois visores

| | |
|---|---|
| **P(alta)** | probabilidade de retorno **anormal** positivo em D+1 |
| **P(queda)** | probabilidade de retorno **anormal** negativo em D+1 |

Não somam 100%: o resto é a classe **neutro**, que na prática fica com a maior
parte da massa — e isso é o resultado correto, não um defeito.

"Anormal" = retorno do papel menos o retorno do mercado, em múltiplos da
volatilidade do próprio papel. Sem isso o modelo aprende a prever o Ibovespa,
e +1% na WEGE3 contaria igual a +1% na MGLU3.

Cada barra mostra um **traço vertical na taxa-base** do papel. A leitura correta
não é "73% é alto" — é "73% contra uma base de 34% é uma vantagem de 39 p.p.".

## Por que ele às vezes se recusa a mostrar número

Com menos de 120 eventos rotulados, os visores exibem **NÃO CALIBRADO**.
Uma probabilidade não calibrada é decoração: se o modelo diz 0,73 e
historicamente os 0,73 subiram 52% das vezes, o visor está mentindo. O sistema
prefere dizer "não sei".

Mesmo calibrado, há **encolhimento para a taxa-base** por evidência (`n_eff`):
uma notícia fraca de fonte ruim não move o visor. Quanto menos evidência, mais
a probabilidade converge para a taxa-base — "não sei" é uma resposta.

## Alarmes

Não disparam por `P(alta) > 60%`. Disparam por **vantagem sobre a taxa-base**,
com quatro portas (`config/alarms.yml`):

1. `min_edge` — vantagem mínima em pontos percentuais
2. `min_n_eff` — evidência efetiva mínima
3. `require_novelty` — exige pelo menos uma *primeira reportagem* no cluster
4. `require_calibrated` — sem calibração, não alarma

Mais `cooldown_min` por papel e direção, para não metralhar a mesma história.
Canais: `console`, `file`, `desktop` (notify-send), `telegram`.

```yaml
rules:
  - ticker: PETR4
    direction: both
    min_edge: 0.10
  - ticker: MGLU3
    direction: down      # só me avise de queda
    min_edge: 0.15
```

## Pipeline

```
GDELT 2.0 + RSS  →  ingest.py     published_ts ≠ ingested_ts (point-in-time)
       ↓
entity.py        →  notícia → ticker, com filtro de relevância econômica
       ↓               (busca "Petrobras" traz matéria sobre futebol; relevance separa)
dedupe.py        →  cluster de quase-duplicatas → POPULARIDADE e NOVIDADE
       ↓
score.py         →  texto → {s, magnitude, event_type}   [llm | ensemble | lexicon]
       ↓               padrão: llm. Sem proxy, cai para lexicon DIZENDO que caiu
       ↓
aggregate.py     →  w = veículo × relevância × novidade × materialidade × decaimento
       ↓               z = Σ(s·w)/Σw      n_eff = Σw
calibrate.py     →  Platt z → P(alta), P(queda) + encolhimento
       ↓
alarms.py        →  vantagem sobre taxa-base + portas + cooldown
```

## O que herdou do TCC de 2013 e o que mudou

| TCC original | Aqui |
|---|---|
| SimilarWeb → popularidade do jornal | peso por veículo, **aprendível** dos dados |
| cluster de notícias ≈ popularidade | cluster = popularidade, **posição no cluster = novidade** |
| LingPipe (descontinuado em 2011) | **LLM como leitor** (4/10/2026); lexicon como piso auditável e rede |
| tradução para inglês | desnecessária (e com embeddings, dispensável de vez) |
| árvore sintática Stanford | removida: não contribuía para o alvo |
| acurácia de 87% / 99% | IC, skill de Brier, monotonia por decil, custo |

A releitura mais importante: **preço reage a surpresa, não a notícia**. A 20ª
repercussão de um fato já precificado vale quase zero. Daí `novelty`.

## Validação

```bash
python3 scripts/backtest.py --folds 6 --embargo-days 3
```

Walk-forward com embargo. K-fold aleatório em série temporal vaza futuro e
devolve resultado bom que não existe.

Métricas: **IC** (Spearman sinal × retorno anormal; 0,02–0,05 já é útil),
**skill de Brier** contra a taxa-base, **monotonia dos decis**, acerto
condicionado a sinal forte. Acurácia não entra — com 70% de casos neutros, 70%
de acurácia é o resultado de chutar "neutro" sempre.

O backtest reporta bruto, **sem custo**. Spread + slippage na B3 comem boa parte.

### Por que o calibrador padrão é Platt e não isotônica

Medição, não gosto. No walk-forward sobre dados sintéticos com sinal verdadeiro
embutido, a isotônica fica com skill de Brier **negativo** fora da amostra
(decora os nós), enquanto Platt — dois parâmetros — se segura:

```
skill Brier [   platt] : alta +0.0018  queda -0.0002
skill Brier [isotonic] : alta -0.0048  queda -0.0069
IC (Spearman)          : +0.0480
```

Repare no contraste: o **IC detecta o sinal** (+0,048), mas o **skill de Brier
é ~0**. Isso é o retrato fiel do problema — há informação no agregado
transversal e quase nenhuma na probabilidade de um evento isolado. É
exatamente por isso que o visor encolhe para a taxa-base e que os alarmes
exigem vantagem, e não probabilidade absoluta.

Troque para isotônica (`--method isotonic`) só com alguns milhares de eventos.

## Defeitos encontrados rodando contra dados reais

Vale registrar, porque todos aparecem em qualquer reimplementação:

| sintoma | causa raiz |
|---|---|
| skill de Brier **negativo dentro da amostra** (impossível para isotônica) | `predict` interpolava entre bordas direitas de bloco; e `z` duplicados caíam em blocos diferentes, deixando o ajuste sem ser função de `x`. Correção: agregar `x` duplicados antes da PAVA e emitir dois nós por bloco |
| notícia da Vale casando com matéria sobre bots | o alias `VALE` em minúscula casa com a palavra comum "vale". Correção: código de papel casa **com caixa**; aliases ambíguos barrados |
| `MISSING_TOKEN` do brapi no 2º lote, OK no 1º | não é falta de auth nem limite de lote: é **cota** de símbolos por janela do tier gratuito. A mensagem engana e faz perder tempo procurando problema de autenticação |
| metade dos tickers sem notícia | GDELT responde 429 pedindo **1 requisição a cada 5 s**; com 2,5 s metade volta vazia, e a mensagem de throttle em texto puro ainda aparecia como "json inválido" |
| "juros sobre o capital próprio" pontuava 0, mas "JCP" pontuava | scorer por token não vê expressão de várias palavras — a mesma notícia valia coisas diferentes conforme o jornal abreviasse |
| notícia em que a empresa é a parte **perdedora** pontuava positivo | o léxico soma o tom do texto e nunca pergunta a posição da empresa no fato. A heurística que corrige isso existia e **não era chamada**: `score.run()` omitia o ticker. +0,35 sem ticker, −0,35 com ele |
| léxico 87,8 em 100 e LLM 53,9 no conjunto-ouro | **gabarito circular**: 93 dos 115 casos vêm de uma regra cujos termos estão no dicionário `POS` do léxico. Medir leitor contra gabarito de palavra-chave premia quem lê palavra-chave |
| duas matérias do mesmo anúncio em clusters distintos | Jaccard não une paráfrase. Mitigado por **impressão digital numérica** (mesma cifra citada) |
| cifra "R$ 3,8 bi" virando `8e9` | `norm()` apaga a vírgula decimal antes do regex. Extrair cifra do texto cru |
| `OverflowError` no SQLite | SimHash de 64 bits estoura o `INTEGER` signed. Usar 63 |

## Limites conhecidos

- **GDELT só dá título.** Título carrega o evento, mas corpo carrega magnitude.
  Baixar o corpo é o primeiro upgrade.
- **Clusterização é global, não por papel.** Por isso o limiar de Jaccard
  precisa ser alto mesmo com cifra em comum. Clusterizar *dentro de cada
  ticker* permitiria limiar bem menor com a mesma precisão.
- **Embeddings resolveriam de vez.** "corta guidance" e "reduz projeção" são a
  mesma história e o Jaccard dá 0,38.
- **Lexicon é fraco de propósito.** É o piso a ser batido, não o produto. Desde
  4/10/2026 o leitor padrão é o LLM, e o piso segue existindo para duas coisas:
  medir o ganho contra algo reproduzível, e manter o pipeline de pé sem proxy.
  **O ganho do leitor novo não foi medido** — ver `docs/parecer.md`, seção 4.
- **O brapi gratuito não cobre 10 papéis.** Cota por janela, e só ~21 pregões
  de histórico — insuficiente para calibrar. Pegue um token gratuito em
  brapi.dev e defina `BRAPI_TOKEN`, ou troque a fonte de preços.
- **Beta = 1** no modelo de mercado. Beta estimado exige histórico longo.
- **Contaminação de LLM**: um modelo treinado até hoje *sabe* o que aconteceu.
  Em `score.py` o LLM só extrai fatos do texto, sem data e sem pedir desfecho.
  Backtest histórico com LLM moderno vaza futuro — valide pós-cutoff.

## Caminho de upgrade

1. corpo do artigo + embeddings multilíngues (clusterização e relevância melhores)
2. ~~LLM como extrator estruturado~~ **feito em 4/10/2026** — é o leitor padrão,
   com extração em coluna (`papel_no_fato`, `ja_precificado`, `is_rumor`,
   `quote`). **Falta medir o ganho de IC**:
   `scripts/evento_noticia.py --scorer lexicon --scorer llm`
3. `fit-source-weights`: aprender quais veículos de fato antecedem o movimento
4. intradiário 15 min + surpresa contra consenso em eventos agendados
5. propagação em grafo (contágio setorial / cadeia de fornecedores)

Parecer técnico do projeto, com o placar completo da evidência e a decisão sobre
quem lê a notícia: [`docs/parecer.md`](docs/parecer.md).

---

Observatório de pesquisa. **Não é recomendação de investimento.**
# observatorio
