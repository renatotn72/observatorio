# Acerto por orientação temporal, granularidade por granularidade

**Data:** 4 de outubro de 2026
**Script:** `scripts/orientacao_test.py` · **Dados:** `data/orientacao_test.json`
· **Saída:** `data/orientacao_test.log`
**Veredito:** **nada passa.** 1.166 testes, 80 com amostra suficiente, **zero**
sobrevive à correção de teste múltiplo.

---

## Antes das tabelas: um erro meu, encontrado e corrigido

A primeira versão desta medição comparava o acerto com uma taxa-base estimada
**dentro da própria célula**, como `max(p, 1−p)`. Esse estimador é enviesado
para cima, e muito. Medido com moeda honesta (p real = 50%), 20.000 simulações:

| n da célula | base aparente | viés |
|---|---|---|
| 12 | 61,2% | **+11,2** |
| 20 | 58,8% | +8,8 |
| 27 | 57,8% | +7,8 |
| 120 | 53,6% | +3,6 |
| 450 | 51,9% | +1,9 |

Com células de 12 a 27 observações, **qualquer sinal apareceria perdendo da
taxa-base por 8 a 11 pontos, mesmo sendo perfeitamente informativo.** A
conclusão "o sinal acerta menos que o chute", que as 30 linhas de direção
sugeriam na primeira rodada, era artefato do comparador.

Corrigido: a base passou a ser calculada sobre **todas as barras**, não só as
que têm notícia — amostra grande, viés desprezível, e é a pergunta certa:
"chutar sempre o lado mais frequente acerta quanto?". A base real fica em
**~51%**, não nos 55–65% que o estimador enviesado produzia.

Todas as tabelas abaixo já usam a base corrigida.

---

## Como ler as tabelas

- **acerto%** — direção: % de vezes que o lado da notícia bateu com o lado do
  retorno. Volatilidade: % do topo 20% do sinal que virou movimento grande.
- **base%** — direção: chutar sempre o lado mais frequente. Volatilidade: 20%,
  por construção do corte.
- **vantagem** — pontos percentuais acima da base. É o número que importa.
- **leitura** — só vale como resultado a linha com n ≥ 120 **e** p abaixo do
  limiar de FDR. "cai no FDR" = teria p < 0,05 isolado, mas não sobrevive à
  correção pela família de 80 testes.

Orientação é **conjunto**: `futuro,passado` conta nos dois grupos. Os grupos se
sobrepõem de propósito, e por isso os testes **não são independentes**.

---

## 1 MINUTO

**110 células testadas, 0 com n ≥ 120. Nenhuma tem poder.**

### Direção
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p |
|---|---|---|---|---|---|---|---|---|
| passado | passado | 5 | 27 | 45,8 | 50,8 | −5,0 | −0,0608 | 0,132 |
| passado | futuro | 6 | 24 | 62,8 | 51,0 | +11,8 | −0,3007 | 0,053 |
| presente | passado | 9 | 12 | 50,0 | 51,1 | −1,1 | −0,1744 | 0,022 |
| presente | futuro | 10 | 12 | 56,3 | 51,1 | +5,3 | +0,0533 | 0,103 |
| futuro | passado | 12 | 14 | 58,6 | 51,4 | +7,2 | +0,1581 | 0,004 |
| futuro | futuro | 13 | 15 | 53,8 | 51,3 | +2,6 | +0,0629 | 0,059 |

### Volatilidade
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p |
|---|---|---|---|---|---|---|---|---|
| passado | passado | 5 | 27 | 20,0 | 20,7 | −0,7 | −0,0627 | 0,024 |
| passado | futuro | 6 | 24 | 7,1 | 21,1 | −13,9 | +0,0163 | 0,004 |
| presente | passado | 9 | 12 | 0,0 | 22,2 | −22,2 | +0,0285 | 0,175 |
| presente | futuro | 10 | 12 | 0,0 | 21,2 | −21,2 | −0,1105 | 0,067 |
| futuro | passado | 12 | 14 | 0,0 | 20,9 | −20,9 | −0,0932 | 0,241 |
| futuro | futuro | 13 | 15 | 16,7 | 22,7 | −6,1 | +0,0229 | 0,138 |

