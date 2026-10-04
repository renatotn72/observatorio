# Parecer técnico — Observatório de Ações

**Data:** 4 de outubro de 2026
**Base:** os 25 documentos de `docs/`, o código de `obs/` e `scripts/`, e o banco
de medição em `data/observatorio.db` (778 pares pontuados, 115 casos de
conjunto-ouro, 2.031 minutos de barras intradiárias).
**Natureza:** parecer de projeto. Não é recomendação de investimento e não
avalia rentabilidade.

---

## 1. Veredito

O projeto é **honesto, bem medido e sóbrio** — e essa é a sua característica
técnica dominante, não um elogio de forma. A regra de ouro de `docs/README.md`
está implementada no código, não só declarada: existem portas que recusam exibir
número (`calibrated: 0`), um módulo que é fonte única dos selos de qualidade
(`obs/medidas.py`), um log de decisões que registra o que foi reprovado e um
módulo de limpeza que existe só para remover dado calculado sob regra que mudou.
Doze hipóteses reprovadas estão documentadas com p-valor. Três passaram. Isso é
raro e é o principal ativo do trabalho.

O risco do projeto **não é overfitting**: é a tentação de confundir o que foi
construído com o que foi provado. A documentação resiste bem a essa tentação. O
código, em três pontos, não resistia — e é o que este parecer aponta na seção 5.

Em uma linha: **o produto entregue é "por que este papel se move" e "quanto ele
deve se mexer"; não é "para onde ele vai"** — e a direção não está perto de ser
entregável.

---

## 2. O que o sistema é

Um observatório de pesquisa que combina três canais de entrada — notícia, preço
e macro — para estimar comportamento **relativo** entre ~10 ações da B3. O alvo
é retorno **anormal transversal** (ação menos a média das outras, em múltiplos
da volatilidade do próprio papel), e essa escolha de alvo é a decisão de
desenho mais acertada do projeto: ela impede o modelo de aprender o Ibovespa e
chamar isso de sinal.

Três cabeças, com lastro muito diferente entre si:

| cabeça | o que responde | estado |
|---|---|---|
| **Agitação** | vai se mexer muito amanhã? (sem lado) | **calibrada e aprovada** |
| Alta / Queda | vai subir ou cair? | **não calibrada** — reprovada em 6 de 6 |
| Meta-label | a direção está certa? | desligada, reprovada |

O pipeline (`docs/arquitetura.md`) é: ingestão → ligação de entidade →
deduplicação → **leitura da notícia** → cadeia de afetação → agregação ponderada
→ calibração com portas → painel. A etapa de leitura é o objeto da seção 4.

---

## 3. Placar da evidência

Os quatro estados de `docs/README.md`, preenchidos:

### Medido e aprovado
- **Agitação, topo 5%**: 38,0 acertos em 100 contra taxa-base de 19,7 — 1,92×,
  com IC95 [35,1–41,0] excluindo a base. Ordenação monotônica do decil 1 ao 10
  (14,6 → 34,7). É o único entregável probabilístico do sistema.
- **Parcimônia**: três features entregam o mesmo que cinco (AUC 0,5913 contra
  0,5902). Payroll e vol-5 não acrescentam nada mensurável. Medir isso e
  **remover** feature é disciplina que quase nenhum projeto do gênero tem.
- **Exposição cambial** como única sobrevivente do teste rigoroso entre 14
  drivers.

### Medido e reprovado
- **Direção, 0 de 6 especificações.** AUC 0,5043 contra 0,5054 do controle de
  ruído puro, no mesmo arcabouço que dá 1,0000 no oráculo. O maquinário está
  certo; o sinal não carrega direção. A linha que "passou" em D+20 era artefato
  de janelas sobrepostas e caiu ao ser refeita com datas disjuntas — **terceira
  vez que esse mesmo erro aparece no projeto**, segundo `docs/metricas.md`.
- **Surpresa macro doméstica**: p entre 0,45 e 0,79 em quatro indicadores.
  Continua ligada por decisão explícita do usuário, marcada como experimental.
- **Meta-label** e **persistência de assimetria** (p 0,065–0,107).
- **Payroll** como feature: Δ AUC **+0,0011 ao ser retirada** — ela piorava.

