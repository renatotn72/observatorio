"""Plano contabil da CVM: o nome muda, o codigo quase nao.

O PROBLEMA QUE VOCE LEVANTOU, MEDIDO
    Numa DRE consolidada de um trimestre: 168 de 218 codigos aparecem com
    MAIS DE UM nome de conta. Casar por DS_CONTA (o nome) e inviavel.

O QUE O DADO MOSTRA, E A SOLUCAO QUE SAI DISSO
    1. Nos niveis RASOS (3.01, 3.02, 3.03, 3.11) o CD_CONTA mapeia o mesmo
       conceito economico, e o nome muda so por SETOR:
           3.01 = "Receita de Venda de Bens e/ou Servicos"      (industria)
                = "Receitas da Intermediacao Financeira"        (banco)
                = "Receitas das Atividades Seguradoras"         (seguradora)
       -> casar por CODIGO, nunca por nome.

    2. Nos niveis PROFUNDOS (3.04.05.01) o mesmo codigo recebe conceitos
       completamente diferentes entre empresas.
       -> NAO descer abaixo do nivel 2 sem mapeamento explicito.

    3. Um codigo e genuinamente ambiguo: 3.05 ora e "Resultado Antes do
       Resultado Financeiro" (o EBIT), ora "Outras Receitas e Despesas
       Operacionais" (uma linha de ajuste).
       -> desempatar pelo NOME normalizado, so nesse caso.

    4. Banco, seguradora e industria tem planos diferentes por desenho.
       -> o mapa e por FAMILIA de plano, nao unico.

VALIDACAO OBRIGATORIA
    Toda extracao confere identidades contabeis (3.03 = 3.01 + 3.02). Se nao
    fecha, o papel e marcado como suspeito em vez de entrar com numero errado.
"""
from __future__ import annotations
import csv
import io
import re
import zipfile
from pathlib import Path

from .util import norm

CVM_ITR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip"
CVM_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"

# conceito -> codigo por familia de plano. Nivel <= 2 apenas.
PLANO = {
    "industria": {
        "receita_liquida": "3.01", "custo": "3.02", "lucro_bruto": "3.03",
        "despesas_op": "3.04", "ebit": "3.05", "resultado_financeiro": "3.06",
        "lucro_antes_tributos": "3.07", "lucro_liquido": "3.11",
    },
    "banco": {
        "receita_liquida": "3.01", "custo": "3.02", "lucro_bruto": "3.03",
        "despesas_op": "3.04", "ebit": "3.05", "resultado_financeiro": "3.06",
        "lucro_antes_tributos": "3.07", "lucro_liquido": "3.11",
    },
}
# Balanco: mesmos codigos em todas as familias
BALANCO = {
    "ativo_total": "1", "ativo_circulante": "1.01", "caixa": "1.01.01",
    "passivo_circulante": "2.01", "passivo_nao_circulante": "2.02",
    "patrimonio_liquido": "2.03",
}

# 3.05 e ambiguo: desempate pelo nome normalizado
AMBIGUOS = {
    "3.05": {
        "ebit": ["resultado antes do resultado financeiro",
                 "resultado antes das receitas", "lucro operacional"],
        "outras_receitas_despesas": ["outras receitas e despesas"],
    }
}

IDENTIDADES = [("lucro_bruto", "receita_liquida", "custo")]   # 3.03 = 3.01 + 3.02


def familia(ds_conta_3_01: str) -> str:
    """Detecta a familia do plano pela linha de receita."""
    n = norm(ds_conta_3_01 or "")
    if "intermediacao financeira" in n or "juros" in n:
        return "banco"
    if "seguradora" in n or "resseguradora" in n:
        return "seguradora"
    return "industria"


def desambigua(cd: str, ds: str) -> str | None:
    """Para codigo ambiguo, devolve o conceito pelo nome; senao None."""
    regras = AMBIGUOS.get(cd)
    if not regras:
        return None
    n = norm(ds or "")
    for conceito, padroes in regras.items():
        if any(p in n for p in padroes):
            return conceito
    return None


