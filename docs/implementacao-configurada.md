# Implementação por configuração — 1 de outubro de 2026

## Configuração escolhida

- IA: API compatível com OpenAI.
- Permissão externa: **não autorizada**.
- Consenso de resultados: **ainda indisponível**.
- Universo: cadastro CVM + CSV; expansão para 150–300 ações somente após filtro de liquidez.

## Entregue nesta versão

- Registro e visualização por empresa de PDFs locais e links remotos.
- Extração local de texto de PDF.
- Análise local por termos e adaptador para IA externa bloqueado por padrão.
- API/UI para relatórios, plano contábil e surpresa trimestral.
- Estrutura de consenso, realizado e surpresa PEAD.
- Importação de CSV de consenso com timestamp `asof_date`.
- Dados contábeis ITR/DFP via CVM, mediante CNPJ explicitamente validado.
- Cadastro CVM de emissores e importação de CSV de universo candidato.
- Calendário externo de Payroll como feature candidata da volatilidade, ainda sujeito a walk-forward.
- Rótulos D+1, D+5 e D+20 por comando.

## Não ativado por falta de dado ou validação

- Chamada à IA externa: requer autorização e variáveis de ambiente.
- PEAD como sinal: requer consenso prévio e backtest.
- Ampliação automática para 150–300: CVM não é filtro de liquidez; exige volume/histórico.
- Pesos de fonte aprendidos e relações cliente-fornecedor: continuam experimentos de pesquisa.
- Qualquer nova probabilidade de alta/queda: bloqueada até aprovação no protocolo.
