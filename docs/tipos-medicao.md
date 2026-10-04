# Judicial, legislativo e calendário: quanto acertam?

Você pediu, nestas palavras: *"as estatísticas para leigo do judicial (também
deve julgar se é ruim para o papel), legislativo, calendário contábil, de
quanto acerta na direção. E em outro gráfico quanto afeta a volatilidade. Nas
diferentes granularidades."*

Está medido. **A resposta é que ainda não dá para medir**, e abaixo está o
porquê, com os números na mão — mais dois defeitos que a medição encontrou e
que já foram corrigidos.

Reproduzir: `python3 scripts/tipo_evento_test.py`
(saída completa em `data/tipo_evento_test.log`)

---

## 1. Primeiro, o defeito: o tipo `calendário` estava 100% errado

Antes de qualquer estatística, fui ler os casos um por um. Eram 6 matérias
marcadas `calendário contábil`. **Nenhuma das 6 era evento de calendário:**

| matéria | o que é de verdade |
|---|---|
| Petrobras anuncia descoberta de gás na Colômbia | descoberta de reserva |
| WEG amplia projeto de fábrica de baterias | investimento |
| WEG anuncia plano de R$ 840 milhões | investimento |
| Vale confirma aquisição de participação na Ligga | M&A |
| Itaú conclui venda de operação na Colômbia | M&A |
| Vale passará a divulgar relatório de vendas junto com resultados | **esta sim** |

A causa: a regra casava as expressões **"fato relevante"** e **"comunicado ao
mercado"**. Essas duas não são tipos de evento — são os **nomes do documento**
que a empresa arquiva na CVM, e aparecem no corpo de praticamente qualquer
anúncio corporativo. Resultado: 5 de 6 erradas, e a sexta certa por acidente.

**Nenhuma estatística acharia isso.** Com 6 casos, qualquer número teria margem
de erro de 60 pontos; ler as 6 manchetes levou dois minutos e achou o defeito
inteiro. Fica registrado porque é o argumento de por que a auditoria à mão
roda junto com a medição, e não em vez dela.

Corrigido: a regra agora exige construção que **anuncia data ou agenda**
(`divulgará o balanço em`, `calendário de resultados`, `passará a divulgar`,
`teleconferência de resultados`, `data ex-dividendo`), não o nome do documento.

## 2. Segundo defeito: "congresso" e "senado" quase nunca são o Legislativo

Mesma auditoria, nas 6 matérias `legislativo`. Uma delas era **"Congresso
IBGC: o ser humano na liderança da transformação"** — um congresso de
governança corporativa, marcado como ato legislativo porque a regra casava a
palavra `congresso` solta.

Medido no acervo de 10.001 artigos:

| termo | artigos | o que são |
|---|---|---|
| `congresso` | 53 | 46 são congresso **de área** (87%) |
| `congresso nacional` | 7 | o Legislativo |
| `senado` | 103 | a maioria é **cobertura eleitoral** — "Quem está na frente para senador em Pernambuco?" |

Corrigido: a regra agora exige a casa **agindo** (`Senado aprova`, `Câmara
rejeita`, `Congresso Nacional`), não a casa mencionada. `projeto de lei`,
`PEC`, `medida provisória` e `decreto` continuam valendo como antes.

**Efeito das duas correções** (`python3 -m obs.cli classificar --aplicar`):

| tipo | antes | depois |
|---|---|---|
| calendário | 6 | **1** |
| legislativo | 6 | **3** |
| judicial | 16 | 16 |
| macro | 138 | 138 |
| corporativo | 611 | **619** |

Ou seja: a correção deixou os dois tipos pedidos **ainda menores**. Isso é a
resposta certa — era melhor ter 6 números errados ou 1 número certo?

---

## 3. Agora a estatística — e por que ela não fecha

### O problema não é a estatística, é a aritmética