### Implementado, não validado
- Canal de notícias inteiro, incluindo o léxico, a camada setorial
  (`PESO_SETOR = 0.35`, declarado como palpite) e as cinco features de atenção
  de `obs/atencao.py` — que estão ligadas na cabeça de agitação e **não medidas**.
  Vale sublinhar: o calibrador aprovado de agitação **não usa nenhuma delas**;
  roda com cinco features de preço e calendário. A tese central de
  `docs/psicologia.md` segue sem teste.
- Cadeia de afetação: descritiva, sem teste de permutação.
- PEAD: estruturado, sem fonte de consenso.
- **A leitura da notícia por LLM, após esta entrega.**

### Hipótese de pesquisa
As dez linhas de `docs/direcao.md` e as features de cascata de
`docs/psicologia.md`.

### Um ponto de atenção sobre o número exibido
`scripts/confiabilidade.py` encontrou **viés sistemático de otimismo**: todos os
dez decis realizam abaixo do previsto, entre −0,7 e −3,3 pontos, ECE de 1,81
pontos, com 4 dos 10 decis fora do IC95. O painel mostra ~2 pontos a mais do que
acontece. Está documentado como corrigível por reajuste de intercepto, e **não
foi corrigido**. É a correção de maior relação benefício/custo em aberto: é
pequena, é mecânica e afeta o único número que o sistema exibe com lastro.

---

## 4. A pergunta central: por que léxico, e a LLM é melhor?

### 4.1 Por que o léxico existia

Quatro razões, todas defensáveis no momento em que foram tomadas:

1. **Piso auditável.** `obs/score.py` o descreve como "o baseline honesto: roda
   offline, sem dependência, e é fraco — e justamente por isso serve de piso a
   ser batido". Um backtest de 2016 reproduz idêntico em 2036.
2. **Autorização.** `docs/implementacao-configurada.md` registra "permissão
   externa: **não autorizada**". Nenhum texto saía da máquina. Só com o proxy
   local (`docs/proxy-sai.md`) isso mudou.
3. **Custo e escala.** O léxico roda em toda matéria; a chamada ao modelo custa
   por artigo.
4. **Contaminação.** Um modelo com cutoff sabe o que aconteceu depois da
   manchete. É a razão mais forte das quatro, e continua valendo — ver 4.5.

### 4.2 Os defeitos do léxico estão medidos, e são estruturais

Não é questão de o léxico ser "fraco". Ele erra de um modo que contagem de
palavras não tem como corrigir:

| defeito medido | consequência |
|---|---|
| "ANP avança para reduzir concentração no mercado de gás **apesar de resistência da Petrobras**" → **s = +0,350** para PETR4 | a empresa é a parte perdedora e a nota saiu positiva |
| a mesma notícia de desastre da Vale: **−0,70** em português, **0,00** em inglês ("record" cancelava "loss"), **+0,60** em francês ("perte record") | o lado do sinal depende do idioma do jornal |
| "juros sobre o capital próprio" valia 0; "JCP" valia +0,45 | a mesma notícia pontuava diferente conforme o jornal abreviasse |
| 44% dos eventos em `unclassified` | tipo de evento quase não discrimina |
| `ja_precificado` não é preenchível por léxico nenhum | em 5 matérias reais, o léxico deu peso 1,12 ao conjunto e o julgamento estruturado deu 0,18 — **84% a menos** — porque 4 eram dividendo rotineiro, etapa procedimental ou retrospectiva |

Cada um desses gerou uma regra nova empilhada sobre contagem de palavras:
`PHRASES`, `NEGATORS`, `HEDGES`, `ADVERSO`/`FAVORAVEL`, `IDIOMAS_LEXICO`. O
limite é de natureza, não de calibragem: **o léxico lê tom, e o alvo exige
efeito sobre a empresa.** "Petrobras anuncia nova descoberta de petróleo" vale
**0,00** no léxico — nenhuma palavra do dicionário — e é um dos eventos mais
materiais que existem para o papel.

### 4.3 Já havia uma medição. Ela favorece o léxico. E ela não vale.

Este é o achado mais importante deste parecer.

`data/ouro_llm.log` registra uma rodada completa de `scripts/ouro_llm.py`:

```
conjunto-ouro: 115 casos
  léxico   101 acertos   87,8 em 100
  LLM       62 acertos   53,9 em 100
  diferença −39          −33,9
```

Lido de fora, isso encerraria a discussão a favor do léxico. **O gabarito é
circular.** Medido hoje, sobre os mesmos 115 casos:

- **93 deles (81%)** vêm de **uma única regra** de `scripts/ouro_direcao.py`,
  "provento ou recompra", cujos cinco termos — `dividendo`, `dividendos`, `jcp`,
  `proventos`, `recompra` — **estão todos no dicionário `POS` do léxico**, com
  peso positivo. O gabarito diz "+1 quando a manchete contém a palavra
  dividendo"; o léxico pontua +0,5 exatamente por essa palavra.
- Nessa fatia o léxico acerta **98,9 em 100**. Nas outras oito regras (22 casos),
  **50,0 em 100** — o chute para uma decisão de sinal.
- **16 dos 93** casos da regra dominante são **lista de recomendação**: "5 ações
  para investir em outubro e embolsar dividendos", "Rendimentos de até 11,8%: as
  10 ações do BTG Pactual", "Dividendos de até 6%: veja a nova aposta da carteira
  recomendada do Itaú". Ali a empresa é **apenas citada** e o gabarito +1 está
  errado para o alvo do projeto. O LLM devolve ~0 e é contado como erro por estar
  certo. Há ainda o caso "EZTec sobe forte na bolsa após 'cheque gordo' do Itaú",
  rotulado +0,72 **para ITUB4** — matéria sobre a EZTEC.

Medir leitor de notícia contra gabarito feito de palavra-chave premia quem lê
palavra-chave. Aquele 87,8 mede **concordância com o léxico**, não acerto.

E há um segundo sinal de que o gabarito não mede o que importa. No mesmo banco,
a força do léxico (`s × magnitude`) tem **IC indistinguível de zero** contra o
retorno residual realizado nos minutos seguintes à publicação:

| janela | IC | p | n |
|---|---|---|---|
| 1 min | +0,0234 | 0,850 | 77 |
| 5 min | −0,0996 | 0,373 | 77 |
| 15 min | −0,0707 | 0,513 | 77 |
| 30 min | +0,0600 | 0,612 | 77 |
| 60 min | +0,0104 | 0,927 | 77 |

Com n = 77 células independentes (papel, minuto), abaixo do mínimo de 120 do
próprio script, isso é **descritivo, não veredito** — e é assim que o script o
rotula. Mas a leitura qualitativa é clara: **87,8 em 100 no gabarito convivem
com zero poder sobre o preço.** O gabarito e o alvo não apontam para o mesmo
lugar.

**Conclusão da seção:** o estado correto da comparação léxico × LLM não é "o
léxico ganhou". É **"não medido"**. O resultado anterior deve ser retirado de
circulação como evidência, e foi — está anotado dentro de
`scripts/ouro_llm.py`.

### 4.4 "LLM pura para dar o score": o que isso resolve e o que não resolve

A proposta junta duas perguntas que têm respostas opostas, e separá-las é o
ponto técnico deste parecer.

**Ler a notícia** — o que aconteceu, com quem, qual a posição da empresa no
fato, qual a materialidade frente ao tamanho dela, se é rumor, se já está no
preço. Aqui o LLM é **estritamente superior** e o léxico é estruturalmente
incapaz (4.2). Esta troca está feita.

**Dar o score preditivo** — a probabilidade de alta amanhã. Aqui **nenhum
leitor ajuda**, porque o problema não é de leitura. A direção foi reprovada em
6 de 6 testes com AUC indistinguível de ruído, e isso **não é um defeito do
léxico**: o canal testado ali era o de drivers, sem texto nenhum. Com IC de
0,09, a conversão `P = 0,5 + arcsin(IC)/π` daria 52,9 acertos em 100; para 70
seria preciso IC 0,588 — 6,5× o medido. Trocar o leitor não move essa
aritmética.

Por isso a regra de `docs/decision-log.md` — **"LLM como sensor, nunca
oráculo"** — foi mantida, e o prompt continua proibido de pedir preço, data ou
desfecho. O que mudou é quem lê, não o que se pergunta.

### 4.5 Onde o LLM não deve entrar: o backfill

O `backfill` de 10 anos é o único caminho do projeto para os 120 rótulos que
destravam a calibração — ao vivo levaria meses. É também o corpus mais
contaminado que existe: um modelo com cutoff conhece o desfecho de cada
manchete de 2016–2025. Acurácia alta obtida ali **não prova previsão, prova
vazamento**.