def extrai_dre(zip_bytes: bytes, cnpjs: set[str] | None = None) -> dict:
    """{cnpj: {periodo: {conceito: valor}}} a partir do zip da CVM.

    Casa por CD_CONTA, nunca por nome -- exceto nos ambiguos declarados.
    """
    out: dict = {}
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    alvo = [n for n in z.namelist() if "DRE_con" in n]
    if not alvo:
        return out

    codigos = {v: k for k, v in PLANO["industria"].items()}
    with z.open(alvo[0]) as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"):
            cnpj = row.get("CNPJ_CIA", "")
            if cnpjs and cnpj not in cnpjs:
                continue
            if row.get("ORDEM_EXERC") != "ÚLTIMO":      # so o exercicio corrente
                continue
            cd, ds = row.get("CD_CONTA", ""), row.get("DS_CONTA", "")
            conceito = desambigua(cd, ds) or codigos.get(cd)
            if not conceito:
                continue
            try:
                val = float(row.get("VL_CONTA") or 0)
            except ValueError:
                continue
            escala = 1000 if (row.get("ESCALA_MOEDA") or "").upper().startswith("MIL") else 1
            per = row.get("DT_FIM_EXERC", "")
            d = out.setdefault(cnpj, {}).setdefault(per, {})
            d[conceito] = val * escala
            if cd == "3.01":
                d["_familia"] = familia(ds)
            d["_denom"] = row.get("DENOM_CIA", "")
            d["_dt_refer"] = row.get("DT_REFER", "")
    return out


def valida(periodo: dict, tol: float = 0.02) -> list[str]:
    """Confere identidades. Devolve lista de problemas (vazia = ok)."""
    problemas = []
    for alvo, a, b in IDENTIDADES:
        if all(k in periodo for k in (alvo, a, b)):
            esperado = periodo[a] + periodo[b]
            real = periodo[alvo]
            base = max(abs(real), abs(esperado), 1.0)
            if abs(real - esperado) / base > tol:
                problemas.append(f"{alvo} != {a} + {b} ({real:,.0f} vs {esperado:,.0f})")
    return problemas


def indicadores(periodo: dict, valor_mercado: float | None = None) -> dict:
    """Os indicadores que a cabeca de volatilidade e o scorer usam."""
    r = periodo.get("receita_liquida")
    lucro = periodo.get("lucro_liquido")
    pl = periodo.get("patrimonio_liquido")
    out = {}
    if r:
        if lucro is not None:
            out["margem_liquida"] = lucro / r
        if periodo.get("lucro_bruto") is not None:
            out["margem_bruta"] = periodo["lucro_bruto"] / r
        if periodo.get("ebit") is not None:
            out["margem_ebit"] = periodo["ebit"] / r
    if pl and lucro is not None:
        out["roe"] = lucro / pl
    if valor_mercado:
        out["valor_mercado"] = valor_mercado
        if lucro:
            out["p_l"] = valor_mercado / (lucro * 4)       # lucro trimestral anualizado
        if pl:
            out["p_vp"] = valor_mercado / pl
    return out


# --------------------------------------------------- calendario e opiniao ---
SCHEMA_CONTABIL = """
CREATE TABLE IF NOT EXISTS fundamentos (
  ticker    TEXT NOT NULL,
  periodo   TEXT NOT NULL,      -- DT_FIM_EXERC
  dt_refer  TEXT,               -- data do protocolo na CVM = divulgacao
  familia   TEXT,
  dados     TEXT NOT NULL,      -- JSON com os conceitos
  problemas TEXT,               -- JSON com falhas de identidade contabil
  PRIMARY KEY (ticker, periodo)
);
CREATE TABLE IF NOT EXISTS opiniao_trimestre (
  ticker   TEXT NOT NULL,
  periodo  TEXT NOT NULL,
  scorer   TEXT NOT NULL,
  s        REAL NOT NULL,
  resumo   TEXT NOT NULL,
  raw      TEXT,
  PRIMARY KEY (ticker, periodo, scorer)
);
"""



def init_contabil(con=None) -> None:
    """Cria tabelas contábeis; aceita conexão existente para evitar conexões duplicadas."""
    from .db import connect
    own = con is None
    con = con or connect()
    with con:
        con.executescript(SCHEMA_CONTABIL)
    if own:
        con.close()


