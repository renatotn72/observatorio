# Direção: hipóteses para aumentar acerto de alta e queda

## Princípio

Direção diária em D+1 é o alvo mais difícil. A melhoria deve ser medida por incremento
fora da amostra sobre a referência existente, e não por uma lista extensa de features.

Não adicionar todas as hipóteses de uma vez. Cada item abaixo deve ser um experimento com
baseline, corte temporal, embargo e teste de permutação.

## Prioridade alta

1. **Surpresa de resultados trimestrais (PEAD)**
   - `realizado - consenso` por empresa, normalizado pela dispersão.
   - Melhor chance de efeito em dias/semanas, não somente no leilão.
   - Bloqueio: consenso de analistas; alternativa é modelo próprio de expectativa,
     explicitamente mais fraco.

2. **Corpo do artigo + schema de evento**
   - Materialidade, fato novo, rumor, guidance, valor financeiro, causalidade e
     “já precificado”.
   - Título informa o fato; corpo permite medir tamanho e condição.

3. **Horizontes D+5 e D+20**
   - Um efeito de notícia pode se propagar além da abertura.
   - Avaliar retorno líquido de custo, não só IC.

4. **Surpresa macro com consenso pré-divulgação**
   - Usar apenas expectativa disponível antes da divulgação.
   - Para exterior, não usar retorno diário contemporâneo de DXY como surpresa.

5. **Pesos de fonte aprendidos**
   - Aprender por `(fonte, tipo de evento)` ou `(fonte, driver)`.
   - Medir independência e antecedência, não popularidade manual.

## Prioridade média

6. **Roteamento por cadeia de afetação**
   - Conectar notícias de OPEP, minério, China e dólar aos papéis expostos.
   - Medir se aumento de cobertura preserva IC por evento.

7. **Estrutura de propagação e psicologia**
   - Primeira publicação, diversidade de fontes, velocidade de cascata,
     medo/incerteza, framing e novidade.
   - Espera-se mais valor para magnitude; direção é hipótese a testar.

8. **Universo de 150–300 ações líquidas**
   - Aumenta poder estatístico, diversificação e chance de captar sub-reação.
   - Não “cria” IC; reduz a incerteza da sua estimativa.

9. **Relações econômicas reais**
   - Cliente–fornecedor, insumo–produtor, cadeia de exportação.
   - Não repetir correlação bruta entre pares de ações.

10. **Contexto de empresa**
    - Dívida líquida/EBITDA, tamanho, free float, margem e liquidez.
    - Usar primeiro como interação de materialidade e volatilidade; direção
      precisa de evidência própria.

## Itens que não devem ser prioridade

- acrescentar muitos drivers macro;
- voltar à árvore sintática;
- usar FinBERT apenas por ser um modelo financeiro;
- religar meta-label sem novas features de regime e monotonicidade;
- tratar cópias de notícia como confirmações independentes.

## Critério de sucesso

Uma hipótese só entra na cadeia direcional se:
- melhora IC/AUC/Brier em teste temporal;
- melhora sobre o baseline preço/drivers;
- mantém direção de efeito em janelas posteriores;
- sobrevive a agrupamento por dia e permutação;
- apresenta retorno líquido plausível no horizonte escolhido.
