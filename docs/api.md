# API local

Servidor local: `obs/api.py`, normalmente em `http://127.0.0.1:8000`.

## Endpoints

### `GET /api/signals?horizonte=d1`
Retorna sinais por ticker e a descrição do horizonte.

### `GET /api/ticker/{TICKER}?horizonte=d1`
Retorna detalhe do ticker, incluindo sinal, notícias, calibração e blocos auxiliares.

### `GET /api/chart/{TICKER}?dias=365`
Retorna série para gráfico de preço e eventos.

### `GET /api/surpresas?indicador=IPCA`
Retorna surpresa macro doméstica, betas históricos e impacto implicado por papel.

**Atenção:** `impacto implicado` não é sinônimo de previsão validada. O payload deve trazer `validado`, `instavel` e o motivo.

### `GET /api/externos`
Retorna o estado de CPI EUA, Payroll EUA e PMI China.

**Atenção:** um evento externo pode ter efeito contemporâneo e ainda assim não ser utilizável para previsão.

### `GET /api/calendario/{TICKER}`
Retorna divulgações corporativas disponíveis no calendário.

### `GET /api/alarms`
Retorna os alarmes registrados.

### `GET /api/status`
Retorna saúde do pipeline, métricas e status das camadas.

## Contrato de transparência

Todo endpoint que devolve valor experimental deve expor:
- `ativo`;
- `validado` ou `pode`;
- origem do dado;
- timestamp;
- métrica de validação;
- motivo de bloqueio, se houver.
