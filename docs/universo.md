# Universo de 150–300 empresas

## Cadastro CVM

`python -m obs universe-cvm` baixa o cadastro aberto de companhias da CVM e grava uma cópia em `data/universe_cvm.csv`.

O cadastro identifica emissores e CNPJ. Ele **não é uma lista investível de ações líquidas** e pode não fornecer o ticker negociado no formato necessário ao projeto.

## Lista de candidatas

Importe um CSV com:

```text
ticker,nome,cnpj,setor,volume_medio
```

Comando:

```text
python -m obs universe-import --file universo.csv
```

A lista fica em `config/universe_candidates.csv`, sem alterar a watchlist ativa.

## Ativação responsável

Antes de mover empresas da lista candidata para a watchlist:

1. reconciliar ticker e CNPJ;
2. obter histórico de preço;
3. medir volume financeiro médio e spread;
4. remover ações sem histórico suficiente;
5. dividir treino/teste no tempo;
6. ativar por lotes setoriais;
7. documentar data de entrada no universo.

A CVM é a fonte de cadastro e documentos; a liquidez deve vir de dados de negociação/preço.
