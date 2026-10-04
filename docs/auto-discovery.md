# Descoberta automática de empresas e documentos

## Fontes

1. **CVM cadastro**: `obs universe-cvm` baixa emissores/CNPJ.
2. **CVM ITR/DFP**: `obs contabil-sync --ano AAAA --tipo ITR|DFP` baixa números estruturados para CNPJs validados.
3. **RI oficial**: `obs ri-sync --ticker TICKER` rastreia somente o domínio de RI registrado em `config/empresas.yml`, cadastra URLs e baixa automaticamente respostas PDF validadas por MIME/assinatura.

## Segurança de fonte

- Nenhuma busca aberta ou URL inventada pela IA é usada para coletar documento.
- O crawler aceita somente URL com o mesmo domínio do RI configurado.
- Links descobertos são cadastrados com origem; respostas identificadas como PDF são baixadas automaticamente e recebem hash.
- CVM é fonte primária; RI é enriquecimento documental.

## Comandos

```bash
python -m obs.cli universe-cvm
python -m obs.cli ri-sync --ticker PETR4
python -m obs.cli contabil-sync --ano 2026 --tipo ITR
```

## Limites atuais

O cadastro CVM não fornece por si só uma lista de tickers líquidos. A ativação de 150–300 papéis exige reconciliação de ticker, preço e volume financeiro.
