# Orientação temporal x retorno: a notícia explica o passado ou o futuro?

**Data:** 4 de outubro de 2026
**Script:** `scripts/orientacao_test.py` · **Dados:** `data/orientacao_test.json`
**Veredito:** **nada passa.** 1.166 testes, 80 com amostra suficiente, **zero**
sobrevive à correção de teste múltiplo.

---

## 1. A pergunta, e como ela foi operacionalizada

Duas metades, medidas em separado:

1. Notícia marcada **PASSADO** deveria explicar movimento **já ocorrido**. Se
   ela também "prevê" o futuro, ou o rótulo está errado ou há vazamento.
2. Notícia marcada **PRESENTE** ou **FUTURO** é a candidata a prever.

Para cada combinação mediu-se a associação entre a força da notícia e o retorno
residual acumulado **para trás** (janela passado) e **para frente** (janela
futuro), em quatro granularidades, dez papéis mais o agregado, e dois alvos.

| | preditor | alvo |
|---|---|---|
| **Direção** | força **com sinal**: `s_papel × magnitude` | retorno residual acumulado, com sinal |
| **Volatilidade** | intensidade **sem sinal**: `\|s\| × magnitude × peso` | `\|retorno residual acumulado\|` |

São perguntas diferentes e um resultado não autoriza o outro.

**Orientação é conjunto, não balde.** `futuro,passado` conta nos dois grupos —
tratar como categorias exclusivas descartaria justamente o caso que motivou a
classificação. Logo os grupos se sobrepõem, e os testes **não são
independentes** entre si.

---

## 2. O resultado, em uma tabela

Células com n ≥ 120 (o piso do projeto). `acerto-base` é em pontos percentuais
acima da taxa-base; negativo significa que acerta **menos** que o chute
informado.

| alvo | orientação | janela | células | IC mediano | acerto−base | menor p | leitura |
|---|---|---|---|---|---|---|---|
| direção | passado | passado | 3 | −0,0064 | −5,9 | 0,149 | nada |
| direção | passado | futuro | 3 | +0,0006 | +0,0 | 0,171 | nada |
| direção | presente | passado | 7 | +0,0100 | −2,5 | 0,234 | nada |
| direção | presente | futuro | 7 | +0,0318 | +1,1 | 0,421 | nada |
| direção | futuro | passado | 10 | −0,0150 | −3,5 | 0,051 | nada |
| direção | futuro | futuro | 10 | **+0,0451** | +0,3 | 0,121 | nada |
| volatilidade | passado | passado | 3 | −0,1029 | −4,2 | 0,120 | nada |
| volatilidade | passado | futuro | 3 | −0,0443 | +2,1 | 0,112 | nada |
| volatilidade | presente | passado | 7 | −0,0661 | −4,2 | 0,018 | nada após FDR |
| volatilidade | presente | futuro | 7 | −0,1036 | −7,5 | 0,073 | nada |
| volatilidade | futuro | passado | 10 | −0,0680 | −3,4 | 0,038 | nada após FDR |
| volatilidade | futuro | futuro | 10 | −0,0355 | −3,9 | 0,046 | nada após FDR |

**Sem correção**, 3 das 80 células têm p < 0,05. **Esperadas por acaso a 5%:
4,0.** O número bruto de "significativos" está *abaixo* do que o acaso produz.

---

## 3. A hipótese do pedido não se confirma — e falha na direção contrária

A expectativa era: notícia de PASSADO explica o movimento passado.
**O que os dados mostram é o oposto do esperado, em todas as três orientações:**

| orientação | IC na janela passado | IC na janela futuro |
|---|---|---|
| passado | −0,0064 | +0,0006 |
| presente | +0,0100 | +0,0318 |
| futuro | −0,0150 | **+0,0451** |

A janela **futuro** tem IC maior que a janela **passado** nas três, e a janela
passado é **negativa** em duas. Ou seja: a notícia marcada como relato de fato
consumado não acompanha o movimento que já houve.

Há uma ordenação coerente com a hipótese na janela futuro —
`futuro (+0,045) > presente (+0,032) > passado (+0,001)` — exatamente a ordem
que a teoria prevê. **Isso não é evidência.** Com 3 a 10 células por linha e p
entre 0,12 e 0,42, essa ordenação é perfeitamente compatível com ruído. Está
registrada como coisa a reexaminar quando houver amostra, não como achado.

### Quanto isso valeria em acerto, se fosse real

Pela conversão que o projeto já usa, `P = 0,5 + arcsin(IC)/π`:

| IC | acertos em 100 |
|---|---|
| +0,0451 (melhor célula direcional) | **51,4** |
| +0,0711 (melhor célula de volatilidade diária) | 52,3 |
| 0,588 (necessário para 70 em 100) | 70,0 |

Mesmo tomando o melhor número da tabela como se fosse verdadeiro, ele vale
**1,4 ponto percentual acima do cara ou coroa** — e não sobrevive ao teste.

---

## 4. Por papel: **não é mensurável com este acervo**

**Nenhum papel individual alcançou n ≥ 120 em célula nenhuma.** O maior acervo
é o da PETR4, com 229 notícias classificadas, que depois de agregar por barra e
separar por orientação e horizonte produz células de 8 a 66 observações.

Exemplo real (PETR4, diário, direção):

| orientação | janela | h | n | IC | p | acerto% | base% | IC95 do acerto |
|---|---|---|---|---|---|---|---|---|
| passado | passado | −1 | 48 | +0,2187 | 0,130 | 60,5 | 58,1 | [45,6 – 73,6] |
| passado | futuro | +1 | 47 | +0,1292 | 0,388 | 61,9 | 59,5 | [46,8 – 75,0] |
| futuro | futuro | +1 | 65 | +0,1365 | 0,274 | 59,3 | 55,6 | [46,0 – 71,3] |

