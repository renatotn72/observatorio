# Macro e pesos de impacto

## Resposta curta

Há três camadas diferentes. Não misturá-las é essencial.

1. **Drivers de mercado internacionais diários**: possuem exposição por ação e são integrados ao roteamento.
2. **Surpresas macro brasileiras com consenso Focus**: podem estar ligadas por configuração, mas os testes transversais documentados reprovaram.
3. **Eventos internacionais agendados (CPI EUA, Payroll, PMI China)**: possuem testes de atribuição, mas não entram no sinal preditivo.

## 1. Drivers internacionais diários: integrados como força de roteamento

`obs/drivers.py` estima, para cada ação:

```text
beta_j  = sensibilidade padronizada ao driver j
share_j = |beta_j| / soma_k |beta_k|
```

O `share` é a força relativa da exposição de uma ação ao driver.  
No roteamento de notícias, a agregação aplica:

```text
peso_noticia_roteada = peso_textual × share_do_driver
sinal_efetivo = sinal_textual × sinal(beta)
```

Logo, a mesma notícia sobre petróleo pode receber força maior para PETR4 que para uma empresa pouco exposta; se o beta for negativo, a direção textual é invertida.

### Limite de interpretação
Esse peso é **mecanicamente coerente com a exposição estimada**, mas não prova que todos os drivers sejam preditores diretos. No histórico do projeto, a exposição cambial foi a única sobrevivente do teste rigoroso; metais, energia e o conjunto de 14 drivers não demonstraram sinal direcional robusto.

## 2. Surpresas macro brasileiras: integração experimental

No código atual, `obs/surpresa.py` pode estar configurado com `ATIVO=True`. Quando habilitada:

- `PESO_SURPRESA = 0.12`;
- meia-vida de 10 dias;
- teto de 30% do peso total do sinal;
- o impacto por ação parte de `beta_da_ação × surpresa_normalizada`, com demeamento transversal.

O teto evita que um indicador mensal sem notícia específica domine o painel.

### Estado de evidência
A implementação de um peso não torna o peso “correto” empiricamente. Os testes documentados para IPCA, IGP-M, desemprego e câmbio não superaram a nula de permutação. Portanto, se a camada estiver ligada, seu status correto é:

```text
experimental / não validada / não usar para probabilidade ou alarme
```

O produto deve exibir o p-valor, o número de divulgações e a marca de instabilidade.

## 3. Eventos macro internacionais: ainda não integram o sinal

`obs/externo.py` usa o movimento contemporâneo de DXY ou HSI como proxy de surpresa para CPI EUA, Payroll EUA e PMI China.

- Payroll EUA apresentou efeito de dispersão entre ações.
- Porém a proxy é o movimento do instrumento no **mesmo dia** do retorno da ação.
- Portanto ela explica ou atribui o movimento já ocorrido; não é conhecida antes dele.

Por isso `externo.ATIVO = False` e o endpoint `/api/externos` expõe estado e evidência, mas a camada não soma força ao `z` agregado.

## O que falta para peso internacional ser preditivo

Para um evento externo entrar como impacto de força preditivo, é necessário:

1. calendário com datas reais;
2. consenso disponível antes da divulgação;
3. surpresa padronizada: `(realizado - consenso) / dispersão`;
4. beta por ação estimado apenas no passado;
5. teste fora da amostra contra a hipótese nula;
6. cap de contribuição e decaimento;
7. separação entre direção, volatilidade e atribuição.

Sem consenso pré-evento, o movimento do DXY não pode ser usado como feature ex-ante de direção. Pode ser usado como:
- tag de atribuição;
- contexto de volatilidade;
- critério de investigação posterior.


## Atualização de implementação: calendário de Payroll

A versão documentada inclui uma feature candidata na cabeça de volatilidade:

```text
Payroll EUA agendado no dia-alvo = 1
caso contrário = 0
```

Ela usa somente calendário aproximado conhecido antes do evento; não utiliza retorno do
DXY, HSI, valor realizado ou consenso. Por isso não sofre a circularidade da proxy
contemporânea.

A feature invalida calibradores antigos de volatilidade e exige novo
`calibrate-vol`. Ela não altera `z`, `P(alta)` ou `P(queda)`. Só poderá alterar
probabilidades de agitação se o novo walk-forward aprovar AUC, intervalo e Brier skill.
