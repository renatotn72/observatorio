# Ponto 3 — Fontes de preço: o que já existe, e o que o diagnóstico mostrou

**Data:** 4 de outubro de 2026
**Estado:** avaliação e diagnóstico (3.3). **Nada foi coletado nem implementado.**

---

## Resposta curta

**Nada do ponto 3 está implementado.** Não há UOL, não há `data_id`, não há
descoberta de universo, não há interface de provider, não há origem por barra.

Mas o diagnóstico mudou duas premissas do plano:

1. **Não existe buraco no MGLU3.** Os 10 papéis têm 2.492 barras diárias, **zero
   lacunas**, de 2016-10-03 a 2026-10-02. A série diária está completa.
2. **A fonte atual alcança 10 anos no diário — o dobro do teto da UOL.** Para
   diário, a UOL seria um retrocesso, não um backfill.

O buraco real é outro, e o diagnóstico achou: **o SUZB3 está congelado em
R$ 20,01 por 279 pregões**, de 2016-10-03 a 2017-11-09.

---

## 3.3 — Diagnóstico do que já existe

```bash
python3 scripts/diag_precos.py          # tabela completa
python3 scripts/diag_precos.py --csv    # grava data/diag_precos.csv
```

### Diário (`prices`) — completo

Calendário observado: 2.492 pregões, 2016-10-03 a 2026-10-02.

| papel | primeira | última | barras | lacunas | maior buraco |
|---|---|---|---|---|---|
| ABEV3, B3SA3, BBAS3, BBDC4, ITUB4, MGLU3, PETR4, SUZB3, VALE3, WEGE3 | 2016-10-03 | 2026-10-02 | 2.492 | **0** | **0** |

Todos iguais. Nenhum papel da watchlist está sem preço.

### Intradiário (`intraday`) — limitado pela retenção da fonte

| granularidade | período | barras | papéis |
|---|---|---|---|
| 1 min | 27/09 a 02/10/2026 — **5 dias** | 35.022 | 13 |
| 5 min | 02/09 a 02/10/2026 — **1 mês** | 25.698 | 12 |
| 15 min | 03/09 a 02/10/2026 — **1 mês** | 10.588 | 13 |
| 1 hora | 02/10/2024 a 02/10/2026 — **2 anos** | 54.747 | 12 |

### O defeito que o diagnóstico encontrou: SUZB3 congelado

| | |
|---|---|
| período | 2016-10-03 a 2017-11-09 |
| pregões | **279**, todos com o mesmo R$ 20,01 |
| fração da série do SUZB3 | 11,2% |
| fração do banco de preços | 1,1% |

**Causa provável:** a Suzano negociava como SUZB5 e só virou SUZB3 na migração
para o Novo Mercado, em novembro de 2017. A fonte preenche o período anterior
com um valor constante em vez de deixar vazio.

**Consequência medida:**

- retorno diário = 0 em 278 pregões ⇒ a volatilidade medida do SUZB3 ali é
  **zero por construção**. Num alvo do tipo "top 20% mais agitados", o SUZB3
  nunca entra — distorção sistemática, não ruído;
- o benchmark do projeto é a **média transversal do dia**, então um papel
  travado em 0,00 puxa a média: o `|retorno anormal|` dos outros nove fica
  **1,8% menor** dentro da janela (0,01266 contra 0,01289 fora);
- o "anormal" do próprio SUZB3 no período (0,01028) não é movimento dele — é
  o espelho da média do mercado.

O período cai dentro da amostra de `scripts/metrica_total.py` (que começa em
2016-12-02), ou seja, **dentro da medição da cabeça de agitação**, a única
aprovada do projeto. O efeito é pequeno, mas é viés, não ruído.

**Recomendação:** apagar as barras anteriores a 2017-11-10 do SUZB3 antes de
qualquer coleta nova, e acrescentar à ingestão uma guarda contra série
constante (N barras idênticas seguidas ⇒ recusar e avisar).

### Ajuste por proventos — testado localmente

Nenhum salto maior que 35% num pregão, em nenhum dos 10 papéis. O MGLU3, que
teve desdobramento no período, vai de R$ 2,42 a R$ 244,52 **sem salto
artificial**. A série atual **parece ajustada**.

