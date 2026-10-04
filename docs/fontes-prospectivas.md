# Ponto 6 — Radar prospectivo: avaliação e recomendação

**Data:** 4 de outubro de 2026
**Estado:** avaliação. **Nada foi implementado**, conforme pedido.

---

## Aviso sobre o que foi e o que não foi medido

A sonda `scripts/sondar_fontes.py` foi escrita e executada, mas **a política de
rede deste contêiner nega todos os hosts `.gov.br` e `.jus.br`** — inclusive
`dados.cvm.gov.br`, que o projeto já usa em produção. Todas as 15 fontes
voltaram `HTTP 000 / Tunnel connection failed: 403`.

Portanto, nesta página:

- **Verificado** (leitura de código e do banco): tudo da seção 6.3 e as
  observações sobre o encaixe na máquina atual.
- **Avaliação** (análise de arquitetura e documentação pública das fontes):
  as recomendações de 6.1 e 6.2. **Não há número de latência medido aqui**, e
  os que aparecem estão marcados como estimativa.

Para obter os números reais, rode onde os hosts respondem:

```bash
python3 scripts/sondar_fontes.py            # todas
python3 scripts/sondar_fontes.py judicial   # um grupo
python3 scripts/sondar_fontes.py --json     # grava data/sonda_fontes.json
```

A coluna `+novo` é a leitura que decide: idade do registro mais novo que a
consulta devolveu. `0d`/`1d` é radar; `30d` é arquivo.

---

## 6.3 Calendário contábil — **já existe; falta a última milha**

O pedido manda verificar o código antes de escrever coisa nova. Verificado:

| o que | onde | estado |
|---|---|---|
| CSV anual do IPE da CVM, todos os documentos de todas as companhias | `obs/cvm_ipe.py:IPE_URL` | **integrado** |
| categoria "Fato Relevante" | `cvm_ipe.CATEGORIAS_ALVO` | **mapeada** |
| categoria "Comunicado ao Mercado" | idem | **mapeada** |
| categoria "Calendário de Eventos Corporativos" | idem | **mapeada** |
| data real de divulgação (protocolo na CVM) | `contabil.calendario()` → `dt_refer` | **existe** |
| `/api/chart` devolve `divulgacoes` | `obs/api.py` | **já devolve** |
| o gráfico desenhar essas datas | `web/acao.html` | **não usa** |

**Conclusão: 6.3 não precisa de fonte nova.** O dado é coletado, é canônico
(protocolo na CVM, não estimativa) e já trafega na API. `web/acao.html`
simplesmente ignora o campo `divulgacoes` — zero referência a ele no arquivo.

Com a taxonomia do ponto 4 isso vira direto: um evento de tipo
`calendario`, orientação `futuro` quando a data ainda não chegou e `passado`
depois. A forma já está desenhada (`evento.ICONES[CALENDARIO]`, forma
`calendario`).

Pendência separada: `contabil-sync` nunca rodou neste banco (não existe tabela
`fundamentos_cvm`), então `calendario()` hoje devolveria lista vazia. São 144
documentos em `report_documents`, mas nenhum fundamento estruturado.

**Esforço: baixo.** É ligar um campo que já existe à tela.

---

## 6.2 Radar legislativo — **viável, e é onde o valor do pedido se realiza**

O pedido é explícito sobre o porquê: *"esses eventos devem aparecer no gráfico
ANTES da notícia que os cobre"*. Entre as fontes citadas, duas são APIs
abertas de verdade e as outras não são.

| fonte | o que responde | sem login? | avaliação |
|---|---|---|---|
| **Câmara, Dados Abertos v2** | JSON, `/proposicoes` com `dataApresentacao`, `/eventos` com a agenda | **sim, sem chave** | **a melhor fonte do ponto 6.** Documentada, estável, paginada |
| **Senado, Dados Abertos** | XML, matérias por ano | **sim, sem chave** | boa; o XML dá mais trabalho que o JSON da Câmara |
| ANEEL / ANATEL via CKAN | catálogo de *datasets* | sim | **não serve ao radar**: entrega conjuntos de dados, não eventos datados |
| ANP, consultas e audiências | página HTML institucional | sim | exige scraping de HTML do gov.br — frágil, e é o que o projeto evitou em `obs/ri.py` |
| CADE, pauta de julgamento | página HTML | sim | mesma objeção |

**Recomendação 6.2:** começar por **Câmara**, e só depois Senado. Deixar
ANP/ANEEL/ANATEL/CADE de fora por enquanto — são HTML institucional, e o
projeto já tem a lição registrada: o crawler de RI descobria 7 "documentos"
para PETR4 e baixava zero, porque os sete eram páginas HTML
(`obs/cvm_ipe.py`, docstring).

### O problema de desenho que precisa ser resolvido ANTES do código

Três coisas na máquina atual não acomodam evento oficial, e descobrir isso
depois custa caro:

1. **Peso.** `aggregate.source_weight` pesa por domínio de veículo, com
   `default_weight 0.35`. Um projeto de lei protocolado na Câmara entraria
   pesando como jornal de peso médio. Ato oficial não é matéria de jornal: ou
   ganha faixa própria de peso, ou distorce o `z`.
2. **Dedupe não resolve o encontro.** O objetivo é o evento aparecer *antes* da
   notícia que o cobre. Mas `dedupe.cluster()` agrupa por SimHash de texto, e o
   texto de um PL não se parece com o texto da reportagem sobre o PL — eles
   **não vão clusterizar**. Sem um elo explícito (número do PL citado na
   matéria, por exemplo), o mesmo fato entra duas vezes e o painel conta
   evidência em dobro. Isto é exatamente o erro que `novelty` existe para
   evitar, numa forma que `novelty` não pega.
