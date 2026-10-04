"""Calibracao sinal -> probabilidade, por regressao isotonica (PAVA).

Implementada a mao: sklearn nao esta disponivel, e sao ~40 linhas.

Isotonica em vez de logistica porque nao exigimos forma funcional -- so que
"mais sinal positivo => nao menos chance de alta". E o minimo defensavel.

REGRA DE OURO: o calibrador tem de ser ajustado SO com dados anteriores ao
periodo avaliado. Por isso `fit(until_ts=...)` existe e o backtest o usa em
janela deslizante. Ajustar na amostra toda e se auto-enganar.
"""
from __future__ import annotations
import json
import math

from .db import connect
from .label import base_rates
from .util import now_ts

MIN_N = 120          # abaixo disso a isotonica so decora ruido
# PORTA DE DESEMPENHO DA DIRECAO. Ate hoje nao existia: `fit` calculava
# skill_up e skill_down e GRAVAVA o calibrador de qualquer jeito, entao bastava
# juntar 120 rotulos para o painel comecar a publicar probabilidade -- mesmo
# com skill negativo, isto e, pior que repetir a taxa-base. A agitacao sempre
# teve porta (CAL_MIN_* em volatility.py); a direcao nao tinha, e e justamente
# a cabeca sem evidencia a favor.
#
# O LIMIAR NAO PODE SER ZERO. A primeira versao usava `> 0.0`, e isso nao e
# porta: qualquer flutuacao positiva passa. MEDIDO logo em seguida -- a direcao
# foi APROVADA com skill_up = +0,0004, quatro decimos de milesimo acima do
# chute, indistinguivel de ruido com n = 752.
#
# O piso de 0,01 nao foi escolhido para dar o resultado que eu esperava: e o
# MESMO da agitacao (volatility.CAL_MIN_SKILL), definido antes e por outro
# motivo. E o projeto ja REPROVOU a agitacao num protocolo com skill +0,005
# por esse criterio -- aceitar +0,0004 na direcao seria usar duas reguas
# diferentes para a mesma pergunta.
MIN_SKILL = 0.01     # skill de Brier em AMBOS os lados, igual a agitacao
SHRINK_K = 2.0       # peso da taxa-base no encolhimento


def pava(xs: list[float], ys: list[float]) -> list[tuple[float, float]]:
    """Pool Adjacent Violators. Devolve nos (x, p) monotonos nao-decrescentes.

    Duas sutilezas, ambas descobertas por skill NEGATIVO dentro da amostra --
    o que para isotonica e impossivel, ja que a taxa-base constante e sempre
    uma solucao monotona viavel:

    1. x DUPLICADOS tem de ser agregados (media ponderada) ANTES da PAVA. Sem
       isso dois pontos com o mesmo x podem cair em blocos diferentes, e o
       ajuste deixa de ser funcao de x -- dois nos com o mesmo x e valores
       diferentes, e `predict` escolhe um deles na sorte.
    2. A PAVA produz uma funcao ESCADA, constante dentro do bloco. Cada bloco
       emite DOIS nos, (x_min, v) e (x_max, v); guardar so a borda direita e
       interpolar entre bordas desloca o ajuste inteiro.
    """
    # 1) agrega x iguais
    agg: dict[float, list[float]] = {}
    for x, y in zip(xs, ys):
        a = agg.setdefault(x, [0.0, 0.0])      # [soma_y, peso]
        a[0] += y
        a[1] += 1.0
    pts = sorted((x, sy / w, w) for x, (sy, w) in agg.items())

    # 2) PAVA ponderada.  bloco = [media, peso, x_min, x_max]
    blocks = [[y, w, x, x] for x, y, w in pts]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] <= blocks[i + 1][0] + 1e-12:
            i += 1
            continue
        a, b = blocks[i], blocks[i + 1]
        w = a[1] + b[1]
        blocks[i:i + 2] = [[(a[0] * a[1] + b[0] * b[1]) / w, w, a[2], b[3]]]
        if i > 0:
            i -= 1

    # 3) dois nos por bloco => interpolacao linear reproduz a escada
    knots: list[tuple[float, float]] = []
    for v, _w, xmin, xmax in blocks:
        knots.append((xmin, v))
        if xmax > xmin:
            knots.append((xmax, v))
    return knots


def predict(knots: list[tuple[float, float]], x: float) -> float:
    """Interpolacao linear entre nos, com clamp fora do dominio."""
    if not knots:
        return float("nan")
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for i in range(1, len(knots)):
        x0, p0 = knots[i - 1]
        x1, p1 = knots[i]
        if x <= x1:
            if x1 == x0:
                return p1
            t = (x - x0) / (x1 - x0)
            return p0 + t * (p1 - p0)
    return knots[-1][1]


