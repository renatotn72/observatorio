# Central de Operações

Abra `http://127.0.0.1:8000/admin.html`.

## Worker

O painel cria apenas jobs autorizados no SQLite. Para consumi-los:

```bash
python -m obs.cli worker --seconds 20
```

Não existe executor de comandos arbitrários.

## Agenda

Jobs agendáveis podem ter intervalo configurado no formulário. O mínimo é 5 minutos.
A primeira implementação considera dias úteis (segunda a sexta); feriados B3 precisam de
calendário específico antes de bloqueio automático.

Backtests, recalibrações e análise externa de IA são deliberadamente manuais.