**Leitura:** nada aqui é interpretável. Com n médio de 12 a 27, um acerto de
62,8% tem intervalo de confiança largo o bastante para conter 50%. Os zeros na
volatilidade são células de 12 observações onde o topo 20% são 2 ou 3 casos.

**Causa:** as barras de 1 minuto cobrem **5 dias** (27/09 a 02/10). Quase
nenhuma notícia do acervo cai nessa janela. Para medir no minuto é preciso
coletar 1m continuamente — o Yahoo só retém 5 dias, então é coleta diária
acumulada, não backfill.

---

## 5 MINUTOS

**276 células testadas, 20 com n ≥ 120.**

### Direção
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 18 | 16 | 54,5 | 52,0 | +2,5 | −0,0924 | 0,086 | descritivo |
| passado | futuro | 18 | 17 | 53,8 | 52,1 | +1,7 | +0,0658 | 0,009 | descritivo |
| presente | passado | 20 | 19 | 46,1 | 51,8 | −5,6 | −0,0271 | 0,004 | cai no FDR |
| presente | futuro | 23 | 17 | 55,2 | 51,9 | +3,3 | −0,0232 | 0,002 | cai no FDR |
| futuro | passado | 29 | 19 | 50,0 | 52,6 | −2,6 | −0,0429 | 0,015 | cai no FDR |
| futuro | futuro | 30 | 20 | 51,0 | 52,6 | −1,6 | +0,0249 | 0,001 | cai no FDR |

### Volatilidade
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 18 | 16 | 3,1 | 21,8 | −18,7 | −0,0220 | 0,011 | descritivo |
| passado | futuro | 18 | 17 | 0,0 | 22,6 | −22,6 | −0,0988 | 0,039 | descritivo |
| presente | passado | 20 | 19 | 16,3 | 22,0 | −5,6 | −0,0484 | 0,018 | cai no FDR |
| presente | futuro | 23 | 17 | 0,0 | 21,9 | −21,9 | −0,1378 | 0,073 | nulo |
| futuro | passado | 29 | 19 | 16,7 | 21,7 | −5,1 | −0,0079 | 0,019 | cai no FDR |
| futuro | futuro | 30 | 20 | 16,7 | 21,4 | −4,8 | −0,0574 | 0,131 | nulo |

**Melhor célula com poder:** direção / futuro / janela futuro, h = 6 barras,
n = 226 — **56,4% contra base de 50,7% (+5,7 p.p.), p = 0,228.** Não passa.

**Leitura:** na direção, a janela futuro bate a passada em presente e futuro.
Na volatilidade, **todas as seis linhas são negativas** — a intensidade da
notícia escolhe barras *menos* voláteis que o acaso, nesta granularidade.

---

## 15 MINUTOS

**274 células testadas, 20 com n ≥ 120.**

### Direção
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 18 | 14 | 50,8 | 52,8 | −2,0 | −0,1135 | 0,079 | descritivo |
| passado | futuro | 20 | 14 | 57,4 | 52,7 | +4,7 | +0,2056 | 0,001 | descritivo |
| presente | passado | 19 | 16 | 55,6 | 52,2 | +3,3 | +0,0000 | 0,073 | nulo |
| presente | futuro | 22 | 16 | 56,4 | 52,9 | +3,6 | −0,0072 | 0,040 | cai no FDR |
| futuro | passado | 29 | 16 | 47,7 | 54,5 | −6,8 | −0,0761 | 0,004 | cai no FDR |
| futuro | futuro | 29 | 17 | 55,6 | 53,5 | +2,1 | +0,0591 | 0,032 | cai no FDR |

### Volatilidade
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 18 | 14 | 5,3 | 22,1 | −16,8 | +0,0549 | 0,013 | descritivo |
| passado | futuro | 20 | 14 | 4,5 | 23,1 | −18,5 | −0,1025 | 0,061 | descritivo |
| presente | passado | 19 | 16 | 16,0 | 21,4 | −5,4 | −0,0709 | 0,013 | cai no FDR |
| presente | futuro | 22 | 16 | 21,1 | 21,4 | −0,3 | +0,0932 | 0,043 | cai no FDR |
| futuro | passado | 29 | 16 | 17,5 | 23,8 | −6,3 | −0,0715 | 0,040 | cai no FDR |
| futuro | futuro | 29 | 17 | 25,0 | 22,2 | +2,8 | +0,0712 | 0,086 | nulo |

