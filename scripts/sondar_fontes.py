#!/usr/bin/env python3
"""Sonda as fontes candidatas do ponto 6 e MEDE o que decide a adocao.

POR QUE UM SCRIPT, E NAO UMA TABELA NA DOCUMENTACAO
Viabilidade de fonte nao se decide por reputacao, decide-se por quatro numeros
que mudam com o tempo:

  responde?   HTTP 200 sem login, ou exige chave/cookie/captcha
  custo       tempo de resposta e tamanho; fonte lenta nao cabe em rodada curta
  LATENCIA    distancia entre o fato e a publicacao -- medida comparando a data
              do registro mais novo com agora. E o numero que decide se a
              fonte e RADAR (chega antes da imprensa) ou arquivo.
  volume      quantos itens por consulta, para dimensionar dedupe

Este projeto ja tem tres casos registrados de fonte que "existe" e nao serve:
valor.globo.com/rss morto devolvendo 0 itens, infomoney/mercados/feed
devolvendo 0, e a Reuters respondendo 401 porque o RSS publico virou licenca
(docs/como-usar.md, secao 6). Fonte morta nao da erro: devolve vazio, e quem
nao mede conclui que nao houve fato.

USO
    python3 scripts/sondar_fontes.py            # todas
    python3 scripts/sondar_fontes.py legislativo
    python3 scripts/sondar_fontes.py --json

NAO COLETA NADA. Nao grava no banco, nao cadastra fonte, nao baixa documento.
E so diagnostico, para a recomendacao de docs/fontes-prospectivas.md parar de
depender de suposicao.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UA = "observatorio-acoes/0.1 (pesquisa academica)"
TIMEOUT = 25

# (grupo, nome, url, o_que_responde, como_achar_a_data)
# `data` e uma regex sobre o corpo da resposta cujo grupo 1 e uma data ISO.
# Serve para medir LATENCIA sem parser proprio por fonte.
FONTES = [
    # ------------------------------------------------------- legislativo ---
    ("legislativo", "Camara / proposicoes",
     "https://dadosabertos.camara.leg.br/api/v2/proposicoes"
     "?ordem=DESC&ordenarPor=id&itens=20",
     "JSON aberto, sem chave", r'"dataApresentacao"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    ("legislativo", "Camara / eventos de hoje",
     "https://dadosabertos.camara.leg.br/api/v2/eventos?itens=20",
     "JSON aberto, sem chave", r'"dataHoraInicio"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    ("legislativo", "Senado / materias do ano",
     "https://legis.senado.leg.br/dadosabertos/materia/pesquisa/lista"
     f"?ano={dt.date.today().year}",
     "XML aberto, sem chave", r"<DataApresentacao>(\d{4}-\d{2}-\d{2})"),
    # ---------------------------------------------------------- judicial ---
    ("judicial", "DataJud CNJ / TRF1",
     "https://api-publica.datajud.cnj.jus.br/api_publica_trf1/_search",
     "Elasticsearch; exige APIKey publica do CNJ no header",
     r'"dataAjuizamento"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    ("judicial", "STF / noticias (RSS)",
     "https://noticias.stf.jus.br/postsnovoportal/rss",
     "RSS publico", r"<pubDate>([^<]+)</pubDate>"),
    ("judicial", "STJ / noticias (RSS)",
     "https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias.aspx",
     "pagina HTML; RSS proprio nao documentado", None),
    ("judicial", "MPF / noticias (RSS)",
     "https://www.mpf.mp.br/rss/noticias", "RSS publico",
     r"<pubDate>([^<]+)</pubDate>"),
    ("judicial", "Querido Diario / API",
     "https://queridodiario.ok.org.br/api/gazettes?querystring=petrobras&size=5",
     "JSON aberto; diarios MUNICIPAIS, nao Uniao",
     r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    ("judicial", "DOU / in.gov.br",
     "https://www.in.gov.br/leiturajornal?data=" + dt.date.today().strftime("%d-%m-%Y"),
     "HTML; JSON embutido em <script>", None),
    # -------------------------------------------------------- regulatorio ---
    ("regulatorio", "ANP / consultas e audiencias",
     "https://www.gov.br/anp/pt-br/assuntos/consultas-e-audiencias-publicas",
     "HTML institucional", None),
    ("regulatorio", "ANEEL / dados abertos",
     "https://dadosabertos.aneel.gov.br/api/3/action/package_list",
     "CKAN, JSON aberto", None),
    ("regulatorio", "ANATEL / dados abertos",
     "https://dados.gov.br/api/3/action/organization_show?id=anatel",
     "CKAN, JSON aberto", None),
    ("regulatorio", "CADE / pauta de julgamento",
     "https://www.gov.br/cade/pt-br/assuntos/sessoes-de-julgamento",
     "HTML institucional", None),
    # --------------------------------------------- ja usados pelo projeto ---
    ("ja_usado", "CVM / IPE (fato relevante, calendario)",
     "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/",
     "CSV anual; JA INTEGRADO em obs/cvm_ipe.py", None),
    ("ja_usado", "CVM / cadastro de companhias",
     "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/",
     "CSV; JA INTEGRADO em obs/universe.py", None),
]


def _data(txt, padrao):
    if not padrao:
        return None
    m = re.search(padrao, txt)
    if not m:
        return None
    bruto = m.group(1)
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = dt.datetime.strptime(bruto.strip()[:len(bruto.strip())], fmt)
            return d.date() if d.tzinfo is None else d.date()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(bruto[:10])
    except ValueError:
        return None


def sonda(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            corpo = r.read(400_000).decode("utf-8", "replace")
            return {"http": r.status, "s": time.time() - t0,
                    "bytes": len(corpo), "corpo": corpo, "erro": None}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "s": time.time() - t0, "bytes": 0,
                "corpo": "", "erro": f"HTTP {e.code}"}
    except Exception as e:                                   # noqa: BLE001
        return {"http": 0, "s": time.time() - t0, "bytes": 0, "corpo": "",
                "erro": f"{type(e).__name__}: {str(e)[:70]}"}


def main(grupos=None, como_json=False):
    hoje = dt.date.today()
    saida = []
    print(f"sonda de fontes — {hoje.isoformat()}  (timeout {TIMEOUT}s)\n")
    print(f"{'grupo':<12}{'fonte':<40}{'HTTP':>5}{'seg':>7}{'KB':>7}"
          f"{'+novo':>9}  observacao")
    for grupo, nome, url, obs, pad in FONTES:
        if grupos and grupo not in grupos:
            continue
        r = sonda(url)
        d = _data(r["corpo"], pad)
        atraso = f"{(hoje - d).days}d" if d else "—"
        marca = "ok" if r["http"] == 200 else (r["erro"] or "?")
        print(f"{grupo:<12}{nome[:38]:<40}{r['http']:>5}{r['s']:>7.2f}"
              f"{r['bytes']/1024:>7.0f}{atraso:>9}  {obs[:42]}")
        if r["erro"]:
            print(f"{'':<12}{'':<40}{'':>5}{'':>7}{'':>7}{'':>9}  !! {r['erro']}")
        saida.append({"grupo": grupo, "fonte": nome, "url": url,
                      "http": r["http"], "segundos": round(r["s"], 2),
                      "bytes": r["bytes"], "registro_mais_novo":
                      d.isoformat() if d else None,
                      "atraso_dias": (hoje - d).days if d else None,
                      "observacao": obs, "erro": r["erro"]})
    print("\n'+novo' = idade do registro MAIS NOVO que a consulta devolveu.")
    print("E a leitura de latencia: '0d' ou '1d' e radar; '30d' e arquivo.")
    print("'—' = o script nao sabe extrair data desta fonte sem parser proprio.")
    print("\nHTTP 000 costuma ser bloqueio de rede do ambiente, nao fonte morta.")
    if como_json:
        p = "data/sonda_fontes.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"data": hoje.isoformat(), "fontes": saida}, fh,
                      ensure_ascii=False, indent=2)
        print(f"\n-> {p}")
    return saida


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(set(args) or None, "--json" in sys.argv)
