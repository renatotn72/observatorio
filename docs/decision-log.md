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


### Registrada em 2026-10-04: "o Yahoo não dá OHLCV" — afirmação minha, errada
Publiquei em `docs/precos-fontes.md`, em `config/sources.yml`
(`yahoo: ohlcv: false`, com a nota "só fechamento") e no docstring de
`obs/uol.py` que a UOL **acrescentava OHLCV** porque a fonte atual só dava
fechamento. **Falso.** O endpoint `v8/finance/chart` devolve
`indicators.quote[0].open/high/low/volume` no mesmo pacote, e
`obs/prices.py:fetch_yahoo` lê os quatro.

Por que o erro passou: o que é verdade é que **o banco** não tem OHLCV — 24.920
barras diárias com `open` e `volume` nulos em todas, medido. Eu li a ausência
no banco como ausência na fonte. São coisas diferentes: a causa é que as barras
foram coletadas antes de o código ler esses campos.

O erro **inflava o valor da fonte nova**, que é o tipo de erro que mais importa
corrigir aqui, porque justifica trabalho pela razão errada. O que a UOL de fato
acrescenta é **descoberta** (catálogo de ~1.800 tickers com id; o Yahoo não tem
endpoint de listagem, e é por isso que a watchlist travou em 10) e **bid/ask**.
Corrigido nos quatro lugares, com retratação explícita na página.

### Registrada em 2026-10-04: complemento exige código, senão é substituição
O requisito era "não exclui a forma antiga, é complemento". A chave de `prices`
é `(ticker, date)` e a gravação era `INSERT OR REPLACE`: ligar a UOL assim
**reescreveria** cada barra que a fonte antiga já tinha — 10 anos de série
ajustada trocados por 5 anos de série de ajuste desconhecido, sem erro e sem
aviso. Era defeito já escrito e testado, pego ao reler o próprio diff.

`grava_diario` passou a ter `complementar=True`, em que o fechamento e a origem
de quem chegou primeiro ficam e só as colunas vazias são preenchidas; a
procedência virou dois campos (`origem` do fechamento, `origem_ohlc` do OHLCV),
porque uma barra pode ter o fechamento de uma fonte e o volume de outra. As
24.920 barras anteriores ficaram `origem='legado'` — não dá para saber se
vieram do brapi ou do Yahoo, porque `sync()` tentava um e caía para o outro sem
registrar qual atendeu, e 'legado' afirma só o que é verificável.

Efeito colateral útil: duas fontes na mesma barra permitem conferir ajuste por
proventos **sem** depender de desdobramento conhecido (`prices.divergencia`),
que era o buraco da armadilha 3.

### Registrada em 2026-10-04: `bid`/`ask` são hipótese, não medição
Entram no banco porque nenhuma outra fonte do projeto dá spread, e
`docs/canal-noticias.md` pede liquidez e spread como feature desde o início.
Mas **não está verificado** se no intraday eles são por barra ou da sessão — e
`high`/`low`/`open` do mesmo endpoint são da sessão, então a hipótese pessimista
é plausível. `obs/uol.constantes` responde na primeira coleta real e avisa alto;
até lá a coluna é "implementada não validada", não "medida".

### Registrada em 2026-10-04: o tipo `calendário` tinha 100% de erro
A regra casava "fato relevante" e "comunicado ao mercado" -- que são os NOMES
DO DOCUMENTO arquivado na CVM, não tipos de evento, e aparecem no corpo de
quase qualquer anúncio corporativo. Das 6 matérias marcadas `calendario` no
acervo, 6 eram outra coisa: descoberta de gás, fábrica de baterias, venda de
operação, plano de investimento, aquisição. Uma só era de calendário, e por
acidente.

Idem `legislativo` com `congresso` e `senado` soltos: medido, 53 artigos citam
"congresso" e só 7 citam "Congresso Nacional" (87% são congresso de área, entre
eles "Congresso IBGC: o ser humano na liderança da transformação", marcado como
ato legislativo); 103 citam "senado" e a maioria é cobertura eleitoral. As duas
regras passaram a exigir, respectivamente, construção que anuncia data/agenda e
a casa agindo.

