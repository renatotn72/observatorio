# 89 papéis e o histórico completo pelo chart v8 do Yahoo

Você pediu os dados dos 89 papéis da lista, e destrinchou o endpoint que
resolve isso. Está implementado e testado. **Falta rodar** — a rede deste
contêiner continua bloqueando `query2.finance.yahoo.com`.

Reproduzir os testes: `python3 scripts/test_yahoo.py` (47 verificações, sem rede)

---

## 1. Os comandos, na ordem

```bash
# histórico diário COMPLETO dos 89 papéis — uma requisição por papel.
# period1=0 traz tudo: anterior a 2016, com adjclose e proventos.
python3 -m obs.cli yf-diario

# o que chegou
python3 -m obs.cli yf-estado

# a série está ajustada por proventos? conferido num desdobramento conhecido
python3 -m obs.cli yf-ajuste

# intradiário, deslizando a janela para trás até ela secar.
# do mais grosso ao mais fino: 1h cobre 720 dias por requisição, 1m só 8.
python3 -m obs.cli yf-intraday --intervalos 1h,15m,5m,1m
```

No painel: Central de Operações, grupo "mercado" — *Yahoo: histórico diário
completo* e *Yahoo: intradiário deslizando a janela*. Os dois ficam **fora do
agendamento** de propósito: são backfill, não rotina.

### Quanto custa, medido num ensaio com rede falsa

| coleta | requisições | observação |
|---|---|---|
| diário, 89 papéis | **89** | uma por papel; `period1=0` dispensa paginar |
| 1m, por papel | **5–6** | parou sozinho quando a janela secou (teto era 400) |
| 1h, por papel | 1–2 | 720 dias por requisição cobre quase tudo |

As janelas de 1m param cedo porque **o teto da janela não é o histórico
retido**: 8 dias é quanto *cabe* numa resposta, não quanto o Yahoo *guarda*. O
código desliza até duas janelas consecutivas voltarem vazias e então **relata o
alcance que mediu**, em vez de afirmar um alcance que não conferiu. Quanto de
1m existe de fato, só a primeira coleta real diz.

---

## 2. O que este endpoint dá e nenhuma outra fonte do projeto dava

### `adjclose` — o ajuste deixa de ser inferência

Até aqui `docs/precos-fontes.md` registrava o ajuste da série atual como
**"provável"**, inferido de não haver salto maior que 35% em 10 anos. Agora é
dado: `indicators.adjclose[0].adjclose` vem no mesmo pacote.

Os dois são gravados e **não se misturam**:

| coluna | o que é | para que serve |
|---|---|---|
| `close` | fechamento como negociado | a tela, o que o usuário reconhece |
| `adjclose` | corrigido para trás a cada provento | **calcular retorno** |

Usar `close` para retorno cria uma queda artificial em cada data-ex: o preço cai
o valor do dividendo e a conta registra isso como perda do acionista, que na
verdade recebeu o dinheiro. Pequeno por dia, sistemático em dez anos. Usar
`adjclose` na tela mostra preço que ninguém viu. Guardar só um obriga a escolher
qual dos dois erros cometer.

**A escolha de qual coluna usar é por papel, e é inteira.** `COALESCE(adjclose,
close)` pareceria mais simples e seria um defeito: metade da série ajustada e
metade crua dá um salto na fronteira que não aconteceu no mercado, e nada no
dado denunciaria. Então: papel com `adjclose` em **todas** as barras usa a série
ajustada; falta em uma, a série inteira usa `close`. Está em
`obs/prices.py:serie_usada`, e o teste cobre os dois lados.

**Aviso para comparar medições:** todo número de `docs/metricas.md` foi
calculado sobre `close`, porque `adjclose` não existia no banco. Depois da
coleta, o mesmo teste pode dar outro resultado — e a diferença não é erro de
nenhum dos dois, é mudança da série de entrada. `returns_by_date(con,
ajustado=False)` reproduz o cálculo antigo, e é assim que se mede o tamanho do
efeito em vez de supor.

### `events=div|split` — as datas de provento e desdobramento

Vão para a tabela `proventos`. Isso fecha um buraco que estava aberto desde a
UOL: a **armadilha 3** (`obs/uol.py`) pedia para testar se `price` é ajustado
"num papel com desdobramento conhecido no período" — e não havia de onde tirar
a data do desdobramento. Agora há.

`python3 -m obs.cli yf-ajuste` roda o teste: num desdobramento 2:1, série
ajustada não salta e série crua cai pela metade. O veredito sai por papel, e
vale para qualquer série do banco, inclusive a da UOL.

