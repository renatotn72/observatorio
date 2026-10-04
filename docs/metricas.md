# Métricas e interpretação

## Medição completa — 2026-10-02

`scripts/metrica_total.py` e `scripts/metrica_reduzida.py`.
Amostra: 24.500 pares (papel, dia), 2016-12-02 a 2026-10-02, taxa-base 19,7%.

### Unitária — cada feature sozinha, fora da amostra

| feature | AUC | skill |
|---|---|---|
| vol 20 pregões | 0,5851 | +0,0204 |
| vol 5 pregões | 0,5762 | +0,0181 |
| \|ret\| hoje | 0,5428 | +0,0108 |
| vol do painel macro | 0,5272 | +0,0021 |
| **Payroll EUA no dia-alvo** | **0,4614** | **−0,0003** |

### Integrada — deixa-uma-de-fora

| retirada | AUC | Δ |
|---|---|---|
| vol 20 pregões | 0,5821 | **−0,0081** |
| \|ret\| hoje | 0,5885 | −0,0017 |
| vol do painel macro | 0,5888 | −0,0014 |
| vol 5 pregões | 0,5902 | 0,0000 |
| Payroll | 0,5912 | **+0,0011** |

### Subconjuntos

| modelo | AUC | precisão topo 5% (IC95) |
|---|---|---|
| todas as 5 | 0,5902 | 38,0 [35,1–41,0] |
| sem Payroll (4) | 0,5912 | 38,3 [35,4–41,3] |
| **sem Payroll nem vol-5 (3)** | **0,5913** | **38,8 [35,8–41,8]** |
| vol-20 + \|ret\| (2) | 0,5911 | 37,7 [34,8–40,7] |
| só vol-20 (1) | 0,5851 | 35,5 [32,6–38,4] |

Conclusão: **três features entregam o mesmo que cinco.** Payroll e vol-5 não
acrescentam nada mensurável. As diferenças entre 3, 4 e 5 ficam dentro do
ruído; o que está fora do ruído é que todos os intervalos excluem a taxa-base
de 19,7.

### Confiabilidade — o número exibido é honesto?

`scripts/confiabilidade.py`, 20.420 fora da amostra. Ordenação monotônica do
decil 1 ao 10 (14,6 → 34,7), que é o que valida o ranking.

**Mas há viés sistemático de otimismo: todos os dez decis realizam ABAIXO do
previsto**, entre −0,7 e −3,3 pontos. ECE 1,81 pontos; em 4 dos 10 decis o
valor previsto cai fora do IC95 do realizado. O painel mostra ~2 pontos a
mais do que acontece. Corrigível com reajuste de intercepto.

### Operacional — acertos em 100

| quando o sistema aponta | acertos/100 | vs base |
|---|---|---|
| os 5% mais agitados | **38,0** | 1,92× |
| os 10% mais agitados | 34,7 | 1,75× |
| os 20% mais agitados | 29,7 | 1,50× |
| os 20% mais calmos | 15,0 | 0,76× |

### Direção — taxas-base (K_SIGMA 0,5; 24.830 pares)

alta 25,8 · neutro 47,4 · queda 26,9 → chutar a classe maior acerta 47,4 em 100.

### Direção — CALIBRADA E TESTADA no canal de drivers (2026-10-02)

`scripts/direcao_test.py` e `scripts/direcao_horizonte.py`. Contornou a falta
de notícia usando os 10 anos de drivers: betas reestimados a cada 21 pregões
com `fit_exposures(asof=T)`, que só lê `d < T`; sinal de T prevê B3 em T+1;
calibração walk-forward em 5 dobras.

**Maquinário validado antes de confiar no resultado:**

| controle | AUC | skill |
|---|---|---|
| oráculo (alvo como sinal) | **1,0000** | +1,0000 |
| ruído puro | 0,5054 | −0,0000 |
| **sinal de drivers** | **0,5043** | −0,0001 |

O sinal real é indistinguível de ruído. Ele não é degenerado (dp 0,0076,
nenhum zero) — apenas não carrega direção.

| h | cabeça | n_oos | base | AUC | skill | prec@10% |
|---|---|---|---|---|---|---|
| 1 | alta | 15.720 | 25,8 | 0,4948 | −0,0002 | 23,9 |
| 1 | queda | 15.720 | 26,9 | 0,5043 | −0,0001 | 26,0 |
| 5 | alta | 15.690 | 27,4 | 0,4962 | +0,0004 | 28,1 |
| 5 | queda | 15.690 | 27,7 | 0,5072 | +0,0002 | 29,6 |
| 20 | alta | 15.610 | 29,0 | 0,4941 | 0,0000 | 26,2 |
| 20 | queda | 15.610 | 28,7 | 0,5256 | +0,0001 | 31,9 |

A última linha "passou" — e era artefato de sobreposição: janelas de 20 dias
dividem dados com 19 vizinhas. Refeito com datas disjuntas (n=780):
prec 34,6 com **IC95 [25,0 – 45,7], que inclui a taxa-base de 30,5**.
REPROVADO. Terceira vez que esse mesmo erro aparece no projeto.

**Veredito: 0 de 6. A direção não é previsível pelo canal de drivers.**

O canal de NOTÍCIA segue não medido (0 rótulos). Com IC de 0,09, a conversão
`P = 0,5 + arcsin(IC)/π` daria **52,9 em 100**; para 70 seria preciso IC 0,588
— 6,5× o medido.

## IC — Information Coefficient

Correlação entre o ranking do sinal e o alvo realizado.

