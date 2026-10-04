# Central de Operações

Abra `http://127.0.0.1:8000/admin.html`.

## Worker

O painel cria apenas jobs autorizados no SQLite. Para consumi-los:

```bash
python -m obs.cli worker --seconds 20
```

Não existe executor de comandos arbitrários.

## Agenda

Jobs agendáveis podem ter intervalo configurado no formulário. O mínimo é 5 minutos.
A primeira implementação considera dias úteis (segunda a sexta); feriados B3 precisam de
calendário específico antes de bloqueio automático.

Backtests, recalibrações e análise externa de **relatório em PDF** são
deliberadamente manuais.

## Pontuar notícias (2026-10-04)

O job `score_news` ("Pontuar notícias (leitor ativo)") é agendável e roda
`obs pontuar`: liga menções, agrupa duplicatas e pontua com o leitor ativo.

Ele existe por dois motivos. Primeiro, `obs ingest` (GDELT) **coleta e não
pontua** — quem pontuava o GDELT era, por acidente, a rodada de RSS, que chama
`link_all` e `score.run` sobre todo o pendente; com `refresh_rss` desligado, a
matéria do GDELT entrava e nunca virava nota. Segundo, com o LLM como leitor
padrão a pontuação passou a ter custo por chamada, e precisa de agenda própria
em vez de pegar carona na rodada de 1 minuto.

Fica no grupo `noticia`: pontuar antes de coletar leria fila velha, e é o grupo
que garante a ordem.

**Isto não afasta a regra acima.** O que segue manual é mandar PDF de relatório
para fora (`report-analyze --externo`). Ler manchete é agora parte do pipeline,
e o teto de `OBS_LLM_MAX_CHAMADAS` é o que limita o custo por rodada.