### `meta.longName` — o nome vem com o preço

Por isso `config/watchlist.yml` **não** tem 89 nomes digitados à mão. Digitar
seria inventar o que a API entrega; o nome entra em `ativos.nome` na coleta.

---

## 3. Por que os 89 papéis não entraram em `tickers:`

Esta é a decisão que mais pode surpreender, então fica explícita.

`tickers:` faz **três** coisas ao mesmo tempo:
1. define quem o matcher procura no texto da notícia;
2. define quem tem preço coletado;
3. define quem compõe a média transversal que serve de benchmark
   (`__crosssec__`).

Jogar os 89 ali trocaria o benchmark de 10 para 89 papéis. Como o retorno
anormal é *retorno menos a média transversal*, **todo retorno anormal do banco
mudaria de valor** — e com ele cada número registrado em `docs/metricas.md`.
Seria uma re-baseline de todas as medições do projeto, disparada por um
download de preço.

Então a lista entrou como `universo:`, que **coleta preço e mais nada**
(`obs/config.py:universo`). A watchlist continua com 10 e o benchmark continua
o mesmo.

**A troca vale a pena, e é sua para decidir.** Uma média de 89 papéis é um proxy
de mercado muito melhor que uma de 10 — menos ruído idiossincrático, menos
chance de a própria notícia mexer no benchmark. Mas trocar exige re-rodar as
medições e registrar o antes e o depois, não deixar acontecer em silêncio. Se
quiser, o caminho é mover os tickers de `universo:` para `tickers:` com
`aliases`, e aí re-rodar `scripts/orientacao_test.py` e
`scripts/tipo_evento_test.py` para o log guardar as duas versões.

### Uma correção na lista recebida

Veio **`SBSPSP3`**, que não existe — são sete caracteres com "SP" repetido. A
Sabesp é **`SBSP3`**, e é ela que está no arquivo.

Dois pares vieram juntos e isso está **certo**, não é duplicata:

| antigo | novo | o que houve |
|---|---|---|
| `ARZZ3` | `AZZA3` | Arezzo virou Azzas na fusão com o Grupo Soma |
| `NTCO3` | `AXIA3` | Natura &Co virou Axia |

O papel antigo guarda o histórico e o novo tem o presente. Quem descartar o
antigo perde série.

E um aviso sobre o que esperar: `AMER3` (Americanas) e `BHIA3` (Casas Bahia)
passaram por recuperação judicial e grupamento; `GOLL4` e `AZUL4` por
reestruturação. Se algum voltar `Not Found`, a coleta **nomeia o papel** no
relatório em vez de omitir — justamente para você conferir se caiu algum papel
bom.

---

## 4. Um defeito meu que o ensaio pegou

`ativos` nasceu com `PRIMARY KEY (ticker)`. Com duas fontes de cadastro — a UOL
pelo `data-id`, o Yahoo pelo símbolo `.SA` — a segunda a sondar **apagaria o id
da primeira**, e a coleta dela passaria a pedir o id errado **sem erro nenhum**:
a linha continua existindo e parecendo válida.

A chave certa é `(ticker, fonte)`. SQLite não troca PRIMARY KEY com `ALTER`, só
recriando a tabela; a migração detecta pelo `PRAGMA` e recria copiando o
conteúdo. E todas as consultas da UOL sobre `ativos` passaram a filtrar por
`fonte` — sem isso, `uol-coletar` pediria à UOL o id `PETR4.SA`.

E um defeito no meu próprio relatório: a primeira versão do resumo de
divergência classificava como *"estável no tempo, misturável"* um papel com
**146% de diferença média**, só porque a diferença não crescia para trás.
Diferença estável de 146% não é arredondamento — é outra série. Agora a
magnitude manda primeiro e a tendência só escolhe entre as causas.

---

## 5. O que ainda bloqueia

| host | resultado hoje |
|---|---|
| `query2.finance.yahoo.com` | **bloqueado** |
| `query1.finance.yahoo.com` | bloqueado |
| `api.cotacoes.uol.com` | bloqueado |
| `economia.uol.com.br` | bloqueado |
| `www.b3.com.br` | bloqueado |

Nenhuma coleta é possível daqui. O código está escrito, testado contra respostas
no formato do esquema, e ensaiado de ponta a ponta com rede falsa sobre uma
cópia do banco real — 89 requisições, 88 papéis, 24.920 fechamentos antigos
intactos, `adjclose` preenchido, proventos gravados, um delistado nomeado no
relatório.