| tipo | matérias | dá para medir? |
|---|---|---|
| corporativo | 619 | **sim** |
| macro | 138 | no limite |
| judicial | 16 | **não** |
| legislativo | 3 | **não** |
| calendário | 1 | **não** |

E é pior do que parece, porque **16 matérias não são 16 observações**. Duas
matérias do mesmo papel no mesmo dia dividem o mesmo retorno futuro: contá-las
como duas infla a amostra e encolhe a margem de erro artificialmente. Agrupadas
corretamente, as 16 judiciais viram **8 a 11 células** em cada granularidade.
Legislativo e calendário viram **menos de 8**, que é o piso para calcular
qualquer coisa — por isso saem como "não calcula".

### O que 10 casos produzem: números que parecem ótimos e não são

Judicial, **direção**, notícia sobre movimento futuro:

| granularidade | prazo | casos | acertou em 100 | chute |
|---|---|---|---|---|
| 5 minutos | 3 barras | 11 | **88** | 52 |
| 5 minutos | 6 barras | 10 | 71 | 51 |
| 5 minutos | 24 barras | 10 | 43 | 51 |
| 15 minutos | 2 barras | 10 | **29** | 51 |
| 15 minutos | 4 barras | 10 | 29 | 52 |
| 15 minutos | 16 barras | 10 | 43 | 53 |
| 1 hora | 1 barra | 10 | 57 | 51 |
| 1 hora | 5 barras | 9 | 67 | 51 |
| 1 hora | 20 barras | 8 | 40 | 51 |
| 1 dia | 1 pregão | 11 | 62 | 50 |

Aquele **88 em 100** é o número mais bonito que este projeto já produziu. E é
lixo. Repare: o mesmo sinal, nas mesmas notícias, dois cliques de granularidade
ao lado, **acerta 29 em 100**. O número pula **59 pontos** entre medições
vizinhas. O que mudou não foi o mercado — foi quais 10 casos caíram em cada
célula.

Compare com o tipo que tem massa:

| tipo | casos por célula | pulo entre granularidades |
|---|---|---|
| judicial | 8 a 11 | **59 pontos** |
| macro | 15 a 101 | 61 pontos |
| **corporativo** | **42 a 428** | **9 pontos** |

Corporativo, com 42 a 428 casos por célula, varia só 9 pontos — de 46 a 55 em
100. Judicial varia 59. **A diferença entre as duas linhas é o tamanho da
amostra, e nada mais.** É por isso que "acertou 88 em 100" com 11 casos vale
menos que "acertou 51 em 100" com 428.

### Em volatilidade, a mesma coisa

Atenção a uma troca de régua que é fácil de errar: na tabela de volatilidade,
"acertar" significa *o papel ficou entre os 20% que mais se mexeram*. Chutar às
cegas acerta **20 em 100**, não 50. Então 35 em 100 aqui é bom, e 45 em 100 na
tabela de direção é ruim — o mesmo número quer dizer coisas opostas nas duas
tabelas. (Uma primeira versão do script comparava volatilidade com 50 e fazia
resultado razoável parecer péssimo. Corrigido.)

Judicial, **volatilidade**: 50 em 100 numa linha (11 casos), **0 em 100** em
nove das dez linhas restantes. Pulo de 50 pontos. Mesmo diagnóstico.

### O veredito formal

| | direção | volatilidade |
|---|---|---|
| combinações calculadas | 76 | 76 |
| sobrevivem à correção de teste múltiplo (FDR 10%) | **0** | **0** |
| dos tipos pedidos, chegaram a 120 células | **0** | **0** |

Zero em 152. Igual ao resultado da medição de orientação temporal
(`docs/orientacao-medicao.md`), e pela mesma razão.

---

## 4. Quanto falta, em número

Teste de proporção contra 50%, poder de 80%, bilateral:

| para provar uma vantagem de | são necessárias |
|---|---|
| 3 acertos em 100 | 2.178 células |
| 5 acertos em 100 | 783 células |
| 10 acertos em 100 | 194 células |
| 15 acertos em 100 | 85 células |
| 20 acertos em 100 | 47 células |

