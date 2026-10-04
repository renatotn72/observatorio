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

## Atualização de 4 de outubro de 2026

- **Leitura da notícia por LLM: ativada como padrão** (`SCORER_PADRAO = "llm"`),
  com extração estruturada em coluna. Estado de evidência: *implementado, não
  validado*. Ver `docs/parecer.md` e `docs/decision-log.md`.
- A chamada passou a respeitar `OBS_ALLOW_EXTERNAL_LLM`, que antes era ignorada
  pelo scorer — era um defeito, e está registrado como tal.
- Sem autorização, o pipeline continua rodando com o léxico e **anuncia** a
  degradação. A linha "permissão externa: não autorizada" acima descreve a
  configuração padrão, não um bloqueio de pipeline.

## Não ativado por falta de dado ou validação

- Chamada à IA externa para **relatório em PDF**: requer autorização e variáveis
  de ambiente (continua manual, por decisão).
- **Promoção do leitor por LLM a melhoria comprovada**: exige o teste contra
  retorno realizado em janela posterior ao cutoff do modelo.
- PEAD como sinal: requer consenso prévio e backtest.
- Ampliação automática para 150–300: CVM não é filtro de liquidez; exige volume/histórico.
- Pesos de fonte aprendidos e relações cliente-fornecedor: continuam experimentos de pesquisa.
- Qualquer nova probabilidade de alta/queda: bloqueada até aprovação no protocolo.
