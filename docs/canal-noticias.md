# Canal de notícias: plano para sair de “em aberto”

## Camada setorial (2026-10-02)

Terceira forma de uma notícia alcançar um papel, ao lado de empresa e driver
macro. Resolve um buraco real: o ligador de entidades exige que o texto
**nomeie** a companhia, então "nova regra de capital para bancos" não virava
sinal para ITUB4, BBDC4 nem BBAS3 — embora atinja os três.

### Por que setor é a granularidade certa para este alvo

O alvo é o retorno residual **transversal** (ação menos a média das outras):

| granularidade | efeito no alvo |
|---|---|
| macro (move todas) | **cancela por construção** — explica as 6 reprovações da surpresa macro |
| **setor** (move um subconjunto) | **sobrevive** |
| empresa (move uma) | sobrevive |

`sector` já existia em `config/watchlist.yml` desde o início, mas só era usado
para **imprimir na tela**: nenhum módulo de coleta, ligação ou pontuação o lia.

### Como funciona

`routing.TOPICOS_SETOR` define termos PT e EN por setor. `ingest.fetch_setorial`
faz **uma consulta por setor** e distribui para todos os papéis que pertencem a
ele, carimbando `driver = "setor:<nome>"` — reaproveitando a maquinaria de peso
que o roteamento por driver já usa em `aggregate.py`.

Verificado com resposta simulada: notícia de regulação bancária → ITUB4, BBDC4
e BBAS3, peso 0,35 cada. **Não validado contra o GDELT ao vivo** — ele estava
bloqueando por throttle (8 setores, 8 falhas, 181s, zero artigos).

`PESO_SETOR = 0.35` é **palpite**, não medição: notícia setorial atinge o papel
por pertencimento, não por citação. Falta medir se acrescenta sinal.

### Custo

| camada | consultas por rodada |
|---|---|
| empresa (lotes de 4) | 3 |
| driver macro (deduplicado) | 10 |
| **setor** | **8** |
| total | 21 (~116s de espera imposta pelo GDELT) |

Antes das otimizações de hoje eram 48 consultas e 264s — a camada setorial
entrou e a rodada ainda ficou mais rápida.

## Objetivo

Testar se o texto da notícia acrescenta informação **fora da amostra** à previsão de:
1. magnitude/volatilidade em D+1;
2. direção anormal em D+1;
3. retorno anormal em D+5 e D+20.

A hipótese prioritária é **magnitude**, não direção. O projeto já observou que volatilidade é mais previsível que direção.

## O que precisa existir antes do primeiro backtest

- corpo do artigo quando permitido;
- URL, domínio, idioma e timestamps;
- ticker ou driver associado;
- cluster de duplicatas;
- primeira publicação por cluster;
- score de evento estruturado;
- preço ajustado e retorno anormal futuro;
- separação entre fonte original, citação e republicação.

## Features mínimas

### Conteúdo
- direção da implicação para a empresa;
- tipo de evento: resultado, guidance, M&A, dividendo, regulação, operação, distress etc.;
- materialidade relativa ao tamanho da empresa;
- rumor/especulação;
- retrospectiva ou fato já precificado;
- surpresa contra expectativa quando existir consenso.

### Estrutura de propagação
- primeira publicação;
- número de fontes independentes;
- diversidade de domínios;
- velocidade de replicação;
- concentração por veículo;
- novidade semântica frente a clusters anteriores;
- idade da informação.

### Contexto
- volatilidade anterior do papel;
- liquidez e spread estimado;
- exposição a drivers;
- alavancagem, tamanho, margem e free float;
- regime de mercado, somente como controle testável.

## Desenho experimental

1. Formar eventos por `(ticker, cluster, primeira_publicação)`.
2. Fazer corte temporal de treino, validação e teste; aplicar embargo.
3. Treinar baseline sem texto.
4. Adicionar conteúdo textual.
5. Adicionar propagação/psicologia.
6. Comparar ganho incremental no mesmo período de teste.
7. Repetir por setor e por horizonte.

## Critério de êxito

O canal passa se houver:
- ganho incremental de IC ou AUC;
- Brier skill não pior;
- efeito por decis monotônico;
- resultado superior à nula por permutação;
- estabilidade temporal;
- sobrevivência a testes de notícia deslocada no tempo.

## Critério de parada

Se texto completo, entidade, clusterização e materialidade não gerarem ganho incremental fora da amostra, o canal deve ser classificado como produto de pesquisa/explicação, não como sinal preditivo.

## Ordem prática

1. Coletar corpos e timestamps confiáveis.
2. Rotular 3.000–10.000 artigos com schema estruturado e amostra humana de auditoria.
3. Rodar baseline léxico.
4. Rodar LLM somente como rotulador/extrator.
5. Destilar para modelo menor ou regras auditáveis.
6. Medir primeiro volatilidade e materialidade; só depois direção.