**Leitura:** o padrão mais limpo de todas as granularidades. Na direção, a
**janela futuro vence a passada nas três orientações** (+4,7 / +3,6 / +2,1
contra −2,0 / +3,3 / −6,8). Na volatilidade, a janela futuro também melhora em
relação à passada. Nada passa, mas a direção do efeito é a que a hipótese
prevê — ao contrário do que a primeira rodada, com a base enviesada, sugeria.

---

## 1 HORA

**314 células testadas, 28 com n ≥ 120.** É a granularidade com mais poder: as
barras de 1 hora cobrem **dois anos** (out/2024 a out/2026).

### Direção
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 23 | 20 | 54,5 | 50,6 | **+4,0** | −0,0064 | 0,021 | cai no FDR |
| passado | futuro | 22 | 23 | 50,0 | 50,7 | −0,7 | −0,0156 | 0,171 | nulo |
| presente | passado | 23 | 18 | 53,0 | 50,5 | +2,5 | +0,0120 | 0,005 | cai no FDR |
| presente | futuro | 23 | 17 | 54,1 | 50,6 | +3,5 | +0,0142 | 0,040 | cai no FDR |
| futuro | passado | 33 | 21 | 52,6 | 51,1 | +1,5 | +0,0041 | 0,032 | cai no FDR |
| futuro | futuro | 33 | 21 | 50,0 | 51,0 | −1,0 | +0,0367 | 0,032 | cai no FDR |

### Volatilidade
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 23 | 20 | 10,5 | 22,2 | −11,7 | −0,1182 | 0,000 | cai no FDR |
| passado | futuro | 22 | 23 | 19,1 | 22,2 | −3,1 | −0,0518 | 0,046 | cai no FDR |
| presente | passado | 23 | 18 | 12,5 | 21,4 | −8,9 | −0,0339 | 0,060 | nulo |
| presente | futuro | 23 | 17 | 9,1 | 21,7 | −12,6 | −0,0896 | 0,003 | cai no FDR |
| futuro | passado | 33 | 21 | 22,2 | 22,2 | 0,0 | −0,0026 | 0,028 | cai no FDR |
| futuro | futuro | 33 | 21 | 15,4 | 21,4 | −6,0 | −0,0866 | 0,013 | cai no FDR |

**Melhor célula com poder:** direção / futuro / janela passado, h = −20 barras,
n = 140 — **57,7% contra base de 50,5% (+7,2 p.p.), p = 0,302.** Não passa.

**Leitura:** é a única granularidade em que a notícia de **passado** tem a maior
vantagem na janela **passado** (+4,0 contra −0,7 na futura) — exatamente a
hipótese do pedido. Mas o IC correspondente é −0,0064, praticamente zero: a
vantagem vem do acerto de sinal, não de ordenação, e com p de 0,021 que não
sobrevive ao FDR. É um candidato a reexaminar, não um achado.

---

## 1 DIA (pregão)

**192 células testadas, 12 com n ≥ 120.**

### Direção
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 14 | 22 | 51,2 | 50,9 | +0,3 | +0,0851 | 0,006 | cai no FDR |
| passado | futuro | 13 | 27 | 45,8 | 50,9 | −5,1 | +0,0443 | 0,111 | nulo |
| presente | passado | 13 | 19 | 54,5 | 50,8 | +3,7 | +0,0764 | 0,234 | nulo |
| presente | futuro | 13 | 18 | 50,0 | 50,9 | −0,9 | +0,0690 | 0,311 | nulo |
| futuro | passado | 23 | 15 | 50,0 | 50,9 | −0,9 | +0,1013 | 0,076 | nulo |
| futuro | futuro | 20 | 18 | 48,2 | 50,9 | −2,7 | +0,0648 | 0,117 | nulo |

