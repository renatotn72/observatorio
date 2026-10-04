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
| OHLCV | **não tem** (só close) | **tem**, no interday | **UOL** |
| universo | 10 papéis na watchlist | **~1.800 tickers** catalogados | **UOL** |

**Conclusão que muda o plano:** a UOL **não é fonte de backfill** — ela é mais
curta que o que você já tem em todas as granularidades. Ela vale por duas
outras coisas:

1. **Largura**: ~1.800 papéis contra os 10 de hoje. É o que destrava o universo
   de 150–300 ações que `docs/universo.md` pede desde o início.
2. **OHLCV**: o banco guarda só o fechamento. Máxima, mínima, abertura e volume
   não existem hoje em granularidade nenhuma — e volume é insumo de liquidez,
   que é o filtro que `docs/universo.md` diz faltar.

Então a ordem que você propôs continua certa, mas o **objetivo** muda: não é
"backfill além de 5 anos", é "largura e OHLCV". O backfill longo continua sendo
o problema do pré-2016, e para isso o candidato é a B3, não a UOL.

---

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

O que **dá** para fazer sem rede, e que respeita sua ordem de execução:

1. escrever os **testes que travam as três armadilhas** do 3.2 contra respostas
   gravadas — eles falham alto se a API mudar, e é assim que devem ser escritos
   de qualquer forma, para rodarem em CI sem depender da UOL estar de pé;
2. escrever o **provider do 3.5** com a interface única, a coluna de origem e a
   migração de OHLCV, deixando a implementação da UOL pronta para ser ligada
   quando houver rede;
3. apagar as barras congeladas do SUZB3 e pôr a guarda contra série constante.

Diga qual desses você quer primeiro — ou libere a rede, e aí a ordem que você
escreveu roda inteira.
