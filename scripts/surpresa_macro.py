#!/usr/bin/env python3
"""Surpresa macro de verdade: consenso do Focus vs realizado do BCB.

POR QUE ISTO E O PONTO DE VIRADA DO PROJETO
    Em tudo que medimos ate agora, o sinal vivia onde e caro capturar (leilao
    de abertura) e chegava tarde (GDELT com 15 min de atraso). Evento
    AGENDADO nao tem nenhum dos dois problemas:
      - a data e conhecida com antecedencia, entao voce nao corre contra
        ninguem para descobrir que o dado saiu;
      - existe CONSENSO publicado, entao a surpresa e calculavel em vez de
        inferida de texto.

    surpresa = (realizado - mediana_Focus) / desvio_das_projecoes

    O desvio importa: 0,1 p.p. acima do consenso e enorme quando os 40
    economistas concordavam e irrelevante quando discordavam entre si.

FONTES (ambas gratuitas, sem chave)
    Focus/Expectativas : olinda.bcb.gov.br (OData)
    Realizado          : api.bcb.gov.br SGS
"""
from __future__ import annotations
import json
import os
import statistics as st
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from obs.util import http_get                                   # noqa: E402

OLINDA = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados"
SERIES = {"IPCA": 433, "Selic": 432}


def focus(indicador: str, top: int = 2000) -> list[dict]:
    """Projecoes mensais do Focus para um indicador."""
    # baseCalculo: 0 = respostas dos ultimos 30 dias, 1 = dos ultimos 5 dias
    # uteis. Filtrar por 0 devolvia ZERO linhas -- as que existem vem com 1.
    # Sem filtro, ficamos com as duas e escolhemos a mais recente por mes.
    q = {"$top": top, "$format": "json", "$orderby": "Data desc",
         "$filter": f"Indicador eq '{indicador}'"}
    # quote_via=quote e obrigatorio: o urlencode padrao troca espaco por '+',
    # e o OData do BCB rejeita isso com "Edm.Boolean / Edm.String are not
    # compatible" -- erro que parece de tipo e e de codificacao de espaco.
    url = OLINDA + "ExpectativaMercadoMensais?" + urllib.parse.urlencode(
        q, safe="$,'", quote_via=urllib.parse.quote)
    r = http_get(url, timeout=40)
    if r is None:
        return []
    try:
        return r.json().get("value", [])
    except ValueError:
        return []


def realizado(serie: int) -> dict[str, float]:
    r = http_get(SGS.format(serie), params={"formato": "json"}, timeout=40)
    if r is None:
        return {}
    try:
        linhas = r.json()
    except ValueError:
        return {}
    out = {}
    for x in linhas:
        d, v = x.get("data", ""), x.get("valor")
        if not d or v in (None, ""):
            continue
        dd, mm, aa = d.split("/")
        out[f"{mm}/{aa}"] = float(v)
    return out


def main():
    ind = "IPCA"
    print(f"Baixando Focus ({ind}) e realizado do BCB...")
    proj = focus(ind)
    real = realizado(SERIES[ind])
    print(f"  {len(proj)} projecoes | {len(real)} meses realizados\n")
    if not proj or not real:
        print("fontes indisponiveis agora"); return 1

    # para cada mes de referencia: a ULTIMA projecao ANTES do fim do mes
    por_ref: dict[str, list[dict]] = {}
    for p in proj:
        ref = p.get("DataReferencia")
        if ref:
            por_ref.setdefault(ref, []).append(p)

    linhas = []
    for ref, ps in por_ref.items():
        if ref not in real:
            continue
        mm, aa = ref.split("/")
        # so projecoes feitas DENTRO ou ANTES do mes de referencia
        validas = [p for p in ps if p.get("Data", "")[:7] <= f"{aa}-{mm}"]
        if not validas:
            continue
        ult = max(validas, key=lambda p: p["Data"])
        mediana, desvio = ult.get("Mediana"), ult.get("DesvioPadrao")
        n = ult.get("numeroRespondentes") or 0
        if mediana is None or not desvio or n < 10:
            continue
        surp = (real[ref] - mediana) / desvio
        linhas.append({"ref": ref, "data_proj": ult["Data"], "mediana": mediana,
                       "desvio": desvio, "real": real[ref], "surp": surp, "n": n})

    linhas.sort(key=lambda x: (x["ref"].split("/")[1], x["ref"].split("/")[0]))
    linhas = linhas[-18:]
    if not linhas:
        print("nenhum par consenso/realizado alinhado"); return 1

    print(f"SURPRESA DO {ind}: (realizado - mediana Focus) / desvio das projecoes")
    print("=" * 78)
    print(f"{'mes':>8} {'consenso':>9} {'desvio':>7} {'realizado':>10} "
          f"{'surpresa':>9} {'n':>4}  leitura")
    print("-" * 78)
    for l in linhas:
        s = l["surp"]
        leitura = ("surpresa ALTA" if s > 1 else "surpresa BAIXA" if s < -1
                   else "dentro do esperado")
        print(f"{l['ref']:>8} {l['mediana']:>9.2f} {l['desvio']:>7.2f} "
              f"{l['real']:>10.2f} {s:>+9.2f} {l['n']:>4}  {leitura}")

    ss = [l["surp"] for l in linhas]
    fora = sum(1 for s in ss if abs(s) > 1)
    print(f"\nn={len(ss)}  media={st.fmean(ss):+.2f}  desvio={st.pstdev(ss):.2f}")
    print(f"meses com |surpresa| > 1 desvio: {fora} de {len(ss)} ({100*fora/len(ss):.0f}%)")
    print("\nE ISTO que vira feature -- nao o texto da noticia sobre a inflacao.")
    print("A surpresa entra no sinal de cada papel ponderada pela exposicao dele")
    print("a juros e consumo domestico: MGLU3 e ITUB4 reagem de formas opostas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
