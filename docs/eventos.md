# Classificação de eventos: duas dimensões independentes

**Desde:** 4 de outubro de 2026
**Código:** `obs/evento.py` · **Teste:** `scripts/test_evento.py`

## O problema

Todo evento era tratado como "notícia que explica o preço", com um campo só —
`event_type`, 12 valores, **44% caindo em `unclassified`**. Duas coisas
faltavam, e elas são ortogonais: juntá-las num campo obriga a escolher entre
"judicial" e "futuro" quando a resposta certa são as duas.

## A) Orientação temporal — a que tempo o CONTEÚDO se refere

| marca | significado |
|---|---|
| ← `passado` | relata fato consumado; deveria explicar movimento **já ocorrido** |
| ● `presente` | fato em curso agora |
| → `futuro` | guidance, projeção, risco prospectivo, processo ainda a decidir |

**É conjunto, não campo único.** Um evento pode ter mais de uma marca.

Sem marca nenhuma o texto recebe `presente`: fato tratado como corrente é o
padrão menos arriscado — não afirma que já aconteceu nem que vai acontecer.

### Caso de teste 4.1 — MPF / bloco FZA-M-59

> "MPF apresenta novo recurso contra exploração de petróleo na Foz do Amazonas
> pela Petrobras (PETR4)" — recurso protocolado no TRF1 na segunda (28) pedindo
> paralisação da perfuração no bloco FZA-M-59, contestando a decisão da Justiça
> Federal do Amapá de quarta (23) que extinguiu a ação civil pública do MPF
> contra União, Ibama e Petrobras.

| | antes | depois |
|---|---|---|
| tipo | `event_type = "operational"` | `tipo_evento = "judicial"` |
| tempo | **não existia** | `orientacao = {passado, futuro}` |

**Por que `operational` estava errado:** nada ali é operação da empresa; é
processo judicial. O padrão legado casava com `produção` e vencia `regulatory`.

**Por que os dois tempos:** a decisão de 23/09 e o protocolo de 28/09 estão
consumados (**passado**); o recurso ainda pode paralisar a perfuração
(**futuro**). Não há `presente` — não há fato em curso, há um já feito e um
por vir.

As regras acertam pelos motivos certos: `apresenta` e `extinguiu` disparam
passado, `recurso` dispara futuro. A manchete sozinha já carrega os dois.

### Limite do corpo: 300 caracteres, escolhido por medição

Orientação temporal mora em oração subordinada — "contestando a decisão de
quarta" está no corpo, não na manchete. Mas corpo longo acumula verbo de todo
tempo e marca tudo como tudo, o que não informa nada.

| limite | 1 marca | 2 marcas | 3 marcas | três % |
|---|---|---|---|---|
| 0 (só manchete) | 691 | 83 | 3 | 0,4% |
| 120 | 490 | 246 | 41 | 5,3% |
| 200 | 421 | 300 | 56 | 7,2% |
| **300** | 359 | **341** | 77 | **9,9%** |
| 450 | 340 | 341 | 96 | 12,4% |
| 600 | 338 | 339 | 100 | 12,9% |

Em 300 os casos de duas marcas — os informativos — chegam ao máximo, e as três
marcas ficam sob 10%. Acima disso só a marcação inútil cresce: duas marcas fica
parado em 341 enquanto três vai de 77 a 100.

O corpo é limpo de HTML antes (`obs/util.py:sem_html`): 73% dos corpos começam
com uma tag `<img>`. Medido: a limpeza muda a orientação de 17 dos 684 corpos
(2%) e recupera 9% de texto real na janela de 600 caracteres que o léxico lê.

## B) Tipo de evento

| tipo | ícone | forma no gráfico | o que é |
|---|---|---|---|
| `corporativo` | ● | triângulo cheio (ou círculo se neutra) | fato da empresa: resultado, provento, M&A, gestão |
| `macro` | ▲ | **triângulo vazado** | sinal macro que chega pela cadeia de afetação |
| `judicial` | § | losango | ação, liminar, recurso, **decisão de agência** |
| `legislativo` | ⚖ | bandeira | projeto de lei, MP, consulta pública, votação |
| `calendario` | 📅 | quadrado com barra | data de divulgação, fato relevante CVM |

A **forma** é geometria, não glifo unicode: em 8px, `§` e `⚖` variam de largura
por fonte e `📅` vira emoji colorido em parte dos sistemas. A legenda desenha a
mesma geometria do marcador — legenda com glifo diferente do gráfico deixa de
ser legenda.

### O triângulo macro aponta pelo efeito NO PAPEL

▲ favorável, ▼ adverso **à empresa**, não ao tom do texto. Alta do petróleo é
favorável a PETR4 (β > 0) e adversa a quem consome combustível (β < 0). O
gráfico usa `s_papel = s × sinal(β)` — a mesma regra que `aggregate.compute`
aplica em `s_eff`, senão gráfico e sinal contariam histórias diferentes sobre
a mesma matéria.

### Órgão como ator, não como fonte

O balde `regulatory` do legado mapeava para `judicial` sem distinguir:

| manchete | tipo | por quê |
|---|---|---|
| "ANP **aprova** delimitação de novas áreas" | judicial | ato administrativo |
| "T4F fecha capital após **CVM aprovar** cancelamento" | judicial | decisão de agência |
| "Petrobras vai ao Governo **contra ANP**" | judicial | disputa contra o órgão |
| "Produção supera marca inédita, **diz ANP**" | **corporativo** | agência é a **fonte do dado** |

`evento._orgao_como_ator` exige ato administrativo perto do nome do órgão, ou
disputa contra ele. Verbo de reporte — "diz", "informa", "divulga", "segundo" —
fica deliberadamente de fora.

## Custo de errar é baixo, de propósito

**Nenhuma das duas dimensões entra no sinal.** Elas descrevem e filtram.
Classificação errada polui a leitura da tela, não a medição — diferente do `s`,
onde errar o lado estraga o resultado.

## Na tela

A legenda é **clicável e filtra**, nas duas dimensões, compondo com o filtro de
direção que já existia. Cada botão traz a contagem sob os outros filtros em
vigor — senão o número ao lado do rótulo mentiria.

Desligar tudo volta para "todos": tela vazia parece defeito.

Filtrar só `futuro` é a leitura de radar: o que ainda pode acontecer.

## Reclassificar o acervo

`score.run` só pontua par que ainda não tem score, então mudar uma regra aqui
não recalcula nada do que já está gravado.

```bash
python3 -m obs.cli classificar              # simula
python3 -m obs.cli classificar --aplicar    # grava
```

Idempotente: a segunda passada reporta 0 alterações. Aplicado em 2026-10-04
sobre os 777 scores do banco — 461 linhas mudaram.

| | antes | depois |
|---|---|---|
| `presente` sozinho | 344 | 68 |
| `futuro,passado` | 41 | **185** |
| `judicial` | 19 | 16 |
| `calendario` | 0 | 6 |
| `legislativo` | 1 | 6 |