def platt(xs: list[float], ys: list[float], iters: int = 60) -> tuple[float, float]:
    """Escala de Platt: regressao logistica de 1 feature por IRLS/Newton.

    Existe porque a isotonica, com algumas centenas de eventos, DECORA: no
    backtest walk-forward ela chega a ficar com skill de Brier negativo fora da
    amostra mesmo havendo sinal verdadeiro. Dois parametros generalizam melhor
    que 25 nos nesse regime. Devolve (a, b) de P = sigmoid(a*x + b).
    """
    a, b = 0.0, math.log(max(1e-6, sum(ys)) / max(1e-6, len(ys) - sum(ys)))
    for _ in range(iters):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for x, y in zip(xs, ys):
            z = a * x + b
            pz = 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))
            r = pz - y
            w = max(1e-9, pz * (1.0 - pz))
            g_a += r * x;  g_b += r
            h_aa += w * x * x;  h_ab += w * x;  h_bb += w
        h_aa += 1e-6; h_bb += 1e-6                      # regularizacao
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        da = (g_a * h_bb - g_b * h_ab) / det
        db = (g_b * h_aa - g_a * h_ab) / det
        a -= da; b -= db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return a, b


def platt_predict(ab: tuple[float, float], x: float) -> float:
    a, b = ab
    z = max(-35.0, min(35.0, a * x + b))
    return 1.0 / (1.0 + math.exp(-z))


def brier(ps: list[float], ys: list[float]) -> float:
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / max(1, len(ps))


def _dataset(con, horizon: str, until_ts: int | None):
    q = """SELECT s.z, s.n_eff, l.cls FROM signals s
           JOIN labels l ON l.ticker=s.ticker AND l.asof_ts=s.asof_ts
           WHERE l.horizon=?"""
    args: list = [horizon]
    if until_ts:
        q += " AND s.asof_ts < ?"; args.append(until_ts)
    return con.execute(q, args).fetchall()


def fit(horizon: str = "1d", until_ts: int | None = None, persist: bool = True,
        method: str = "platt") -> dict:
    """Ajusta P(alta|z) e P(queda|z).

    method="platt" e o DEFAULT por medicao, nao por gosto: ver docstring de
    platt(). Use "isotonic" quando tiver alguns milhares de eventos.
    """
    con = connect()
    rows = _dataset(con, horizon, until_ts)
    out = {"n": len(rows), "horizon": horizon, "fitted": False}

    if len(rows) < MIN_N:
        out["falhou_por"] = "amostra"
        out["reason"] = (f"amostra insuficiente: {len(rows)} eventos rotulados, "
                         f"minimo {MIN_N}. O visor segue NAO CALIBRADO.")
        con.close()
        return out

    zs = [r["z"] for r in rows]
    up = [1.0 if r["cls"] == 1 else 0.0 for r in rows]
    dn = [1.0 if r["cls"] == -1 else 0.0 for r in rows]

    if method == "isotonic":
        k_up = pava(zs, up)
        k_dn = pava([-z for z in zs], dn)      # P(queda) decresce em z
        f_up = lambda z: predict(k_up, z)
        f_dn = lambda z: predict(k_dn, -z)
    elif method == "platt":
        k_up = platt(zs, up)
        k_dn = platt([-z for z in zs], dn)
        f_up = lambda z: platt_predict(k_up, z)
        f_dn = lambda z: platt_predict(k_dn, -z)
    else:
        raise ValueError(f"method desconhecido: {method}")

    m_up = brier([f_up(z) for z in zs], up)
    m_dn = brier([f_dn(z) for z in zs], dn)
    base = base_rates(con, horizon)
    b_up = brier([base["up"]] * len(up), up)
    b_dn = brier([base["down"]] * len(dn), dn)

    out.update({
        "fitted": True, "method": method,
        "brier_up": round(m_up, 5), "brier_up_baseline": round(b_up, 5),
        "brier_down": round(m_dn, 5), "brier_down_baseline": round(b_dn, 5),
        "skill_up": round(1 - m_up / b_up, 4) if b_up else 0.0,
        "skill_down": round(1 - m_dn / b_dn, 4) if b_dn else 0.0,
    })

    # A PORTA: skill negativo significa que o calibrador perde para o chute da
    # taxa-base. Nesse caso nao se grava nada, e `probabilities()` segue
    # devolvendo None -- o painel continua em NAO CALIBRADO, que e a leitura
    # honesta. Reprovar aqui e resultado valido, nao falha de execucao.
    reprova = []
    if out["skill_up"] <= MIN_SKILL:
        reprova.append(f"skill de alta {out['skill_up']:+.4f} (minimo {MIN_SKILL:+.2f})")
    if out["skill_down"] <= MIN_SKILL:
        reprova.append(f"skill de queda {out['skill_down']:+.4f} (minimo {MIN_SKILL:+.2f})")
    out["aprovado"] = not reprova
    if reprova:
        # O motivo tem de ser preenchido ANTES de gravar: a versao anterior
        # gravava `out` e so depois escrevia `reason`, entao o painel recebia
        # `reason: null` e exibia "reprovou:" seguido de nada.
        out["reason"] = "nao passou na porta: " + "; ".join(reprova)
        out["falhou_por"] = "desempenho"
    # REGISTRA A TENTATIVA mesmo quando reprova. Sem isso o painel nao
    # distingue "ainda nao houve tentativa" de "houve e falhou" -- sao estados
    # diferentes e o segundo e muito mais informativo. O nome tem prefixo
    # `tentativa:` de proposito: `load()` procura por `up:{h}`/`down:{h}`,
    # entao esta linha NUNCA e confundida com um calibrador aprovado.
    with con:
        con.execute(
            "INSERT OR REPLACE INTO calibrators(name,payload,n,fitted_ts,metrics)"
            " VALUES (?,?,?,?,?)",
            (f"tentativa:direcao:{horizon}", json.dumps({"aprovado": out["aprovado"]}),
             len(rows), now_ts(), json.dumps(out)))
    if reprova:
        out["reason"] += ". O visor segue NAO CALIBRADO."
        con.close()
        return out

    if persist:
        ts = now_ts()
        with con:
            for name, params in ((f"up:{horizon}", k_up), (f"down:{horizon}", k_dn)):
                con.execute(
                    "INSERT OR REPLACE INTO calibrators(name,payload,n,fitted_ts,metrics)"
                    " VALUES (?,?,?,?,?)",
                    (name, json.dumps({"method": method, "params": params}),
                     len(rows), ts, json.dumps(out)))
    con.close()
    return out


