# Documentação do Observatório de Ações

**Versão documental:** 4 de outubro de 2026  
**Escopo:** arquitetura, fontes, validação, métricas, decisões, API, canal de notícias e camadas macro.

## Como ler esta documentação

O projeto é um **observatório de pesquisa**. Ele não deve ser apresentado como recomendação de investimento nem como sistema de retorno líquido comprovado.

A documentação separa quatro estados:

- **Medido e aprovado:** passou no protocolo definido.
- **Medido e reprovado:** foi testado e não deve receber peso preditivo.
- **Implementado, não validado:** existe no código/painel, mas não há evidência suficiente.
- **Hipótese de pesquisa:** proposta de feature ou experimento.

## Mapa de documentos

- [Parecer técnico](parecer.md): leitura crítica do projeto inteiro, placar da
  evidência e a decisão sobre quem lê a notícia (4 de outubro de 2026).
- [Arquitetura](arquitetura.md): pipeline, armazenamento e agregação.
- [Fontes de dados](fontes-de-dados.md): origem, papel e limitações.
- [Validação](validacao.md): protocolo anti-vazamento e critérios de aceite.
- [Métricas](metricas.md): IC, AUC, Brier, acerto e custo.
- [Log de decisões](decision-log.md): escolhas, bugs corrigidos e portas.
- [API](api.md): endpoints locais.
- [Canal de notícias](canal-noticias.md): plano de medição contra retorno realizado.
- [Classificação de eventos](eventos.md): orientação temporal e tipo de evento,
  as duas dimensões independentes que o gráfico desenha.
- [Orientação x retorno](orientacao-medicao.md): a notícia de passado explica o
  passado? A de futuro prevê? Medido — nada passa.
- [Fontes prospectivas](fontes-prospectivas.md): avaliação do radar judicial,
  legislativo e do calendário contábil — recomendação, nada implementado.
- [Psicologia e propagação](psicologia.md): hipóteses do TCC de 2013 convertidas em features testáveis.
- [Macro e pesos](macro.md): drivers, surpresas domésticas e eventos internacionais.
- [Direção](direcao.md): hipóteses para elevar acerto sem multiplicar testes.

- [Relatórios e IA](relatorios.md): PDFs locais, extração e análise com autorização explícita.

- [PEAD](pead.md): consenso, realizado e surpresa trimestral.

- [Universo](universo.md): cadastro CVM, CSV de candidatas e filtro de liquidez.

- [Implementação configurada](implementacao-configurada.md): o que foi entregue, bloqueado e por quê.

- [Descoberta automática](auto-discovery.md): CVM, ITR/DFP e domínio oficial de RI.

- [Central de Operações](operacoes.md): fila, worker, agenda e jobs permitidos.

- [Proxy SAI](proxy-sai.md): mcp-models.properties, modo raw e integração de relatórios.

## Regra de ouro

Nenhuma feature entra como probabilidade, alerta operacional ou promessa de retorno sem:
1. timestamp disponível antes do alvo;
2. teste temporal fora da amostra;
3. comparação com baseline;
4. teste de robustez/permutação quando aplicável;
5. registro da métrica e do script em `obs/medidas.py`.