Isso é relevante para a armadilha 3 do seu 3.2: se a UOL **não** ajustar, as
duas séries não são comparáveis e misturá-las na mesma tabela produziria salto
onde não há evento.

---

## O que existe hoje, item por item do seu pedido

| item | estado | onde |
|---|---|---|
| **3.1** universo B3 + `data_id` | **não existe** | — |
| descoberta de empresas | parcial, outra coisa | `obs/universe.py` lê o **cadastro CVM** (emissor + CNPJ), que não é lista de tickers negociados nem traz liquidez |
| classificação ON/PN/UNT × BDR × ETF | **não existe** | — |
| **3.2** endpoints UOL | **não existe** | — |
| **3.3** diagnóstico | **entregue agora** | `scripts/diag_precos.py` |
| **3.4** backfill > 5 anos | **não necessário para diário** (ver abaixo) | — |
| **3.5** provider com interface única | **não existe** | `obs/prices.py` tem duas funções fixas, `fetch` (brapi) e `fetch_yahoo`, escolhidas por um `if` em `sync()` |
| origem por barra | **não existe** | `prices(ticker, date, close)` — sem coluna de origem |
| OHLCV | **não existe** | só `close`. O mesmo em `intraday` |
| idempotência por (ticker, gran, ts) | **existe** | `INSERT OR REPLACE` com chave primária composta |
| registro em `config/sources.yml` | **não existe para preço** | o arquivo só modela feeds de notícia |
| **3.6** termos de uso / robots | **não verificado** | bloqueio de rede, ver abaixo |
| chamada pelo frontend | **existe, limitada** | a Central de Operações (`/admin.html`) enfileira o job `refresh_prices`, que roda `obs prices --range 2y`. Sem escolha de papel, de fonte ou de granularidade |

---

## 3.4 — alcance real da fonte atual, antes de trocar nada

Você pediu para eu dizer isso antes de qualquer troca. Medido no banco:

| granularidade | fonte atual (Yahoo) | UOL, pela sua especificação | quem ganha |
|---|---|---|---|
| diário | **10 anos** (2.492 pregões) | 5 anos fixos (`interday/list/years`) | **atual, por 2×** |
| diário recente | idem | ~65 barras (`interday/list/months`) | atual |
| 1 hora | 2 anos | não oferece | atual |
| 15 min | 1 mês | não oferece | atual |
| 5 min | 1 mês | não oferece | atual |
| 1 min | **5 dias** | **só a última sessão** | atual |
| OHLCV | **tem** no endpoint; **vazio no banco** | **tem**, no interday | **empate** |
| bid/ask (spread) | não oferece | **oferece** | **UOL** |
| descoberta de tickers | **não oferece** endpoint de listagem | **catálogo de ~1.800 com id** | **UOL** |
| universo | 10 papéis na watchlist | **~1.800 tickers** catalogados | **UOL** |

**Conclusão que muda o plano:** a UOL **não é fonte de backfill** — ela é mais
curta que o que você já tem em todas as granularidades. Ela vale por duas
outras coisas:

1. **Descoberta**: ~1.800 papéis contra os 10 de hoje. O Yahoo **não tem
   endpoint de listagem** — para pedir um papel é preciso já saber o ticker, e
   é exatamente por isso que a watchlist travou em 10. A UOL tem catálogo
   paginado com id interno. É o que destrava o universo de 150–300 ações que
   `docs/universo.md` pede desde o início.
2. **bid/ask**: spread cotado. Nem Yahoo nem brapi dão, e
   `docs/canal-noticias.md` pede "liquidez e spread estimado" como feature de
   contexto desde o começo. É a única coisa aqui que **só** a UOL dá.
3. **Segunda opinião** na mesma `(ticker, date)`: é o que permite conferir
   ajuste por proventos sem depender de desdobramento conhecido
   (`obs/prices.py:divergencia`).

### Correção de uma afirmação errada que eu publiquei antes

A versão anterior desta página, de `config/sources.yml` (`yahoo: ohlcv: false`)
e do docstring de `obs/uol.py` dizia que a UOL acrescentava **OHLCV** porque o
Yahoo "só dá fechamento". **Está errado, e o erro inflava o valor desta
fonte.** O endpoint `v8/finance/chart` do Yahoo devolve
`indicators.quote[0].open/high/low/volume` no mesmo pacote do fechamento, e
`obs/prices.py:fetch_yahoo` lê os quatro.