Com ~10 células por 16 matérias, cada célula custa da ordem de 1,5 matéria
judicial. Para 194 células — o cenário **otimista**, de uma vantagem enorme de
10 pontos — seriam cerca de **300 matérias judiciais**. Há 16.

**Isso é 20 vezes o que existe, e não se resolve refinando a estatística.** O
caminho é o ponto 6: um **radar judicial** com fonte dedicada, em vez de
depender de a imprensa econômica resolver noticiar um processo. Enquanto a
origem for "o que o InfoMoney publicou", 16 é o que se tem.

---

## 5. "Judicial também deve julgar se é ruim para o papel"

Sobre esta parte do seu pedido: **o julgamento existe** — a coluna `s` é o
efeito **no papel**, com sinal, a mesma que o gráfico usa, e as 16 judiciais
têm 5 negativas, 7 neutras e 4 positivas. Não é um tipo "sem direção".

Mas a auditoria mostra que o **sinal aponta para o lado errado** em casos
verificáveis, porque quem está julgando hoje é o léxico:

| matéria | sinal | o certo seria |
|---|---|---|
| "ANP avança para **reduzir concentração** no mercado de gás **apesar da resistência da Petrobras**" | **+0,35 (bom)** | **ruim** — é a Petrobras perdendo poder de mercado |
| "Vale **pode pagar imposto** sobre lucros no exterior? STF zera placar" | **+0,50 (bom)** | **ruim** — é a Vale podendo pagar mais imposto |
| "MPF **aciona** Vale por extravasamento na Mina de Viga e demanda auditoria" | 0,00 (neutro) | **ruim** — é uma ação judicial contra a empresa |
| "Vale **inicia retomada** de operações na Mina de Fábrica **após aval da Justiça**" | 0,00 (neutro) | **bom** — volta a produzir |

O padrão é claro e é a limitação conhecida do léxico: ele lê **"aprova",
"avança", "aval"** como positivos sem perguntar *positivos para quem*. Numa
notícia judicial o agente da frase é o órgão, não a empresa — e aí o verbo
favorável ao órgão costuma ser **adverso ao papel**. É exatamente o caso
ANP/Petrobras que o `parecer.md` já descreveu, e que motivou tornar o LLM o
leitor primário.

**Conclusão honesta:** o defeito de direção judicial é de **leitor**, não de
amostra. Ele se resolve com o LLM lendo (já implementado, `OBS_SCORER=llm`,
precisa de chave), e aí sim vale medir — mas medir precisa das 300 matérias do
ponto 6. São dois problemas independentes e os dois precisam ser resolvidos:
mais dados não consertam o sinal errado, e o sinal certo não dispensa a
amostra.

---

## 6. O que fica registrado como evidência

Seguindo o protocolo de `docs/validacao.md`:

| afirmação | estado |
|---|---|
| o tipo `calendário` tinha 100% de erro (6 de 6) | **medido e reprovado**, corrigido |
| `congresso`/`senado` soltos classificam errado (87% e maioria) | **medido e reprovado**, corrigido |
| judicial/legislativo/calendário preveem direção | **não medível** — 0 de 76 linhas atingem o piso |
| judicial/legislativo/calendário explicam volatilidade | **não medível** — 0 de 76 |
| corporativo é estável entre granularidades (9 pontos, n alto) | **medido**, e serve de régua |
| o sinal judicial aponta para o lado errado em casos verificáveis | **auditado à mão**, 4 de 16; não é estatística |
| o LLM corrigiria esses 4 casos | **hipótese** — não rodou, falta chave |

Nenhuma linha aqui autoriza usar tipo de evento como sinal. O que elas
autorizam é o tipo de evento como **descrição** — que é para o que ele serve no
gráfico, e é o que a legenda diz.