- IC positivo: maior sinal tende a corresponder a maior alvo.
- IC negativo: pode representar reversão; o sinal ainda pode ser útil se a direção for tratada corretamente.
- IC não é retorno, nem taxa de acerto.

## AUC

Probabilidade de o modelo ordenar um caso positivo acima de um negativo.

- AUC = 0,50: sem capacidade de ordenação.
- AUC não equivale a “percentual de acerto”.
- Em classes desbalanceadas, acurácia simples pode ser enganosa.

## Brier score e Brier skill

Medem se a probabilidade anunciada corresponde à frequência observada.

- Probabilidade só é exibível se superar uma taxa-base apropriada.
- Um AUC aceitável sem Brier skill suficiente não autoriza exibir “82% de chance”.

## Acertos em 100

Usar apenas para uma definição fechada de direção e conjunto de decisões.

No histórico de referência:
- direção antes da cadeia: 50,8 em 100;
- direção com exposição cambial: 52,6 em 100.

Esses números não representam retorno líquido, pois custo, spread, impacto e janela de execução podem consumir a vantagem.

## Léxico x LLM — medição pendente, e a que foi retirada (2026-10-04)

O leitor padrão da notícia passou a ser o LLM. **O ganho não foi medido**, e a
medição que existia não serve para a pergunta.

### A que foi retirada de circulação

`data/ouro_llm.log`, 115 casos de conjunto-ouro:

| leitor | acertos | em 100 |
|---|---|---|
| léxico | 101 | 87,8 |
| LLM | 62 | 53,9 |

Gabarito **circular**. Medido sobre os mesmos 115 casos:

| fatia | n | léxico |
|---|---|---|
| regra "provento ou recompra" — termos `dividendo`, `dividendos`, `jcp`, `proventos`, `recompra`, todos no `POS` do léxico | 93 (81%) | **98,9 em 100** |
| as outras oito regras | 22 | **50,0 em 100** |

Dezesseis dos 93 casos da fatia dominante são lista de recomendação ("5 ações
para investir em outubro e embolsar dividendos"), em que a empresa é apenas
citada e o gabarito +1 está errado para o alvo transversal. O LLM devolve ~0 e
é contado como erro.

Medir leitor de notícia contra gabarito de palavra-chave mede **concordância
com o léxico**, não acerto.

### Segundo sinal: o gabarito não aponta para o alvo

Força do léxico (`s × magnitude`) contra retorno residual realizado nos minutos
seguintes à publicação, células (papel, minuto) independentes:

| janela | IC | p | n |
|---|---|---|---|
| 1 min | +0,0234 | 0,850 | 77 |
| 5 min | −0,0996 | 0,373 | 77 |
| 15 min | −0,0707 | 0,513 | 77 |
| 30 min | +0,0600 | 0,612 | 77 |
| 60 min | +0,0104 | 0,927 | 77 |

**DESCRITIVO**: n = 77, abaixo do mínimo de 120 do próprio script. Mas 87,8 em
100 no gabarito convivendo com IC indistinguível de zero contra preço é o
retrato de um gabarito que não mede o que importa.

### Como a pergunta se resolve

```bash
python3 scripts/evento_noticia.py --scorer lexicon --scorer llm
```

Mesmas células para os dois leitores, células de força zero mantidas (é onde a
cegueira de um leitor aparece), retorno residual realizado como juiz.

Critério de aceite, pelas portas de `docs/validacao.md`: ganho incremental de
IC/AUC fora da amostra sobre o leitor atual, sem degradação de Brier skill,
decis monotônicos, sobrevivência à permutação e ao agrupamento por dia e
cluster — **em janela posterior ao cutoff do modelo**. Até lá o estado é
*implementado, não validado*, e `/api/status.scorer` devolve `validado: false`.

## Orientação temporal x retorno — medido em 2026-10-04

`scripts/orientacao_test.py`. **1.166 testes, 80 com n >= 120, zero sobrevive
ao FDR** (q = 0,10). Sem correção, 3 de 80 com p < 0,05 contra **4,0 esperados
por acaso** — o número bruto está abaixo do que o acaso produz.

A hipótese de que notícia de PASSADO explica o movimento já ocorrido **não se
confirma, e falha na direção contrária**: nas três orientações o IC da janela
futuro é maior que o da janela passado.

| orientação | IC janela passado | IC janela futuro |
|---|---|---|
| passado | −0,0064 | +0,0006 |
| presente | +0,0100 | +0,0318 |
| futuro | −0,0150 | +0,0451 |

Melhor célula direcional: IC +0,0451, que pela conversão do projeto vale
**51,4 acertos em 100** — 1,4 ponto acima do cara ou coroa, e não passa.

**Por papel não é mensurável**: nenhum papel individual alcança n >= 120. Os
IC95 do acerto por papel têm 25 a 30 pontos de largura e todos contêm a
taxa-base.

Volatilidade: o sinal **depende da granularidade** — positivo no diário
(+0,0711, as três orientações), negativo no intradiário. Nenhum passa. Detalhe,
tabelas por granularidade e as proteções do desenho em
`docs/orientacao-medicao.md`.

## Métricas de notícia

Para o canal de texto, medir adicionalmente:
- cobertura: proporção de eventos com corpo e timestamp;
- precisão de entidade;
- taxa de duplicação;
- diversidade de fontes independentes;
- tempo até primeira publicação;
- incremento de IC/AUC/Brier sobre o modelo sem texto;
- estabilidade por setor, período e tipo de evento.
