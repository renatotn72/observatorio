"""Perguntas em linguagem natural sobre o que o painel MEDE.

Tres decisoes que definem este modulo:

1. A IA nao sabe nada por conta propria. Toda resposta sai de um pacote de
   CONTEXTO montado aqui a partir do banco e das medicoes. O que nao esta no
   pacote nao existe para ela -- e o prompt manda dizer isso em voz alta.

2. As regras epistemicas do projeto viram restricao de prompt, nao enfeite.
   Direcao nao calibrada continua nao calibrada quando quem responde e um
   modelo de linguagem: ele e proibido de inferir lado a partir de z, de
   noticia ou da cadeia.

3. A IA PROPOE operacao, nunca executa. Este modulo jamais chama ops.enqueue.
   Ele devolve ids de job validados contra ops.JOBS e a classe de cada um; o
   clique e do humano, pela rota /api/admin/run que ja existia. Recalibracao
   seguir sendo ato deliberado e um requisito do projeto, nao uma preferencia
   de interface.
"""
from __future__ import annotations

import json

from . import llm_client, ops

# Jobs que reescrevem o que o painel publica. Mesma divisao que a tela de
# Operacoes mostra: `schedule: False` em ops.JOBS == nunca roda sozinha.
CLASSE = {j: ("rotina" if d["schedule"] else "deliberada") for j, d in ops.JOBS.items()}

ESCOPOS = ("painel", "papel", "agitacao", "direcao", "evidencia", "cadeia",
           "surpresa", "operacoes")

SISTEMA = """Você é o assistente do Observatório de Ações, um painel ACADÊMICO de pesquisa sobre ~10 papéis da B3. Não é produto financeiro e o público é alguém pesquisando, não operando.

Responda SOMENTE com o que está no JSON de CONTEXTO abaixo. Você não tem conhecimento próprio sobre essas empresas, preços, notícias ou mercado. Se a resposta não estiver no contexto, diga que não está no painel.

REGRAS INEGOCIÁVEIS
1. O sistema NÃO estima direção. p_up, p_down e p_flat vêm nulos e calibrated=0. Se perguntarem se um papel vai subir ou cair, responda que o sistema não sabe dizer, e explique que a cabeça de direção nunca passou na porta de calibração. Nunca dê, sugira ou insinue direção — nem a partir de z, nem de notícia, nem da cadeia de afetação.
2. Não recomende compra, venda, preço-alvo, carteira, momento de entrada ou saída. Se pedirem, recuse em uma frase e ofereça o que o painel de fato mede.
3. Toda probabilidade de agitação (p_vol) é citada JUNTO da taxa-base (vol_base), dizendo se está acima ou abaixo do acaso e por quantos pontos percentuais. Nunca cite p_vol sozinho: isolado ele engana.
4. Agitação é movimento grande SEM LADO. Nunca a descreva como alta, queda, risco de cair ou oportunidade.
5. z é ENTRADA do modelo (tom das notícias), não saída, e não é previsão.
6. Qualquer número da surpresa macro vem com a ressalva de que ela foi REPROVADA no teste de permutação (p = 0,508) na mesma frase em que o número aparece.
7. A cadeia de afetação é DESCRITIVA: descreve co-movimento passado, não entra em nenhuma probabilidade e nunca serve para projetar.
8. n_eff é peso efetivo numa escala de 0 a 1,00 — não é contagem de matérias. n_articles é a contagem bruta.
9. Não invente número nenhum. Não arredonde para parecer mais redondo. Não preencha lacuna com estimativa.

OPERAÇÃO
Você pode PROPOR tarefas do painel; nunca executá-las. Em "acoes" use apenas ids presentes em contexto.operacoes.jobs. Tarefas de classe "deliberada" sobrescrevem o que o painel publica (recalibração, rótulos, experimento): proponha-as somente se o usuário pedir com clareza, e diga no motivo o que será sobrescrito. Na dúvida, não proponha ação.

Responda SOMENTE com um objeto JSON, sem comentário fora dele:
{"resposta": "texto em português do Brasil, direto, no máximo 6 frases",
 "fatos": [{"rotulo": "nome do campo", "valor": "valor citado"}],
 "ressalvas": ["limite que o leitor precisa saber"],
 "acoes": [{"job": "id_do_job", "motivo": "por que rodar agora"}]}
Use no máximo 6 fatos. "ressalvas" e "acoes" podem vir vazios."""


# ------------------------------------------------------------- contexto ---