3. **`config/sources.yml` só conhece RSS.** O arquivo tem lista de feeds e
   pesos por domínio. Fonte que não é feed precisa de seção própria, com o
   campo de peso do item 1.

**Esforço: médio**, e a maior parte não é a coleta — é o item 2.

---

## 6.1 Radar judicial — **viável em parte, e não pela via esperada**

Esta é a avaliação que mais muda em relação ao que o pedido sugere.

| fonte | o que responde | sem login? | avaliação |
|---|---|---|---|
| **DataJud / CNJ** | metadados processuais nacionais, Elasticsearch | exige **APIKey pública** do CNJ no header | estruturado e oficial, **mas ver a ressalva abaixo** |
| Consulta processual TRF1 / STJ / STF | páginas de consulta | **não**: sessão e captcha | **desaconselhado**. É o "scraping frágil" que o pedido manda evitar |
| **RSS institucional (MPF, STF, STJ)** | notícias do próprio órgão | sim | **a via realista do radar judicial** |
| DOU / in.gov.br | atos oficiais da União | sim, mas JSON embutido em HTML | serve mais a 6.2 (regulatório) que a 6.1 |
| Querido Diário | diários **municipais** | sim | escopo errado para empresas da B3 |

### A ressalva que decide o DataJud

O DataJud é forte para **acompanhar um processo cujo número você já tem**, e
fraco para a pergunta que o radar faz, que é **"quem está sendo processado
hoje"**. O índice público trabalha com metadados processuais — classe, assunto,
movimentos, órgão julgador — e não expõe de forma confiável o nome das partes.
Sem parte, não há como filtrar por empresa da watchlist.

Some-se a isso que a alimentação é feita pelos tribunais em lote, o que torna a
latência o ponto fraco justamente onde o radar precisa ser forte. **Essa
latência não foi medida aqui** — é a primeira coisa que `sondar_fontes.py`
deve responder quando rodar com rede.

**Recomendação 6.1, em duas etapas:**

1. **Agora: RSS institucional** (MPF, STF, STJ). Publica no mesmo dia, é
   público, não tem captcha e entra na máquina de ingestão que já existe — é
   feed, igual aos 24 que o projeto já lê. Com o ponto 4 já entregue, a matéria
   do MPF cai sozinha em `tipo_evento = judicial`, e o caso FZA-M-59 mostra que
   a orientação temporal sai certa. **Cobertura menor, latência boa, custo
   quase zero.**
2. **Depois, e só se a etapa 1 mostrar valor: DataJud**, começando pelos
   processos cujo número a etapa 1 revelar. Aí a pergunta vira "o que mudou no
   processo X", que é a pergunta que o DataJud responde bem.

**Esforço: etapa 1 baixo** (é RSS); **etapa 2 alto**, e condicionado.

---

## Recomendação consolidada, em ordem

| # | ação | grupo | esforço | por quê |
|---|---|---|---|---|
| 1 | desenhar `divulgacoes` no gráfico como evento `calendario` | 6.3 | baixo | o dado já está coletado e já trafega na API; é a única pendência de tela |
| 2 | rodar `contabil-sync` e popular o calendário | 6.3 | baixo | sem isso o item 1 desenha uma lista vazia |
| 3 | RSS institucional MPF / STF / STJ | 6.1 | baixo | entra na máquina que já existe; o ponto 4 já classifica |
| 4 | Câmara, Dados Abertos v2 | 6.2 | médio | a fonte que realmente entrega "ver a iniciativa quando nasce" |
| 5 | resolver peso e elo evento↔notícia | 6.2 | médio | **pré-requisito do item 4**, não sequência dele |
| 6 | Senado, Dados Abertos | 6.2 | médio | mesma máquina do item 4, depois dele |
| 7 | DataJud / CNJ | 6.1 | alto | só depois que o item 3 mostrar que há valor, e com número de processo em mãos |
| — | ANP / ANEEL / ANATEL / CADE por HTML | 6.2 | — | **não recomendado agora**: scraping institucional frágil |

### O que medir antes de adotar qualquer uma

Rode `scripts/sondar_fontes.py` e exija de cada fonte:

- responde 200 sem login;
- `+novo` de 0 a 2 dias — acima disso é arquivo, não radar;
- volume por consulta compatível com dedupe;
- e, depois de coletar, a pergunta que o projeto sempre faz: **o evento oficial
  antecede de fato a notícia que o cobre?** Isso se mede comparando
  `published_ts` do evento com o da primeira matéria do mesmo assunto. Se não
  anteceder, a fonte não é radar — é redundância cara.

### Requisitos que valem para toda fonte nova

Do próprio pedido, e todos já têm lugar na máquina atual:

- **ingestão idempotente**: `articles.url` é `UNIQUE` e a inserção é
  `INSERT OR IGNORE` — sai de graça, **desde que cada evento tenha URL
  estável**. Evento sem URL própria precisa de chave sintética;
- **dedupe contra o que já existe**: `dedupe.cluster()` cobre texto parecido,
  mas **não** cobre o caso evento↔notícia (item 5 acima);
- **registro em `config/sources.yml`**: hoje o arquivo só modela RSS; precisa
  de seção para fonte estruturada, com peso próprio.
