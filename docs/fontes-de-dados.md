# Fontes de dados

## Mercado e drivers

| Fonte | Uso | Papel no projeto | Limitação principal |
|---|---|---|---|
| Yahoo Finance | Preços de ações B3, índices, commodities, câmbio e ADRs | histórico, retornos e drivers | não é feed institucional garantido para execução em tempo real |
| GDELT 2.0 | Notícias e metadados globais | descoberta de títulos e roteamento | atraso e ausência de corpo do artigo |
| RSS/Atom | Notícias de fontes selecionadas | cobertura adicional e, em alguns feeds, resumo | cada fonte tem cobertura e horário próprios |
| BCB Olinda / Focus | consenso, dispersão e respondentes | surpresa macro brasileira | requer corte temporal rigoroso para não usar consenso pós-divulgação |
| BCB SGS | valor realizado de indicadores | denominador/resultado da surpresa brasileira | unidades precisam coincidir com o Focus |
| DBnomics | séries macro internacionais | histórico e pesquisa | alguns espelhos podem ter defasagem |
| CVM Dados Abertos | ITR, DFP, demonstrações e composição acionária | fundamentos e contexto de materialidade | periodicidade trimestral e necessidade de padronização |

## Regras de qualidade

1. Armazenar fonte, URL, idioma, `published_ts` e `ingested_ts`.
2. Registrar unidade, frequência, fuso e horário de fechamento de toda série de preço.
3. Não casar uma barra diária que inclui o pregão brasileiro com o mesmo pregão como se fosse previsão.
4. Usar o valor de consenso disponível **antes** da divulgação.
5. Em fontes internacionais sem consenso acessível, separar:
   - evento contemporâneo explicativo;
   - sinal efetivamente observável antes do retorno.

## Fontes para a documentação externa

Manter, no README principal, referências para:
- Python `http.server`, `sqlite3` e `xml.etree`;
- Requests, NumPy e PyYAML;
- GDELT 2.0;
- BCB Olinda/OData e SGS;
- DBnomics;
- CVM Dados Abertos;
- políticas e disponibilidade do provedor de preços usado.