O que é verdade — e é outra coisa — é que **o banco** não tem OHLCV: medido em
4/10/2026, 24.920 barras diárias, **`open` e `volume` nulos em todas**. A causa
não é a fonte, é que as barras foram coletadas antes de o código ler esses
campos. Logo o OHLCV se resolve com a fonte que já existe:

```bash
python3 -m obs.cli prices --fonte yahoo --range 10y --complementar
```

`--complementar` preenche o que está vazio **sem trocar um único fechamento**,
então nenhuma medição já aprovada muda de valor. Ver abaixo.

Então a ordem que você propôs continua certa, mas o **objetivo** muda: não é
"backfill além de 5 anos" nem "OHLCV", é **descoberta de universo + spread**. O
backfill longo continua sendo o problema do pré-2016, e para isso o candidato é
a B3, não a UOL.

---

## Implementado em 4 de outubro de 2026

O provedor da UOL está escrito, testado e ligado ao painel. **Falta só rodar**
— ver o bloqueio de rede abaixo.

### Os três passos, em comandos

```bash
python3 -m obs.cli uol-descobrir              # 1. catálogo de tickers
python3 -m obs.cli uol-sondar --categorias acao   # 2. data-id + validação
python3 -m obs.cli uol-coletar                # 3. cotações dos ativos
python3 -m obs.cli uol-estado                 # relatório de aceite
```

Pelo painel: Central de Operações tem os três como tarefas
(`uol_descobrir`, `uol_sondar`, `uol_coletar`), no mesmo grupo para a ordem
ficar garantida.

### O que foi implementado, item por item

| item | onde |
|---|---|
| catálogo paginado, para só após **3 páginas vazias seguidas** | `uol.catalogo` |
| classificação ação / BDR / ETF-FII / outro, **antes** de qualquer requisição | `uol.classifica` |
| categoria **guardada**, nunca descartada (dá para reincluir BDR) | `ativos.categoria` |
| `data-id` extraído da div e **cacheado no banco** | `uol.extrai_id`, `ativos.id_externo` |
| validação ≥ 60 barras e última ≤ 10 pregões | `uol.avalia` |
| não resondar antes de 30 dias | `uol.pendentes` |
| relatório por categoria e status, com a lista nominal dos SEM_DADO | `uol.estado` |
| User-Agent de browser, requisições serializadas com pausa | `uol.CABECALHO`, `uol.PAUSA_S` |
| OHLCV com volume | `prices(open, high, low, volume)` |
| **bid/ask** (spread) — nenhuma outra fonte do projeto dá | `intraday(bid, ask)` |
| **origem por barra**, separada em fechamento e OHLCV | `prices.origem`, `prices.origem_ohlc`, `intraday.origem` |
| **entra como complemento: não apaga a fonte antiga** | `prices.grava_diario(..., complementar=True)` |
| discordância entre fontes **relatada, não escondida** | `prices.divergencia` |
| idempotência por (ticker, data) e (símbolo, intervalo, ts) | `INSERT OR REPLACE` com PK composta |
| registro em `config/sources.yml` | seção `precos:` |

### Complemento, não substituição — e por que isso precisou de código

Seu requisito foi explícito duas vezes: *"não exclui a forma antiga de obter
preços, é complemento"* e *"mantenha a do Yahoo também"*. O comportamento
ingênuo faz o contrário, **em silêncio**: a chave de `prices` é
`(ticker, date)` e a gravação é `INSERT OR REPLACE`, então coletar da UOL
**reescreveria** cada barra que o Yahoo já tinha — trocando 10 anos de série
ajustada por 5 anos de série de ajuste desconhecido, sem erro, sem aviso e sem
como voltar atrás.

`grava_diario` passou a ter dois modos:

| | `complementar=False` (padrão das fontes canônicas) | `complementar=True` (UOL) |
|---|---|---|
| barra que **não existe** | entra inteira | entra inteira |
| `close` de barra existente | **substituído** | **preservado** |
| `origem` de barra existente | substituída | preservada |
| OHLCV **vazio** de barra existente | substituído | **preenchido** |
| OHLCV **já preenchido** | substituído | preservado |
| quem preencheu o OHLCV | `origem_ohlc` | `origem_ohlc`, acumulando (`yahoo+uol`) |

A procedência virou **dois campos** porque uma barra pode ter duas mães: o
fechamento de uma fonte e o volume de outra. Um campo só obrigaria a escolher,
e escolher aqui significa jogar fora dado bom.

E onde as duas fontes **discordam** no mesmo `(ticker, date)`, nada é
sobrescrito e nada é escondido: `prices.divergencia` relata o par e a diferença
antes de gravar. Isso responde de graça a armadilha 3 (ajuste por proventos)
sem depender de desdobramento conhecido — se uma fonte ajusta e a outra não, os
fechamentos batem depois do último provento e **se afastam progressivamente
para trás**.

As 24.920 barras que já estavam no banco não tinham origem registrada (a coluna
é nova). Ficaram marcadas `origem='legado'`, que afirma só o que é verificável:
*coletada antes de haver registro de procedência*. Não dá para saber se vieram
do brapi ou do Yahoo — `sync()` tentava um e caía para o outro sem registrar
qual atendeu.

### As três armadilhas, travadas por teste

`scripts/test_uol.py` — **91 verificações, sem rede**, com respostas gravadas.
Teste que depende da API estar de pé não roda em CI e, quando falha, não diz se
o defeito é nosso ou da fonte.

Sobre os números da fixture, para ninguém os citar como cotação: o
**comportamento** travado ali é achado da sua sondagem de 4/10/2026, e os
valores que a sua especificação citou (44.15 como `close` da barra 20261002;
45.27 / 43.10 / 45.25 como high/low/open da sessão do ITUB4) são exatos. Os
demais números são preenchimento coerente escrito para fechar a fixture —
nenhuma resposta crua foi capturada aqui, porque a rede não alcança a API. Isso
não enfraquece o teste, que afere o mapeamento e não o preço.

1. **`price` é o fechamento da barra; `close` é o da sessão anterior.** O teste
   não confere só o mapeamento — ele **prova** o deslocamento: verifica que o
   `close` de uma barra é igual ao `price` da barra anterior. Mapear
   `close→close` deslocaria a série inteira em um dia, sem nada no dado
   denunciar.
2. **No intraday não há OHLC.** O mapeador **não devolve** `high`/`low`/`open`,
   porque a API dá valor de sessão, não de barra. O volume da barra é a
   diferença entre acumulados consecutivos.
3. **Ajuste por proventos desconhecido.** `uol.conferir_ajuste` detecta salto
   acima de 35% num pregão e a coleta avisa, com a razão (4:1, 2:1…). Não
   recusa: a origem por barra permite separar depois. Somado a isso,
   `prices.divergencia` compara o fechamento da UOL com o que já está no banco
   na **mesma** barra — teste mais forte, porque não depende de haver
   desdobramento no período.
4. **`bid`/`ask` podem ser da sessão, não da barra.** Não está verificado, e a
   diferença decide se a coluna é spread ou enfeite. O código grava o que veio
   **e responde a pergunta**: `uol.constantes` avisa se bid/ask saírem
   constantes nas ~399 barras, como acontece com high/low/open. O teste cobre
   as duas hipóteses, incluindo o caso de uma barra só, em que a resposta é
   "não dá para saber" e não "é constante".

### Dois defeitos meus que o teste pegou antes de rodar

1. **BDR não patrocinado escapava da classificação.** `A1FL34` não casa com
   `[A-Z]{4}` por causa do dígito — os quatro primeiros caracteres são
   alfanuméricos, não letras. Eles cairiam em `outro` e entrariam na coleta
   como desconhecidos. A página 2 da listagem é inteira disso.
2. **Página "vazia" estava definida errado.** Eu contava como vazia toda página
   sem ticker **novo**; a especificação diz **0 tickers**. Uma página que só
   repetisse o que já foi visto encurtaria a varredura — exatamente o erro que
   o critério das 3 páginas existe para evitar.

### Teste de ponta a ponta, com rede falsa