Os IC95 têm 25 a 30 pontos de largura e **todos contêm a taxa-base**. Um
intervalo assim não distingue 50% de 70%: a medição não tem poder para
responder a pergunta por papel.

Papéis como ABEV3 (14 notícias no total) não chegam a produzir célula.

---

## 5. Por granularidade

Mediana do IC nas células com n ≥ 120, e quantas são positivas.

### Direção

| granularidade | janela passado | janela futuro |
|---|---|---|
| 5 min | −0,0899 (0/5 positivas) | +0,0382 (4/5) |
| 15 min | −0,0397 (2/5) | +0,0468 (5/5) |
| 1 hora | +0,0150 (5/7) | +0,0113 (5/7) |
| diário | +0,0926 (3/3) | +0,0443 (2/3) |

A janela futuro é positiva nas **quatro** granularidades. A janela passado
alterna de sinal. Nada significativo.

### Volatilidade

| granularidade | janela passado | janela futuro |
|---|---|---|
| 5 min | −0,0730 (0/5) | −0,1036 (0/5) |
| 15 min | −0,0650 (0/5) | +0,0123 (4/5) |
| 1 hora | −0,0661 (1/7) | −0,1038 (0/7) |
| diário | −0,0750 (1/3) | **+0,0711 (3/3)** |

**O sinal depende da granularidade**, e isso é a observação mais interessante
da página. No **diário**, intensidade de notícia anda **junto** com o tamanho
do movimento seguinte — a direção que a cabeça de agitação, a única aprovada do
projeto, prevê. No **intradiário**, anda contra.

Nenhum dos dois passa (o melhor p diário é 0,215). Mas o diário ser o único com
sinal positivo nas três orientações é coerente com o que o projeto já mediu em
D+1, e merece investigação própria.

### Uma suspeita minha, testada e descartada

A célula usa a **média** da intensidade das matérias daquela barra. Média
regride quando há muitas matérias, e dia de muita notícia tende a ser dia
volátil — o que criaria correlação negativa espúria.

Refeito com **soma** em vez de média: **30 de 40 células negativas, contra 31
de 40 com média.** A escolha do agregador não explica o sinal. Fica registrado
para ninguém repetir o teste.

### O que não dá para concluir do padrão de sinais

É tentador olhar "31 de 40 negativas" e tratar como resultado. **Não é.** As
células compartilham as mesmas notícias, as orientações se sobrepõem por
construção, as janelas de horizontes diferentes se cruzam e as granularidades
são aninhadas. Não existe teste de sinal válido sobre células assim. O que
testaria: um alvo só, uma granularidade só, janelas disjuntas, e permutação.

---

## 6. O que protege esta medição de se enganar

1. **Células disjuntas.** Várias matérias do mesmo papel na mesma barra viram
   uma observação. Sem isso, 752 eventos virariam 108 células contadas como
   752 — o n infla e o p encolhe pela raiz disso.
2. **Janelas não sobrepostas** para h > 1: as células são amostradas com passo
   `|h|`. **Esse erro já derrubou três resultados neste projeto**, o último um
   "passou" em D+20 que virou pó com datas disjuntas.
3. **Permutação** com 2.000 embaralhamentos, não p de tabela.
4. **Benjamini-Hochberg** (q = 0,10) sobre a família inteira de 80 testes, não
   por tabela. Sem FDR esta página seria uma máquina de fabricar descoberta.
5. **Piso de amostra** de 120 células. Abaixo disso a linha sai marcada como
   descritiva e não entra na contagem.
6. **IC95 de Wilson** no acerto, não normal simples — com n pequeno o intervalo
   normal sai fora de [0,1] e mente.

---

## 7. Por que o resultado é este: a amostra

A restrição não é o método, é o acervo.

| | |
|---|---|
| notícias classificadas | 777 pares (artigo, papel) |
| células (papel, dia de pregão com notícia) | 354 |
| concentração | **374 dos 777 scores são de setembro de 2026** |
| meses anteriores | 4 a 7 scores por mês, de dezembro a maio |
| papéis com acervo utilizável | PETR4 (229) e B3SA3 (145); os outros, dezenas |

Barras disponíveis: 1 min cobre 5 dias, 5 e 15 min cobrem um mês, 1 hora cobre
dois anos, diário cobre dez anos. A notícia é que não cobre.

---

## 8. O que mudaria a resposta

1. **Acumular notícia.** O gargalo é amostra, não método. Com a cadência atual
   (~370/mês no melhor mês), um ano de coleta contínua levaria as células por
   papel ao piso de 120.
2. **`backfill-rss`**, que pagina histórico sem depender do GDELT, para
   recuperar os meses de dezembro a maio.
3. **Reduzir o número de hipóteses.** 1.166 testes para 80 células utilizáveis
   é o desenho errado: testar menos coisas com mais dados responde mais que
   testar tudo com pouco. A ordenação da seção 3 indica onde olhar primeiro —
   janela futuro, alvo direção, agregado.
4. **Separar o alvo de volatilidade diária**, que é o único com sinal positivo
   coerente nas três orientações e com o que o projeto já aprovou.

Até lá, o estado correto da hipótese é **não medida** — e, pelo que há, **sem
indício de que a orientação temporal separe o que explica o passado do que
prevê o futuro**.

---

## Como reproduzir

```bash
python3 scripts/orientacao_test.py             # tudo (~10 min)
python3 scripts/orientacao_test.py --gran 1h
python3 scripts/orientacao_test.py --papel PETR4
python3 scripts/orientacao_test.py --json      # grava data/orientacao_test.json
```