**O defeito foi achado LENDO os 6 casos, não medindo.** Com n=6 a margem de
erro de qualquer taxa passa de 60 pontos; nenhuma estatística o acharia. Fica
registrado como o argumento de por que `scripts/tipo_evento_test.py` roda uma
auditoria à mão junto com a medição, e não em vez dela.

Efeito: calendário 6 -> 1, legislativo 6 -> 3, corporativo 611 -> 619. Os dois
tipos pedidos ficaram MENORES -- que é a resposta certa.

### Registrada em 2026-10-04: comparador errado na tabela de volatilidade
`em_100` comparava a precisão no topo 20% com 50 em 100. Mas nessa tabela
"acertar" é o papel ter ficado entre os 20% que mais se mexeram, e chutar às
cegas acerta ~20 em 100, não 50. O texto dizia "acerta menos que a moeda" para
resultado que estava acima do chute real. Corrigido: o comparador é a taxa-base
da própria pergunta, e o cabeçalho avisa qual é a régua.

### Registrada em 2026-10-04: `adjclose` entra, e a série de retorno muda
O chart v8 do Yahoo (`period1=0&events=div|split|earn`) traz
`indicators.adjclose`, que e a serie certa para calcular retorno: `close` cru
cai o valor do provento em cada data-ex e a conta registra isso como perda do
acionista, que recebeu o dinheiro. Os dois sao gravados em colunas separadas --
`close` para a tela, `adjclose` para a conta.

CONSEQUENCIA QUE PRECISA FICAR DITA: todo numero de docs/metricas.md foi
calculado sobre `close`, porque `adjclose` nao existia no banco. Depois da
coleta, o mesmo teste pode dar outro resultado, e a diferenca nao e erro de
nenhum dos dois -- e mudanca da serie de entrada.
`returns_by_date(con, ajustado=False)` reproduz o calculo antigo, para o
tamanho do efeito ser MEDIDO em vez de suposto.

A escolha da coluna e POR PAPEL e INTEIRA. `COALESCE(adjclose, close)` seria
mais curto e seria defeito: metade da serie ajustada e metade crua da um salto
na fronteira que nao houve no mercado, e nada no dado denunciaria.

### Registrada em 2026-10-04: `ativos` tinha a chave errada
A tabela nasceu com `PRIMARY KEY (ticker)`. Com duas fontes de cadastro -- UOL
pelo data-id, Yahoo pelo simbolo .SA -- a segunda a sondar apagaria o id da
primeira, e a coleta dela passaria a pedir o id errado SEM ERRO: a linha
continua existindo e parecendo valida. Chave corrigida para (ticker, fonte),
com recriacao da tabela na migracao, e todas as consultas da UOL passaram a
filtrar por `fonte`.

### Registrada em 2026-10-04: os 89 papeis NAO entraram em `tickers:`
`tickers:` define, de uma vez, quem o matcher procura, quem tem preco e quem
compoe a media transversal que serve de benchmark. Ampliar para 89 trocaria o
benchmark de 10 para 89 papeis, e como retorno anormal e retorno menos essa
media, TODO retorno anormal do banco mudaria de valor junto com cada numero de
docs/metricas.md -- uma re-baseline de todas as medicoes disparada por um
download de preco.

A lista entrou como `universo:`, que coleta preco e mais nada. A troca de
benchmark vale a pena (media de 89 e proxy melhor que media de 10) e fica
registrada como DECISAO PENDENTE do usuario, com o caminho descrito em
docs/precos-universo.md: mover para `tickers:` com aliases e re-rodar as
medicoes guardando o antes e o depois.

### Registrada em 2026-10-04: meu resumo de divergencia mentia por omissao
A primeira versao classificava como "estavel no tempo -> misturavel" um papel
com 146% de diferenca media entre as fontes, so porque a diferenca nao crescia
para tras. Diferenca estavel de 146% nao e arredondamento nem horario de corte
-- e outra serie. A magnitude passou a mandar primeiro (limiar de 5%) e a
tendencia so escolhe entre as causas.

A configuração e a documentação podem divergir. Sempre declarar:
1. o que o código está fazendo;
2. o que a evidência validou;
3. a decisão de produto tomada apesar da evidência.

Exemplo: uma camada pode estar `ATIVO=True` por decisão experimental e, ao mesmo tempo, continuar não validada. Esse estado não é “aprovada”; é “ligada para experimento”.
