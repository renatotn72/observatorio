"""IPE da CVM: a fonte CANONICA de documentos oficiais.

POR QUE ESTE MODULO EXISTE
    O crawler de RI (obs/ri.py) rastreia o site da empresa e esbarra em dois
    muros: sites dinamicos (os PDFs nem estao no HTML inicial) e falsos
    positivos (ver a correcao em _pdf_candidate). Para PETR4 ele descobria 7
    "documentos" e baixava ZERO -- os sete eram paginas HTML.

    O IPE resolve isso na raiz: a propria CVM publica um CSV anual com TODOS
    os documentos entregues por TODAS as companhias abertas, com `Link_Download`
    apontando direto para o arquivo. Sem rastejar, sem navegador headless.
    So para a Petrobras em 2026 sao 225 documentos.

DUAS ARMADILHAS QUE CUSTARAM TEMPO -- nao as remova
    1. ACENTO: o nome vem "PETROLEO BRASILEIRO S.A. - PETROBRAS" com acento.
       Filtrar por "PETROLEO BRASILEIRO" sem acento devolve ZERO resultados,
       em silencio. Toda comparacao de nome aqui passa por `_sem_acento`.
    2. CONTENT-TYPE MENTIROSO: o RAD da CVM serve PDF declarando
       `content-type: text/html`. Quem checar so o MIME ignora tudo. A
       verificacao correta e a ASSINATURA do arquivo (`%PDF`), que e o que
       reports.download_remote ja faz.
"""
from __future__ import annotations
import csv
import io
import unicodedata
import zipfile

from .util import http_get

IPE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"

# Categorias que interessam para o observatorio, em ordem de valor.
CATEGORIAS_ALVO = {
    "Fato Relevante": "FATO_RELEVANTE",
    "Comunicado ao Mercado": "COMUNICADO",
    "Dados Econômico-Financeiros": "RESULTADO",
    "Press-release de Resultados": "RESULTADO",
    "Apresentações a analistas/agentes do mercado": "APRESENTACAO",
    "Calendário de Eventos Corporativos": "CALENDARIO",
    "Informação Prestada às Bolsas Estrangeiras": "BOLSA_ESTRANGEIRA",
    "Política de Divulgação de Ato ou Fato Relevante": "POLITICA",
    "Reunião da Administração": "GOVERNANCA",
    "Assembleia": "GOVERNANCA",
}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").upper()


def baixa_ano(ano: int) -> list[dict]:
    """CSV anual do IPE inteiro, como lista de dicionarios."""
    r = http_get(IPE_URL.format(ano=ano), timeout=120)
    if r is None:
        return []
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return []
    nomes = [n for n in z.namelist() if n.endswith(".csv")]
    if not nomes:
        return []
    out = []
    with z.open(nomes[0]) as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"):
            out.append(row)
    return out


def documentos(termos_empresa: list[str], anos: list[int],
               categorias: set[str] | None = None,
               cnpj: str | None = None) -> list[dict]:
    """Documentos de uma empresa, por nome (sem acento) ou CNPJ.

    `termos_empresa` sao trechos do nome na CVM -- ex.: ["PETROLEO BRASILEIRO"].
    Comparados SEM acento, que e a armadilha 1 do cabecalho.
    """
    alvo = [_sem_acento(t) for t in termos_empresa]
    cnpj_limpo = "".join(ch for ch in (cnpj or "") if ch.isdigit())
    out = []
    for ano in anos:
        for r in baixa_ano(ano):
            nome = _sem_acento(r.get("Nome_Companhia", ""))
            doc_cnpj = "".join(ch for ch in (r.get("CNPJ_Companhia") or "") if ch.isdigit())
            casa = (cnpj_limpo and doc_cnpj == cnpj_limpo) or \
                   (not cnpj_limpo and any(t in nome for t in alvo))
            if not casa:
                continue
            cat = r.get("Categoria", "")
            if categorias and cat not in categorias:
                continue
            link = (r.get("Link_Download") or "").strip()
            if not link:
                continue
            out.append({
                "url": link,
                "kind": CATEGORIAS_ALVO.get(cat, "CVM"),
                "categoria": cat,
                "title": (r.get("Assunto") or cat or "")[:200],
                "periodo": r.get("Data_Referencia", ""),
                "entrega": r.get("Data_Entrega", ""),
                "protocolo": r.get("Protocolo_Entrega", ""),
                "versao": r.get("Versao", ""),
                "cnpj": r.get("CNPJ_Companhia", ""),
                "empresa": r.get("Nome_Companhia", ""),
            })
    out.sort(key=lambda d: d["entrega"], reverse=True)
    return out


def sync(ticker: str, termos: list[str], anos: list[int] | None = None,
         categorias: set[str] | None = None, limite: int = 20,
         download: bool = True, cnpj: str | None = None,
         verbose: bool = True) -> dict:
    """Descobre no IPE, registra e baixa. Devolve o mesmo formato do ri-sync."""
    import datetime as dt

    from . import reports

    anos = anos or [dt.date.today().year]
    docs = documentos(termos, anos, categorias, cnpj)[:limite]
    ids, baixados, ignorados = [], [], []
    for d in docs:
        rid = reports.add_url(ticker, d["url"], kind=d["kind"], title=d["title"])
        ids.append(rid)
        if not download:
            continue
        res = reports.download_remote(rid)
        if res.get("downloaded"):
            baixados.append({**res, "titulo": d["title"][:70], "entrega": d["entrega"]})
            if verbose:
                print(f"  [ipe] OK  {d['entrega']}  {d['title'][:62]}")
        else:
            ignorados.append({**res, "titulo": d["title"][:70]})
            if verbose:
                print(f"  [ipe] --  {res.get('reason','?')}: {d['title'][:52]}")
    return {"ticker": ticker.upper(), "fonte": "CVM/IPE",
            "descobertos": len(docs), "registrados": len(ids),
            "baixados": len(baixados), "ignorados": len(ignorados),
            "anos": anos, "detalhes_download": baixados[:50]}