def _papel_linha(s: dict) -> dict:
    """Uma linha de papel com a leitura ja feita, para a IA nao ter de calcular."""
    pv, vb = s.get("p_vol"), s.get("vol_base")
    d = {
        "ticker": s["ticker"], "nome": s.get("name"), "setor": s.get("sector"),
        "p_vol": pv, "vol_base": vb,
        "agitacao_calibrada": bool(s.get("vol_calib")),
        "z_tom_noticias": s.get("z"), "n_articles": s.get("n_articles"),
        "n_eff_peso_0a1": s.get("n_eff"), "dispersion": s.get("dispersion"),
        "cadeia_top": s.get("cadeia_top"),
        "p_up": s.get("p_up"), "p_down": s.get("p_down"), "p_flat": s.get("p_flat"),
        "direcao_calibrada": bool(s.get("calibrated")),
    }
    if pv is not None and vb is not None:
        d["delta_vs_acaso_pp"] = round((pv - vb) * 100, 1)
        d["acima_do_acaso"] = pv > vb
    return d


def _cabecas(status: dict) -> dict:
    """Estado de cada cabeca, na linguagem dos quatro regimes da tela."""
    ag = status.get("agitacao") or {}
    cal = (ag.get("calibrador") or {}).get("metrics") or {}
    med = status.get("medidas") or {}
    wf = med.get("agitacao_auc_wf") or {}
    sur = status.get("surpresa") or {}
    return {
        "agitacao": {
            "regime": "medido",
            "o_que_e": "probabilidade de o papel ficar no topo 20% de |retorno anormal| em D+1; movimento grande, SEM lado",
            "taxa_base": cal.get("taxa_base_oos"),
            "porta_do_calibrador": {
                "passou": bool(cal.get("calibrado")),
                "auc_oos": cal.get("auc_oos"), "ic95": cal.get("auc_ic95"),
                "skill_brier": cal.get("skill_brier_oos"), "n_oos": cal.get("n_oos"),
                "periodo": cal.get("periodo"),
            },
            "protocolo_estrito_walk_forward": {
                "passou": wf.get("aprovado", False), "auc": wf.get("valor"),
                "motivo": wf.get("motivo"),
            },
            "features": cal.get("features"),
            "atencao": "nenhuma notícia entra na agitação; ela vem do histórico de preços e do painel macro",
        },
        "direcao": {
            "regime": "nao calibrado",
            "o_que_significa": "p_up, p_down e p_flat vêm nulos: ausência de evidência, não falta de dado do dia",
            "rotulos_no_banco": status.get("labels"),
            "porta": {"min_oos": 500, "min_auc": 0.55, "min_skill_brier": 0.01},
            "canal_preco": (med.get("preco_ic") or {}),
        },
        "surpresa_macro": {
            "regime": "reprovado, porem ligado",
            "ativa": sur.get("ativo"), "motivo": sur.get("motivo"),
            "teste": sur.get("teste"),
        },
        "cadeia_de_afetacao": {
            "regime": "descritivo",
            **{k: v for k, v in (status.get("cadeia") or {}).items() if k != "papeis"},
        },
    }


def _operacoes(estado: dict, limite_runs: int = 12) -> dict:
    sch = {s["job"]: s for s in estado.get("schedules", [])}
    jobs = []
    for jid, j in estado.get("jobs", {}).items():
        a = sch.get(jid, {})
        jobs.append({
            "id": jid, "label": j["label"], "classe": CLASSE.get(jid, "rotina"),
            "agendavel": bool(j.get("schedule")),
            "agendada": bool(a.get("enabled")),
            "intervalo_min": a.get("interval_minutes"),
            "janela": f'{a.get("window_start", "?")}-{a.get("window_end", "?")}',
            "dias_uteis": bool(a.get("weekdays_only")),
            "ultima_ts": a.get("last_run_ts"), "ultimo_status": a.get("last_status"),
            "proxima_ts": a.get("next_run_ts"),
        })
    runs = [{k: r.get(k) for k in ("job", "trigger", "status", "queued_ts", "finished_ts")}
            for r in estado.get("runs", [])[:limite_runs]]
    return {"jobs": jobs, "ultimas_execucoes": runs,
            "regra": "jobs de classe 'deliberada' nunca rodam sozinhos e sobrescrevem o que o painel publica",
            "worker": estado.get("worker_note")}


def _detalhe_papel(d: dict, max_itens: int = 10) -> dict:
    """Detalhe de um papel, sem o peso das URLs e com as manchetes podadas."""
    out = {k: v for k, v in d.items() if k != "items"}
    out["manchetes"] = [
        {"titulo": i.get("title"), "veiculo": i.get("domain"), "s": i.get("s"),
         "peso": i.get("w"), "idade_h": i.get("age_h"),
         "tipo_evento": i.get("event_type"), "repeticoes": i.get("cluster_size")}
        for i in (d.get("items") or [])[:max_itens]
    ]
    return out


