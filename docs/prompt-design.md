# Prompt para o time de design

Copie daqui para baixo.

---

## Contexto

Observatório de Ações: painel de pesquisa que estima, para ~10 ações da B3,
a probabilidade de **alta**, de **queda** e de **agitação** (movimento grande,
sem dizer o lado), a partir de notícias e de fatores macro.

É um projeto acadêmico de mestrado/TCC reaproveitado, não um produto
financeiro. **Não recomenda compra nem venda.** O público é uma pessoa
pesquisando, não operando.

## A restrição que define este projeto

Quase tudo que o sistema mede **não funciona**, e isso é exibido, não
escondido. O placar atual:

| cabeça | estado | desempenho medido |
|---|---|---|
| **Agitação** | calibrada, aprovada | **38 acertos em 100** no topo 5%, contra 19,7 de taxa-base |
| Alta | **não calibrada** | — |
| Queda | **não calibrada** | — |
| Surpresa macro | ligada, mas **reprovada** no teste | p entre 0,45 e 0,79 |

Doze hipóteses testadas foram reprovadas. Três passaram.

**A ausência de número é conteúdo, não lacuna.** Quando `p_up` vem `null`,
significa "não há evidência suficiente para afirmar". O design NÃO pode
preencher esse espaço com estimativa, barra cinza de placeholder, "—" tímido
ou qualquer coisa que o olho leia como "ainda carregando". Tem de ser um
estado **deliberado e legível**.

Este é o requisito mais importante do briefing. Se o design induzir o usuário
a achar que existe uma previsão de direção, ele falhou — por mais bonito que
esteja.

## Dados reais que a tela recebe

`GET /api/signals` devolve um registro por papel:

```json
{
  "ticker": "PETR4", "name": "Petrobras", "sector": "oil_gas",
  "z": 0.3265,              // sinal agregado das notícias (-1 a +1)
  "n_eff": 0.7328,          // peso efetivo (NÃO é contagem)
  "n_articles": 15,         // contagem bruta de matérias
  "dispersion": 0.2923,     // discordância entre as fontes
  "cadeia_top": "BRENT",    // driver macro dominante do papel

  "p_up": null, "p_down": null, "p_flat": null,   // direção: SEM CALIBRAÇÃO
  "base_up": null, "base_down": null,
  "calibrated": 0,

  "p_vol": 0.2035,          // agitação: ESTA é confiável
  "vol_base": 0.198,        // taxa-base: o que o acaso daria
  "vol_calib": 1,           // 1 = calibrador aprovado na porta

  "surpresa_contrib": 0.0215, "surpresa_peso": 0.2198
}
```

Outras rotas: `/api/status` (saúde e medições), `/api/ticker/{t}` (detalhe),
`/api/chart/{t}`, `/api/alarms`, `/api/surpresas`, `/api/calendario/{t}`,
`/admin.html` (Central de Operações: agendar e rodar tarefas).

## O que precisa ser resolvido

### 1. Dois regimes visuais: medido e não medido

O usuário tem de distinguir, **em menos de um segundo**, o número com lastro
do número sem lastro. Hoje tudo parece igualmente confiável.

- `p_vol` com `vol_calib: 1` → número com credibilidade, mostrado **sempre ao
  lado da taxa-base** (`vol_base`). "20,4% contra base de 19,8%" informa;
  "20,4%" sozinho engana, porque parece alto e é igual ao acaso.
- `p_up` com `calibrated: 0` → estado explícito de "não calibrado", com acesso
  ao porquê.

### 2. A agitação é o produto, e não parece

É a única coisa que funciona, e hoje divide espaço igualmente com duas cabeças
vazias. A hierarquia visual está invertida em relação à hierarquia de
evidência.

Atenção: agitação **não tem direção**. Não pode usar verde/vermelho, seta,
nem qualquer código que o mercado associa a subir/descer.

### 3. `n_eff` contra `n_articles`

`n_eff: 0.73` com `n_articles: 15` significa que 15 matérias valeram peso
efetivo 0,73 — porque são repetições da mesma notícia, ou antigas, ou de
veículo de pouco peso. Essa diferença é informação valiosa e hoje é invisível.

### 4. A camada que está ligada e reprovada

`surpresa_contrib` entra no sinal por decisão do usuário, mas **falhou no
teste de permutação** (p = 0,508). Precisa aparecer com essa ressalva colada
ao número — não numa nota de rodapé que ninguém lê.

### 5. A cadeia de afetação

Cada papel reage a fatores macro com peso e sinal (PETR4 é 49% Brent). Hoje é
uma lista. Deveria responder visualmente *"por que este papel se move"*, que é
o entregável mais confiável do sistema depois da agitação.

### 6. Central de Operações

`/admin.html` é funcional e feia. Tarefas agendáveis, com janela de horário,
histórico de execução, e algumas que **nunca devem rodar sozinhas**
(recalibração). Precisa dessa distinção clara.

## Restrições técnicas

- **Sem framework.** HTML, CSS e JavaScript puros. Sem React, sem build.
  O servidor é Python de biblioteca padrão.
- **Sem CDN.** Roda em máquina local, às vezes sem internet.
- Telas existentes: `web/index.html`, `web/acao.html`, `web/admin.html`.
- Desktop é o uso principal; responsivo é desejável, não crítico.
- Português do Brasil.

## O que NÃO fazer

- Não inventar número onde a API manda `null`.
- Não usar verde/vermelho nem setas para agitação (ela não tem lado).
- Não transformar em painel de trading: nada de "comprar/vender", preço-alvo,
  carteira sugerida ou sinal de entrada.
- Não esconder incerteza atrás de ícone de informação. Ela é o conteúdo.
- Não usar número grande e colorido para dado não calibrado.

## Entrega

1. Hierarquia proposta da tela principal, com justificativa.
2. Como distinguir visualmente medido / não medido / reprovado.
3. Tratamento da cadeia de afetação.
4. Protótipo em HTML+CSS puro de ao menos a tela principal.

## Critério de aceite

Alguém que nunca viu o sistema deve, olhando a tela por 30 segundos,
responder certo:

1. Quais papéis têm chance maior de se mexer bastante amanhã?
2. O sistema sabe dizer se vão subir ou cair? **(resposta correta: não)**
3. De onde vem a informação?

Se a pessoa responder "sim" à pergunta 2, o design falhou.