Portanto: **ao vivo o leitor é o LLM; no histórico o padrão continua o léxico.**
Pontuar histórico com LLM exige `--scorer llm` explícito e imprime aviso. A
validação do canal de texto só vale em janela **posterior ao cutoff** do modelo.

---

## 5. Três defeitos de código encontrados na revisão

Não são observações de estilo. Os três faziam a documentação divergir do que o
código executava — exatamente a inconsistência que `docs/decision-log.md` manda
registrar.

1. **A correção do caso ANP/Petrobras nunca rodou em produção.**
   `score_lexicon(title, body, ticker)` recebeu a heurística de posição no fato
   justamente para consertar aquele caso, mas `score.run()` chamava
   `fn(title, body)` **sem o ticker** quando o scorer era o léxico. A correção
   existia no arquivo e era código morto. Medido agora: a mesma manchete dá
   **+0,35 sem o ticker** e **−0,35 com ele**. Consequência operacional: os
   scores que já estavam no banco (777 dos 778 atuais) vieram da regra antiga e
   precisam de `limpar --aplicar` para serem repontuados.

2. **`score_llm` ignorava a porta de autorização.** Ele montava a própria
   chamada HTTP e exigia apenas `OBS_LLM_KEY` e `OBS_LLM_URL` — nunca consultava
   `OBS_ALLOW_EXTERNAL_LLM`, a porta que `obs/llm_client.py` respeita e que
   `docs/relatorios.md` descreve como "nenhum texto sai da máquina por padrão".
   Com as duas variáveis definidas para os relatórios, o scorer mandaria texto
   para fora sem a autorização explícita. Também não fixava temperatura, o que
   tornava duas rodadas sobre a mesma matéria irreprodutíveis.

3. **A escolha de scorer não se propagava.** Havia `"lexicon"` escrito no código
   em quatro pontos — `cli.cmd_ingest_rss`, `cli.cmd_backfill_rss`,
   `historico.preparar`, `limpeza.limpar` — mais `api.SCORER`. Pedir
   `--scorer llm` no `cycle` não mudava o que a rodada rápida de RSS gravava, e
   `limpar --aplicar` repontuaria o léxico mesmo com o LLM ativo.

E um quarto, menor mas que bloqueava toda medição: **11 dos 23 scripts de
`scripts/` tinham o caminho absoluto `/mnt/nvmep2/home/rtnati/...` no
`sys.path`** — inclusive `ouro_llm.py` e `evento_noticia.py`, que são os dois
que decidem esta pergunta. Nenhum deles rodava fora da máquina do autor.

---

## 6. O que foi ajustado nesta entrega

Esta entrega move o projeto do **ponto 3** para o **ponto 4** da ordem prática de
`docs/canal-noticias.md` ("rodar LLM como rotulador/extrator").

**Leitor:** `SCORER_PADRAO = "llm"` (`OBS_SCORER` sobrescreve). Sem proxy
autorizado, `resolver()` cai para o léxico **dizendo que caiu** — no terminal,
em `/api/status.scorer` e no cartão "Notícias" do painel. Painel vazio se lê
como "não houve notícia", que é a conclusão errada mais comum deste projeto.

**Extração em coluna:** `papel_no_fato`, `ja_precificado`, `is_rumor` e `quote`
saíram do JSON `raw` e viraram colunas de `scores`. Feature que não dá para
consultar não dá para medir, e o ganho incremental do canal de texto exige
cruzar `ja_precificado` com retorno realizado — isso é um `GROUP BY`, não um
`json_extract` em 50 mil linhas. O léxico deixa as quatro em `NULL`, e esse
`NULL` é informativo.

**Custo, que é o que torna a troca operável:**
- *cache* (`llm_cache`, chaveado pela versão do prompt): repontuar não paga
  releitura. Sem isso o operador deixaria de rodar `limpar --aplicar`, que é a
  operação que conserta regra errada;
- *reuso por cluster*: a 20ª republicação não paga leitura nova — "cópia não é
  voto", aplicado ao custo. Verificado: 1 chamada para 3 cópias;
- *teto por rodada* (`OBS_LLM_MAX_CHAMADAS`, padrão 400): o resto fica pendente
  para a próxima rodada;
- *isolamento de falha*: par que falha fica **sem nota**, não recebe nota de
  outro leitor sob o nome `llm`; 5 falhas seguidas abortam a rodada.

