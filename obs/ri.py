"""Descoberta controlada de relatórios em sites oficiais de RI.

Rastreia somente domínios previamente validados. Primeiro visita páginas de resultado,
relatórios e comunicados; depois coleta links PDF/download encontrados dentro delas.
"""
from __future__ import annotations
import re
from collections import deque
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
import yaml
from . import config
from .util import http_get
from . import reports

KEYWORDS=("resultado","release","apresenta","earnings","financial","relatorio","report",
          "itr","dfp","demonstr","fato","comunicado","guidance","trimestr","quarter",
          "investor","divulgacao","balanco","download")
# NAO voltar a incluir "download" como pista solta: o site da Petrobras se
# chama "central-de-downloads", entao TODA url dele continha a palavra e virava
# candidata a PDF -- 7 descobertos, 0 baixados, todos paginas HTML. A pista tem
# de indicar ARQUIVO, nao secao do site.
PDF_HINTS=(".pdf",".xlsx",".xls",".zip","/download/","download=","arquivo=",
           "attachment","getfile","fileid","documento.pdf")
# Padroes que NUNCA sao documento, por mais que casem com as pistas acima.
NAO_DOCUMENTO=("wp-json","oembed","?page_id=","/feed","/wp-admin","mailto:",
               "javascript:","/tag/","/category/")

def _empresas():
    p=config.ROOT/"config"/"empresas.yml"
    return (yaml.safe_load(p.read_text()) or {}).get("empresas",{})

def _links(html, base):
    # Captura âncora e texto visível para não depender apenas do nome da URL.
    for tag, href in re.findall(r"""(<a\b[^>]*>.*?</a>)|href=["']([^"']+)["']""",html,re.I|re.S):
        raw = href
        label = ""
        if tag:
            m=re.search(r"""href=["']([^"']+)["']""",tag,re.I)
            raw=m.group(1) if m else ""
            label=re.sub(r"<[^>]+>"," ",tag)
        if raw:
            yield urljoin(base,unescape(raw)), re.sub(r"\s+"," ",unescape(label)).strip()

def _kind(text):
    low=text.lower()
    return "RESULTADO" if any(k in low for k in ("resultado","earnings","release","quarter")) else "RI"

def _candidate(url,label):
    low=(url+" "+label).lower()
    return any(k in low for k in KEYWORDS)

def _pdf_candidate(url,label):
    low=(url+" "+label).lower()
    if any(b in low for b in NAO_DOCUMENTO):
        return False
    return any(k in low for k in PDF_HINTS)

def discover(ticker: str, max_links: int=120, max_pages: int=30, max_depth: int=2) -> dict:
    info=_empresas().get(ticker.upper())
    if not info or not info.get("ri_url"): raise ValueError("RI oficial não configurado")
    root=info["ri_url"]; host=urlparse(root).netloc.lower()
    # sitemap é tentativa adicional; se não existir, não falha o processo.
    seeds=[root, urljoin(root,"/sitemap.xml")]
    q=deque((u,0,"") for u in seeds); visited=set(); docs={}; pages=[]
    while q and len(visited)<max_pages and len(docs)<max_links:
        page,depth,parent=q.popleft(); page=urldefrag(page)[0]
        if page in visited: continue
        x=urlparse(page)
        if x.scheme not in ("http","https") or x.netloc.lower()!=host: continue
        visited.add(page)
        r=http_get(page)
        if not r: continue
        ctype=(r.headers.get("content-type") or "").lower(); blob=r.content
        if blob[:4]==b"%PDF" or "application/pdf" in ctype:
            docs[page]={"url":page,"kind":_kind(parent or page),"title":Path(x.path).name or page,"source_page":parent}
            continue
        if "html" not in ctype and "xml" not in ctype and not r.text.lstrip().startswith("<"):
            continue
        pages.append(page)
        for u,label in _links(r.text,page):
            u=urldefrag(u)[0]; ux=urlparse(u)
            if ux.scheme not in ("http","https") or ux.netloc.lower()!=host: continue
            if _pdf_candidate(u,label):
                docs.setdefault(u,{"url":u,"kind":_kind(label+" "+u),"title":label or Path(ux.path).name or u,"source_page":page})
            if depth<max_depth and _candidate(u,label):
                q.append((u,depth+1,page))
    return {"documents":list(docs.values())[:max_links],"pages_visited":pages,"root":root}

def sync(ticker: str, download: bool=True) -> dict:
    found=discover(ticker); links=found["documents"]
    ids=[]; baixados=[]; ignorados=[]
    for x in links:
        rid=reports.add_url(ticker,x["url"],kind=x["kind"],title=x["title"]); ids.append(rid)
        if download:
            result=reports.download_remote(rid)
            (baixados if result.get("downloaded") else ignorados).append(result)
    nota = ("Crawl de até 2 níveis; PDFs validados por assinatura %PDF. "
            "Sites dinâmicos (Petrobras, Vale) não expõem os PDFs no HTML: "
            "para esses, use `obs cvm-sync`, que lê o IPE da CVM — a fonte "
            "canônica, com link direto para cada documento entregue.")
    if links and not baixados:
        nota = ("NENHUM PDF BAIXADO. O site provavelmente é dinâmico. "
                "Use `obs cvm-sync --ticker %s` — o IPE da CVM traz os "
                "documentos oficiais sem depender do site de RI." % ticker.upper())
    return {"ticker":ticker.upper(),"descobertos":len(links),"registrados":len(ids),
            "baixados":len(baixados),"ignorados":len(ignorados),
            "paginas_visitadas":len(found["pages_visited"]),
            "detalhes_download":baixados[:50], "nota":nota}