def load(con, horizon: str = "1d"):
    res = {}
    for d in ("up", "down"):
        row = con.execute("SELECT payload,n FROM calibrators WHERE name=?",
                          (f"{d}:{horizon}",)).fetchone()
        res[d] = json.loads(row["payload"]) if row else None
    return res


def apply_cal(cal: dict, x: float) -> float:
    """Avalia um calibrador gravado, qualquer que seja o metodo."""
    if cal["method"] == "platt":
        return platt_predict(tuple(cal["params"]), x)
    return predict([tuple(k) for k in cal["params"]], x)


def probabilities(con, z: float, n_eff: float, horizon: str = "1d",
                  ticker: str | None = None) -> dict:
    """z -> (p_up, p_flat, p_down) com encolhimento para a taxa-base.

    Com pouca evidencia (n_eff baixo) o resultado TEM de convergir para a
    taxa-base: 'nao sei' e uma resposta, e e a resposta certa quase sempre."""
    base = base_rates(con, horizon, ticker)
    if base["n"] < 30:
        base = base_rates(con, horizon)      # pouca historia do papel: usa o pool

    cal = load(con, horizon)
    calibrated = cal["up"] is not None and cal["down"] is not None

    if not calibrated:
        return {"p_up": None, "p_flat": None, "p_down": None,
                "base_up": base["up"], "base_flat": base["flat"],
                "base_down": base["down"], "calibrated": 0}

    p_up = apply_cal(cal["up"], z)
    p_dn = apply_cal(cal["down"], -z)

    w = n_eff / (n_eff + SHRINK_K)
    p_up = w * p_up + (1 - w) * base["up"]
    p_dn = w * p_dn + (1 - w) * base["down"]

    tot = p_up + p_dn
    if tot > 1.0:                             # normaliza deixando 'neutro' >= 0
        p_up, p_dn = p_up / tot, p_dn / tot
    return {"p_up": round(p_up, 4), "p_flat": round(max(0.0, 1 - p_up - p_dn), 4),
            "p_down": round(p_dn, 4), "base_up": round(base["up"], 4),
            "base_flat": round(base["flat"], 4), "base_down": round(base["down"], 4),
            "calibrated": 1}