**Coerência verificada, não pedida:** o prompt exige "prejudicada ⇒ s < 0", mas
instrução não é garantia — e é esse exatamente o erro que motivou a troca. O
código confere, inverte a nota quando o modelo se contradiz e grava a
contradição em `raw.incoerencia`, que é contável.

**Auditoria:** `signals.scorer` grava quem leu cada sinal; sem isso um backfill
do léxico e uma rodada ao vivo do LLM ficam indistinguíveis na mesma tabela e o
calibrador treina na mistura. `obs score-estado` mostra autorização, modelo,
versão do prompt, cobertura por leitor e pendentes. O job `score_news` tira a
pontuação do acidente em que estava — quem pontuava o GDELT era, por acaso, a
rodada de RSS.

**Medição:** `scripts/evento_noticia.py --scorer lexicon --scorer llm` compara
os dois **nas mesmas células** (papel, minuto) contra retorno residual
realizado, mantendo as células de força zero — que é justamente onde a cegueira
de um leitor aparece. `scripts/test_score_llm.py` prova o caminho com
respondedor falso, sem rede: 9 casos, 22 verificações, todas passando.

---

## 7. O que falta para fechar o ponto 4

O leitor novo entra como **"implementado, não validado"**. É o estado correto, e
não uma ressalva de praxe: o ganho de leitura é argumentável pelos defeitos da
seção 4.2, mas **não medido**.

1. **Autorizar e pontuar ao vivo** (proxy de pé): `obs score --scorer llm`.
2. **Comparar contra retorno realizado**, acumulando até n ≥ 120 células:
   `scripts/evento_noticia.py --scorer lexicon --scorer llm`.
3. **Construir gabarito independente** — a amostra humana de auditoria do ponto
   2 da ordem prática, rotulada **sem** usar as palavras do léxico. É a única
   forma de ter um conjunto-ouro que não premia quem lê palavra-chave.
4. **Validar em janela posterior ao cutoff** do modelo, pelas portas de
   `docs/validacao.md`: corte temporal, embargo, ganho sobre preço/drivers,
   monotonicidade por decil e permutação.
5. Só então promover o estado em `obs/medidas.py` e em `/api/status.scorer`.

Critério de parada, já escrito em `docs/canal-noticias.md` e que deve ser
respeitado: se corpo de texto, entidade, clusterização e materialidade não
gerarem ganho incremental fora da amostra, **o canal de notícias é produto de
pesquisa e explicação, não sinal preditivo** — e trocar o leitor não muda esse
critério.

---

## 8. Recomendações, por relação benefício/custo

| # | ação | por quê |
|---|---|---|
| 1 | `limpar --aplicar` | 777 scores estão sob a regra sem ticker; é o defeito 1 da seção 5 |
| 2 | corrigir o intercepto da agitação | ~2 pontos de otimismo no único número com lastro; correção mecânica já diagnosticada |
| 3 | medir as features de atenção | cinco features ligadas e não medidas na cabeça aprovada; `scripts/atencao_test.py` já existe |
| 4 | baixar corpo do artigo | título carrega o evento, corpo carrega magnitude — e é o insumo que o leitor novo melhor aproveita |
| 5 | testar a camada setorial | `PESO_SETOR = 0,35` é palpite declarado, e setor é a granularidade que **sobrevive** ao alvo transversal |
| 6 | permutação da cadeia de afetação | é o entregável mais usado do painel e nunca foi testado |
| 7 | não religar direção | 0 de 6; sem feature nova, religar é só repetir o teste |

---

## 9. Ressalvas deste parecer

- Os números das seções 3 e 4 vêm da documentação do projeto e do banco local.
  **Não os reproduzi de ponta a ponta**: os scripts de medição pesada
  (`metrica_total.py`, `direcao_test.py`, `confiabilidade.py`) não foram
  re-executados nesta revisão.
- O que **foi** medido aqui, neste banco: a circularidade do conjunto-ouro
  (93/115, 98,9 contra 50,0), a fração de listas de recomendação (16/93), o IC
  do léxico contra retorno residual (n = 77, descritivo) e os quatro defeitos de
  código da seção 5.
- A leitura por LLM **não foi exercitada contra o modelo real** nesta sessão: não
  há proxy autorizado no ambiente. O que está verificado é o caminho, com
  respondedor falso. O ganho de leitura segue não medido, e é por isso que
  `/api/status.scorer` devolve `validado: false`.