def gravar_fundamentos(ticker: str, periodo: str, dt_refer: str, dados: dict) -> None:
    from .db import connect
    problemas = valida(dados)
    payload = {
        "dre": {k: v for k, v in dados.items() if not k.startswith("_")},
        "indicadores": indicadores(dados),
        "denom_cia": dados.get("_denom"),
    }
    con = connect()
    init_contabil(con)
    with con:
        con.execute("""INSERT OR REPLACE INTO fundamentos
            (ticker,periodo,dt_refer,familia,dados,problemas)
            VALUES (?,?,?,?,?,?)""",
            (ticker.upper(), periodo, dt_refer, dados.get("_familia"),
             json.dumps(payload, ensure_ascii=False),
             json.dumps(problemas, ensure_ascii=False)))
    con.close()


def calendario(ticker: str) -> list[dict]:
    from .db import connect
    con = connect()
    init_contabil(con)
    rows = con.execute("""SELECT periodo,dt_refer FROM fundamentos WHERE ticker=?
        AND dt_refer IS NOT NULL ORDER BY periodo""", (ticker.upper(),)).fetchall()
    con.close()
    return [{"periodo": r["periodo"], "divulgacao": r["dt_refer"]} for r in rows]


def resumo_ticker(ticker: str, limite: int = 8) -> dict:
    from .db import connect
    con = connect()
    init_contabil(con)
    rows = con.execute("""SELECT ticker,periodo,dt_refer,familia,dados,problemas
        FROM fundamentos WHERE ticker=? ORDER BY periodo DESC LIMIT ?""",
        (ticker.upper(), limite)).fetchall()
    con.close()
    itens = []
    for r in rows:
        d = json.loads(r["dados"])
        itens.append({
            "periodo": r["periodo"], "dt_refer": r["dt_refer"],
            "familia": r["familia"], "indicadores": d.get("indicadores", {}),
            "dre": d.get("dre", {}),
            "problemas": json.loads(r["problemas"] or "[]"),
        })
    return {
        "itens": itens,
        "disponivel": bool(itens),
        "nota": "dados estruturados CVM" if itens else "dados CVM ainda não sincronizados",
    }


def sync_fundamentos(ano: int, tipo: str = "ITR",
                     empresas_path: str | None = None) -> dict:
    """Baixa DRE CVM e persiste apenas empresas mapeadas explicitamente por CNPJ."""
    import yaml
    from .config import ROOT
    from .util import http_get

    path = Path(empresas_path) if empresas_path else ROOT / "config" / "empresas.yml"
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = yaml.safe_load(path.read_text()) or {}
    empresas = spec.get("empresas") or {}
    mapa = {
        ticker.upper(): re.sub(r"\D", "", str(info.get("cnpj") or ""))
        for ticker, info in empresas.items() if info.get("cnpj")
    }
    if not mapa:
        return {"gravados": 0, "motivo": "preencha CNPJ em config/empresas.yml"}

    tipo = tipo.upper()
    if tipo not in ("ITR", "DFP"):
        raise ValueError("tipo deve ser ITR ou DFP")
    url = (CVM_ITR if tipo == "ITR" else CVM_DFP).format(ano=int(ano))
    res = http_get(url)
    if res is None:
        raise RuntimeError("falha ao baixar arquivo CVM")
    bruto = extrai_dre(res.content)
    por_cnpj = {re.sub(r"\D", "", cnpj): dados for cnpj, dados in bruto.items()}

    gravados, sem_dados = 0, []
    for ticker, cnpj in mapa.items():
        dados = por_cnpj.get(cnpj)
        if not dados or not dados.get("receita_liquida"):
            sem_dados.append(ticker)
            continue
        periodo = f"{tipo}-{int(ano)}"
        gravar_fundamentos(ticker, periodo, f"{int(ano)}-12-31", dados)
        gravados += 1

    return {
        "gravados": gravados, "sem_dados": sem_dados,
        "tipo": tipo, "ano": int(ano),
        "url": url,
    }
