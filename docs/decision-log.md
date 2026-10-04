# Log de decisões e portas

## Decisões de desenho

### Retorno anormal, não retorno bruto
**Decisão:** rotular com retorno relativo ao universo/benchmark.  
**Motivo:** retorno bruto permitiria ao modelo aprender o fator de mercado, não a informação específica da ação.

### Regressão ridge para exposições
**Decisão:** estimar os drivers em conjunto.  
**Motivo:** câmbio, commodities e índices são colineares; betas univariados somados contam o mesmo fator várias vezes.

### Roteamento por driver
**Decisão:** usar a cadeia para decidir o que uma ação deve escutar.  
**Motivo:** uma notícia sobre OPEP pode ser relevante a uma petroleira mesmo sem citar seu nome.

### Deduplicação antes de peso
**Decisão:** agrupar republicações e conteúdo quase idêntico.  
**Motivo:** repetição sindical não é confirmação independente.

### LLM como sensor, nunca oráculo
**Decisão:** usar LLM para extrair campos estruturados, como materialidade, rumor e “já precificado”.  
**Motivo:** pedir previsão de preço aumenta risco de vazamento histórico e cria uma resposta não auditável.

### LLM como leitor primário da notícia (2026-10-04)
**Decisão:** `SCORER_PADRAO = "llm"`. O léxico deixa de ser o leitor de produção
e passa a ser piso auditável e rede de queda.

**Motivo:** os defeitos do léxico são estruturais, não de calibragem — ele lê
**tom**, e o alvo exige **efeito sobre a empresa**. Medidos: "ANP avança …
apesar de resistência da Petrobras" valia **+0,350** para PETR4; a mesma notícia
de desastre dava −0,70 em português, 0,00 em inglês e **+0,60** em francês;
"Petrobras anuncia nova descoberta de petróleo" vale **0,00**, por não ter
palavra no dicionário; `ja_precificado` não é preenchível por léxico nenhum.

**O que NÃO mudou:** o LLM continua sensor. O prompt não pede preço, não pede
data e não pede desfecho. Trocar o leitor melhora a leitura e **não cria**
previsão de direção, que segue reprovada em 6 de 6 (`docs/metricas.md`).

**Estado de evidência:** *implementado, não validado*. O ganho de leitura não
foi medido. A medição que existia (`data/ouro_llm.log`, léxico 87,8 × LLM 53,9)
foi **retirada de circulação como evidência** por circularidade: 93 dos 115
casos vêm de uma regra de gabarito cujos cinco termos estão no dicionário `POS`
do léxico — ali ele acerta 98,9 em 100, e nas outras oito regras, 50,0. Números
em `docs/parecer.md`, seção 4.3.

**Limite deliberado:** no backfill histórico o padrão continua o léxico. Um
modelo com cutoff conhece o desfecho das manchetes antigas, e é desse corpus que
saem os rótulos da calibração; acurácia obtida ali provaria vazamento, não
previsão.

### Porta de autorização no scorer (2026-10-04)
**Decisão:** toda chamada de leitura passa por `obs/llm_client.py`.

**Motivo — era um defeito, não uma preferência:** `score_llm` montava a própria
chamada HTTP e exigia apenas `OBS_LLM_KEY` e `OBS_LLM_URL`. Nunca consultava
`OBS_ALLOW_EXTERNAL_LLM`, a porta que o resto do projeto respeita e que
`docs/relatorios.md` descreve como "nenhum texto sai da máquina por padrão".
Com as duas variáveis definidas para os relatórios, o scorer mandaria texto de
notícia para fora sem a autorização explícita. O cliente único também fixa
temperatura 0 — sem isso, duas rodadas sobre a mesma matéria dão notas
diferentes e nenhuma medição é reproduzível.

## Portas atuais

- Meta-label: desligada até obter monotonicidade e t estatístico adequado.
- Volatilidade: apresentar faixa ordinal enquanto o calibrador não superar a porta de Brier.
- Evento externo: explicação/atribuição, não previsão, se a surpresa for medida pelo próprio movimento contemporâneo do mercado.
- Surpresa macro doméstica: se ligada por configuração apesar do teste negativo, deve ser marcada como experimental e nunca promovida a evidência de previsão.
- Notícias: não tratadas como sinal validado até teste incremental contra retorno realizado.
- Leitor de notícia: a troca para LLM é decisão de leitura, não de evidência.
  `/api/status.scorer` devolve `validado: false` até o teste da seção 7 de
  `docs/parecer.md` passar.

### Classificação de evento ligada ao pipeline (2026-10-04)
**Decisão:** `score.run` passa a chamar `evento.classifica` e gravar
`tipo_evento` e `orientacao` em toda pontuação.

**Motivo — era código morto:** `obs/evento.py` existia com as duas dimensões
implementadas e **nenhum módulo o importava**. As colunas estavam no esquema e
ficaram congeladas no momento em que alguém rodou a classificação à mão;
matéria nova entrava com as duas em `NULL`.

**Defeito corrigido junto:** `INSERT OR REPLACE` apaga a linha e insere outra,
então coluna omitida volta a `NULL`. A inserção de `score.run` não listava
`tipo_evento` nem `orientacao` — ou seja, `limpar --aplicar` zerava a
classificação do acervo inteiro, em silêncio.

**Órgão como ator x órgão como fonte:** o balde `regulatory` do `event_type`
legado mapeava para `judicial` sem distinguir "ANP aprova delimitação" de
"produção supera marca, diz ANP". O segundo é a agência como fonte do dado e
não é evento judicial. `evento._orgao_como_ator` exige ato administrativo
perto do nome do órgão, ou disputa contra ele.

**Limite do corpo escolhido por medição:** 300 caracteres de corpo limpo. Em
300 os casos de duas marcas chegam ao máximo (341) e as três marcas ficam sob
10%; acima disso só a marcação inútil cresce. Tabela em `obs/evento.py`.

## Inconsistências que exigem registro

### Registrada em 2026-10-04: a correção que não rodava
`score_lexicon(title, body, ticker)` recebeu a heurística de posição no fato
para consertar o caso ANP/Petrobras, mas `score.run()` chamava
`fn(title, body)` **sem o ticker** quando o leitor era o léxico. A correção
existia no arquivo e era código morto: a mesma manchete dá **+0,35 sem o
ticker** e **−0,35 com ele**. Corrigido; os 777 scores gravados antes estão sob
a regra antiga e exigem `limpar --aplicar` para serem repontuados.

Pelo mesmo motivo, havia `"lexicon"` escrito no código em quatro pontos
(`cli.cmd_ingest_rss`, `cli.cmd_backfill_rss`, `historico.preparar`,
`limpeza.limpar`) mais `api.SCORER`: pedir `--scorer llm` no `cycle` não mudava
o que a rodada rápida de RSS gravava. Agora o leitor vem de um lugar só.


A configuração e a documentação podem divergir. Sempre declarar:
1. o que o código está fazendo;
2. o que a evidência validou;
3. a decisão de produto tomada apesar da evidência.

Exemplo: uma camada pode estar `ATIVO=True` por decisão experimental e, ao mesmo tempo, continuar não validada. Esse estado não é “aprovada”; é “ligada para experimento”.