### Volatilidade
| orientação | janela | células | n médio | acerto% | base% | vantagem | IC | menor p | leitura |
|---|---|---|---|---|---|---|---|---|---|
| passado | passado | 14 | 22 | 13,7 | 21,4 | −7,8 | −0,0749 | 0,071 | nulo |
| passado | futuro | 13 | 27 | 33,3 | 20,7 | **+12,6** | +0,1302 | 0,104 | nulo |
| presente | passado | 13 | 19 | 12,5 | 21,1 | −8,6 | +0,0315 | 0,041 | cai no FDR |
| presente | futuro | 13 | 18 | 25,0 | 21,4 | +3,6 | −0,2440 | 0,032 | cai no FDR |
| futuro | passado | 23 | 15 | 20,0 | 22,2 | −2,2 | +0,0277 | 0,010 | cai no FDR |
| futuro | futuro | 20 | 18 | 21,4 | 20,8 | +0,6 | +0,0378 | 0,051 | nulo |

**Melhor célula com poder:** volatilidade / futuro / janela futuro, h = 1 dia,
n = 296 — **23,7% contra base de 20,3% (+3,5 p.p.), p = 0,215.** Não passa.

**Leitura:** é a granularidade onde a **volatilidade** se comporta como a teoria
do projeto espera — as três orientações têm vantagem positiva na janela futuro
(+12,6 / +3,6 / +0,6) e negativa na passada. É o mesmo sentido da cabeça de
agitação, a única aprovada do projeto, que opera justamente em D+1. Com p de
0,104 a 0,215, não passa; mas é a única coincidência entre esta medição e o que
o projeto já tem validado.

Na direção, o diário é o mais fraco: nenhuma vantagem passa de +3,7.

---

## O que se conclui, somando as cinco granularidades

1. **Nada passa.** Zero células sobrevivem ao FDR. Sem correção, 3 de 80 têm
   p < 0,05 — contra 4,0 esperadas por acaso.
2. **A hipótese não se confirma.** A expectativa era que notícia de PASSADO
   explicasse o movimento já ocorrido. Isso só aparece em **1 hora**
   (+4,0 na janela passado contra −0,7 na futura). Em 5 e 15 minutos acontece o
   contrário, e no diário a vantagem some.
3. **O sinal de volatilidade troca de sentido com a granularidade.** Negativo
   no intradiário curto (até −22,6 em 5 min), positivo no diário (até +12,6).
   É a observação mais consistente da página, e a que merece investigação
   própria — mas como são células não independentes, não existe teste de sinal
   válido sobre elas.
4. **O minuto não é mensurável** com este acervo: 5 dias de barras.
5. **Por papel, nenhuma granularidade produz célula com n ≥ 120.** A leitura
   por papel individual não existe aqui.

Em acerto, pela conversão que o projeto usa (`P = 0,5 + arcsin(IC)/π`), o melhor
IC da tabela inteira — +0,2056, numa célula descritiva de 15 minutos com n = 14
— valeria 56,6 em 100. Entre as células **com poder**, o melhor IC é +0,1013,
que vale **53,2 em 100**. E não passa.

---

## O que protege esta medição

1. **Células disjuntas**: várias matérias do mesmo papel na mesma barra viram
   uma observação. Sem isso, 752 eventos virariam 108 células contadas como 752.
2. **Janelas não sobrepostas** para h > 1 (passo `|h|`). Esse erro já derrubou
   três resultados neste projeto.
3. **Permutação** com 2.000 embaralhamentos.
4. **Benjamini-Hochberg** (q = 0,10) sobre a família inteira de 80 testes.
5. **Piso de 120 células**; abaixo disso a linha é descritiva.
6. **IC95 de Wilson**, não normal simples.
7. **Base direcional estimada fora da célula** — a correção descrita no topo.

### Uma suspeita testada e descartada
A célula usa a **média** da intensidade. Média regride quando há muitas
matérias, e dia de muita notícia tende a ser volátil — o que criaria correlação
negativa espúria. Refeito com **soma**: 30 de 40 células negativas, contra 31 de
40 com média. O agregador não explica o sinal.

---

## Como reproduzir

```bash
python3 scripts/orientacao_test.py                 # as cinco granularidades
python3 scripts/orientacao_test.py --gran 1m       # uma só
python3 scripts/orientacao_test.py --papel PETR4
python3 scripts/orientacao_test.py --json          # grava o JSON
```

Ordem de saída: 1 minuto, 5 minutos, 15 minutos, 1 hora, 1 dia.