A cadeia inteira — descobrir → sondar → coletar → intraday → relatório — roda
contra um `http_get` falso e banco isolado, e o teste confere **as linhas
gravadas**: origem carimbada, `close` vindo do `price`, OHLCV preenchido,
volume de 1 min já diferenciado, bid/ask no banco, e recoleta que não duplica.

E o caso que mais importa para o seu requisito: o teste **semeia uma barra do
Yahoo** (fechamento 99,99, OHLCV vazio), roda a coleta da UOL em cima e exige
que o fechamento continue 99,99, que `origem` continue `yahoo`, que o OHLCV
vazio tenha sido preenchido, que `origem_ohlc` diga `uol`, e que a discordância
entre os dois fechamentos apareça no relatório. Depois roda duas vezes para
provar que complementar é idempotente, e uma vez com `--substituir` para provar
que o modo destrutivo existe mas **só quando pedido**.

É o que separa "o código compila" de "a ingestão grava certo".

## O que me impede de seguir agora

A política de rede deste contêiner **nega todos os hosts externos** relevantes.
Testado hoje:

| host | resultado |
|---|---|
| `api.cotacoes.uol.com` | bloqueado |
| `economia.uol.com.br` | bloqueado |
| `www.b3.com.br` | bloqueado |
| `query1.finance.yahoo.com` | bloqueado — **e é a fonte que o projeto já usa** |

Consequências diretas:

- **3.2** não dá para sondar nem provar o mapeamento `price → close`;
- **3.6** não dá para ler o `robots.txt` nem os termos de uso;
- nenhuma coleta é possível daqui.

Feito sem rede, e já no repositório:

1. os **testes que travam as três armadilhas** do 3.2 contra respostas
   gravadas — falham alto se a API mudar, e é assim que devem ser escritos de
   qualquer forma, para rodarem em CI sem depender da UOL estar de pé;
2. o **provider do 3.5** com interface única, origem por barra e o modo
   complementar, pronto para ser ligado quando houver rede;
3. o registro em `config/sources.yml`, os jobs no painel e a migração de
   esquema (`prices.origem_ohlc`, `intraday.bid/ask`).

Falta, e só com rede: **a coleta em si**, a verificação do `price` ajustado
(3.6/armadilha 3) e o `robots.txt`.

---

## Para rodar na sua máquina — a sequência exata

O banco que acompanha este commit já tem o esquema novo e as notícias
reclassificadas, mas **nenhuma barra da UOL**, porque daqui não há rede. Na sua
máquina, em ordem:

```bash
# 0. preencher o OHLCV que falta, da fonte que já funciona, SEM trocar
#    fechamento. Isto é seguro: nenhuma medição já aprovada muda de valor.
python3 -m obs.cli prices --fonte yahoo --range 10y --complementar

# 1-3. a UOL, nos três passos (ou pelos jobs do painel, grupo "uol")
python3 -m obs.cli uol-descobrir                   # catálogo (~1.800 tickers)
python3 -m obs.cli uol-sondar --categorias acao    # data-id + validação
python3 -m obs.cli uol-estado                      # CONFIRA aqui antes de coletar
python3 -m obs.cli uol-coletar --limite 20         # comece pequeno
python3 -m obs.cli uol-coletar                     # depois o resto
```

Duas coisas para **olhar** na saída do `uol-coletar`, porque são as perguntas
que ficaram abertas:

- **"DISCORDÂNCIA COM O QUE JÁ ESTAVA NO BANCO"** — se a diferença **cresce
  para trás** no tempo, as duas fontes usam regras de ajuste por proventos
  diferentes e as séries **não são misturáveis**. Nada foi sobrescrito: o
  relatório existe justamente para você decidir. Se a diferença é ruído de
  centavo, estão compatíveis.
- **"SALTOS > 35% EM UM PREGÃO"** — série provavelmente **não** ajustada.

E no `uol-coletar --intraday --ticker ITUB4`, o aviso
**"bid: CONSTANTE em N barras"**: se aparecer, bid/ask são da sessão e não
servem como spread por minuto. Se não aparecer, são por barra e o spread é
utilizável — é a pergunta que a sondagem deixou aberta e que a primeira coleta
real responde sozinha.
