# Como iniciar e usar

## 1. Arranque

```bash
bash scripts/iniciar.sh
```

Sobe o banco, o proxy de IA, os dados base e o painel. Depois, em **outro
terminal**, deixe o worker rodando:

```bash
python3 -m obs.cli worker --seconds 20
```

O worker é quem executa o que você enfileira na Central de Operações. Sem ele,
"Rodar agora" fica em `queued` para sempre.

| Onde | Para quê |
| --- | --- |
| `http://127.0.0.1:8105/` | painel: alta, queda, agitação, notícias, cadeia |
| `http://127.0.0.1:8105/admin.html` | Central de Operações: agendar e rodar jobs |

### Não rode a ingestão no terminal

`obs ingest` leva **mais de 5 minutos**: o GDELT impõe 1 requisição a cada 5,5s
e são 10 papéis mais as consultas roteadas. Rodando à mão você desiste no meio e
conclui que não há notícia. Enfileire `refresh_news` na Central e deixe o worker
levar — ele tem 30 min de folga por job.

## 2. O que já funciona hoje

**Agitação** é a única cabeça calibrada: AUC 0,590 fora da amostra, 8 anos,
20.410 observações. Lê-se *"MGLU3 com 36% de chance de ficar no top 20% de
volatilidade amanhã, contra base de 20%"*. Não diz a direção.

**Documentos oficiais** funcionam agora, sem acumular nada:

```bash
python3 -m obs.cli cvm-sync --ticker PETR4 --limite 10
python3 -m obs.cli report-extract --id <id>
python3 -m obs.cli report-analyze --id <id> --externo
```

Use `cvm-sync`, não `ri-sync`: o IPE da CVM traz link direto para cada
documento entregue. Os sites de RI da Petrobras e da Vale montam a lista por
JavaScript, então o crawler acha a página e não o PDF.

**Cadeia de afetação**: clique num papel e veja a que assuntos ele reage. É
descritiva — o teste de permutação dela não foi feito.

## 3. Destravar a direção

A direção não calibra no primeiro dia, e não é defeito: o rótulo exige sinal do
passado casado com o retorno que veio depois. Ao vivo, juntar os 120 eventos
mínimos levaria meses.

O atalho é reconstruir o histórico, porque o GDELT aceita janela fechada:

```bash
python3 -m obs.cli backfill --dias 365
```

Leva **cerca de 50 minutos** (53 janelas × 10 papéis × 5,5s). Faz a cadeia
inteira: baixa notícia antiga, liga menções, pontua, reconstrói os sinais
passados com asof no fechamento de cada dia, e rotula. No fim diz quantos
rótulos saíram.

**Repetir é seguro e às vezes necessário.** O artigo entra com `INSERT OR
IGNORE` pela URL, então rodar de novo não duplica nada — só preenche o que
faltou. E vai faltar: se você tiver feito muitas chamadas ao GDELT antes, ele
responde throttle por um tempo e janelas inteiras voltam vazias. O log diz
`sem resposta` quando é isso. Espere algumas horas e rode de novo; para
reaproveitar o que já está no banco sem baixar nada:

```bash
python3 -m obs.cli backfill --dias 365 --sem-baixar
```

Se passar de 120 rótulos:

```bash
python3 -m obs.cli calibrate --method platt
```

**Leia o aviso que o comando imprime.** Rótulo de backfill é *estimativa*: o
GDELT indexa pelo `seendate` (quando ele viu), não pela publicação, e a
cobertura retroativa não é a que estava visível em tempo real. Serve para abrir
a primeira porta; o ciclo ao vivo vai substituindo por rótulo limpo. Se o skill
de Brier vier negativo, a porta barra e o painel continua mostrando
`não calibrado` — isso é resultado válido, não falha.

## 4. Rotina diária

Na Central de Operações, ligue:

| Job | Quando |
| --- | --- |
| Atualizar notícias | 15 min, dias úteis, horário de pregão |
| Atualizar preços | após o fechamento |
| Atualizar drivers | diário |
| Descobrir documentos de RI | diário |
| Processar PDFs pendentes | após o download |

Deixe **manuais**: recalibrar direção, recalibrar agitação, experimento PEAD.
Calibração não deve rodar sozinha.

## 5. Usando de fato

1. **De manhã** — abra o painel e olhe a coluna de agitação, a que tem lastro.
   Papel com vantagem grande sobre a taxa-base é papel para acompanhar.
2. **Clique no papel** — veja as manchetes que formaram o sinal e a cadeia de
   drivers. Responder *por quê* é o entregável mais confiável do sistema.
3. **Quando sair resultado trimestral** — `cvm-sync`, extraia, analise. Em
   minutos você tem os fatos do documento com citação de página.
4. **Semanalmente** — `python3 -m obs.cli status` para ver o histórico crescer.

## 6. Quando algo vier vazio

Fonte morta não dá erro: devolve zero, e você conclui que não houve notícia.
Três casos já medidos neste projeto:

- `valor.globo.com/rss/` estava morto. O caminho certo é
  `pox.globo.com/rss/valor/` — 100 itens contra 0.
- `infomoney.com.br/mercados/feed/` devolve 0; só o feed raiz funciona.
- O GDELT recusa a consulta **inteira** quando uma frase tem palavra curta
  demais, e responde em texto puro em vez de JSON. O papel volta sem nenhuma
  notícia. Ver `_frase_valida` em `obs/ingest.py`.
- A Reuters devolve **401**, não 403: o RSS público foi descontinuado e virou
  licença. Não é bloqueio anti-bot, não há o que contornar.

E um caso pior que fonte vazia — **fonte que mente**. A mesma notícia de
desastre pontuava:

| idioma | nota |
| --- | --- |
| português | −0,70 ✓ |
| inglês | 0,00 (`record` cancelava `loss`) |
| alemão | 0,00 (nenhuma palavra no léxico) |
| francês | **+0,60** ✗ |

O francês inverte o sinal porque `perte record` casa com o `record` positivo do
inglês. Idioma vizinho é pior que idioma distante: gera falso positivo em vez
de silêncio. Por isso existe a porta `IDIOMAS_LEXICO` em `obs/score.py`, e por
isso o idioma passou a ser lido do feed em vez de fixo no código.

Antes de concluir que não há notícia, confira quantos artigos entraram:

```bash
python3 -m obs.cli status
```

## 7. O que o sistema não faz

Não recomenda compra ou venda e não prevê preço. A direção, quando calibrar,
deve acertar algo como **52,6 vezes em 100** — vantagem real, e pequena demais
para pagar corretagem numa operação isolada.

É um observatório de pesquisa.