def montar_contexto(escopo: str, prov, ticker: str | None = None) -> dict:
    """Pacote de fatos que a IA pode usar. `prov` evita import circular com api."""
    escopo = escopo if escopo in ESCOPOS else "painel"
    status = prov.status()
    ctx: dict = {
        "escopo": escopo,
        "horizonte": "D+1 (fechamento a fechamento)",
        "cabecas": _cabecas(status),
        "placar_do_projeto": "12 hipóteses testadas reprovadas, 3 passaram",
    }

    if escopo == "papel" and ticker:
        ctx["papel"] = _detalhe_papel(prov.ticker(ticker))
        return ctx

    if escopo == "operacoes":
        ctx["operacoes"] = _operacoes(prov.ops_state())
        return ctx

    sinais = [_papel_linha(s) for s in prov.signals()]
    if escopo == "agitacao":
        sinais.sort(key=lambda r: (r.get("p_vol") is None, -(r.get("p_vol") or 0)))
        ctx["papeis"] = [{k: v for k, v in r.items()
                          if k in ("ticker", "nome", "p_vol", "vol_base",
                                   "delta_vs_acaso_pp", "acima_do_acaso",
                                   "agitacao_calibrada")} for r in sinais]
    elif escopo in ("direcao", "evidencia"):
        ctx["papeis"] = [{k: v for k, v in r.items()
                          if k in ("ticker", "nome", "z_tom_noticias", "n_articles",
                                   "n_eff_peso_0a1", "dispersion", "p_up", "p_down",
                                   "direcao_calibrada")} for r in sinais]
    elif escopo == "cadeia":
        ctx["papeis"] = [{k: v for k, v in r.items()
                          if k in ("ticker", "nome", "setor", "cadeia_top")} for r in sinais]
        ctx["nota"] = (status.get("cadeia") or {}).get("nota")
    elif escopo == "surpresa":
        ctx["papeis"] = [{k: v for k, v in r.items()
                          if k in ("ticker", "nome", "cadeia_top")} for r in sinais]
        ctx["surpresa"] = status.get("surpresa")
    else:                                            # painel
        ctx["papeis"] = sinais
        ctx["contagens"] = {k: status.get(k) for k in
                            ("articles", "mentions", "scores", "labels", "prices", "alarms")}
        ctx["operacoes"] = _operacoes(prov.ops_state(), limite_runs=5)
    return ctx


# -------------------------------------------------------------- resposta ---

def _valida_acoes(acoes) -> list[dict]:
    """So passam jobs que existem. A IA nao inventa tarefa, e nao executa nenhuma."""
    out, vistos = [], set()
    for a in (acoes or [])[:4]:
        if not isinstance(a, dict):
            continue
        jid = str(a.get("job") or "").strip()
        if jid not in ops.JOBS or jid in vistos:
            continue
        vistos.add(jid)
        out.append({"job": jid, "label": ops.JOBS[jid]["label"],
                    "classe": CLASSE[jid], "motivo": str(a.get("motivo") or "")[:300]})
    return out


def estado() -> dict:
    ok, motivo = llm_client.enabled()
    return {"ok": ok, "motivo": motivo,
            "nota": ("A IA responde apenas com o pacote de contexto montado pelo servidor "
                     "e nunca executa tarefa: ela propõe, o clique é humano.")}


def responder(pergunta: str, prov, escopo: str = "painel", ticker: str | None = None,
              max_tokens: int = 1100) -> dict:
    pergunta = (pergunta or "").strip()[:600]
    ctx = montar_contexto(escopo, prov, ticker)
    base = {"escopo": escopo, "ticker": ticker, "contexto": ctx}
    if not pergunta:
        return {**base, "ok": False, "error": "pergunta vazia"}

    ok, motivo = llm_client.enabled()
    if not ok:
        # Sem IA o pacote de contexto continua indo para a tela: o usuario ve os
        # mesmos fatos que o modelo veria. A ausencia e declarada, nao mascarada.
        return {**base, "ok": False, "error": motivo, "ia_desligada": True}

    user = (f"CONTEXTO (único material permitido):\n"
            f"{json.dumps(ctx, ensure_ascii=False, separators=(',', ':'))}\n\n"
            f"PERGUNTA DO USUÁRIO:\n{pergunta}")
    r = llm_client.chat_json(SISTEMA, user, max_tokens=max_tokens)
    if not r.get("ok"):
        return {**base, "ok": False, "error": r.get("error", "falha na chamada")}

    d = r.get("data") or {}
    fatos = [f for f in (d.get("fatos") or []) if isinstance(f, dict)][:6]
    return {**base, "ok": True, "model": r.get("model"),
            "resposta": str(d.get("resposta") or "").strip(),
            "fatos": [{"rotulo": str(f.get("rotulo") or ""), "valor": str(f.get("valor") or "")}
                      for f in fatos],
            "ressalvas": [str(x) for x in (d.get("ressalvas") or [])][:4],
            "acoes": _valida_acoes(d.get("acoes"))}
