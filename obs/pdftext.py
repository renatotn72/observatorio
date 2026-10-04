"""Extracao de texto de PDF sem dependencia externa.

POR QUE EXISTE
    `pypdf` e o caminho preferido, mas este ambiente nao tem `pip` e o PyPI
    esta inacessivel -- sem um plano B o pipeline documental inteiro fica
    parado. Os documentos da CVM sao PDFs GERADOS (nao escaneados), com texto
    em streams Flate, que o zlib da stdlib descomprime.

COMO FUNCIONA
    1. acha os objetos `stream ... endstream`
    2. descomprime o que for FlateDecode
    3. le os operadores de texto: `(txt) Tj` e `[(a) -200 (b)] TJ`
    4. decodifica escapes de PDF string e separa por BT/ET e Td/TD/T*

LIMITES -- diga ao usuario em vez de entregar texto ruim
    - PDF escaneado devolve pouco ou nada: e imagem, precisa de OCR.
    - Fontes com CMap customizado podem sair com caracteres trocados.
    - Nao reconstroi tabelas nem ordem de colunas com fidelidade.
    `qualidade()` mede isso e o chamador decide se confia.
"""
from __future__ import annotations
import re
import zlib

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TJ = re.compile(rb"\((?:\\.|[^\\()])*\)\s*Tj", re.S)
_TJ_ARR = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
_STR = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
_QUEBRA = re.compile(rb"(?:T\*|Td|TD|ET)\b")

_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
            b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _decodifica(s: bytes) -> str:
    """Resolve escapes de string PDF e devolve texto."""
    s = s[1:-1]                                   # tira os parenteses
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt in _ESCAPES:
                out += _ESCAPES[nxt]; i += 2; continue
            if nxt.isdigit():                      # octal \ddd
                j = i + 1
                oct_ = b""
                while j < len(s) and len(oct_) < 3 and s[j:j + 1].isdigit():
                    oct_ += s[j:j + 1]; j += 1
                try:
                    out.append(int(oct_, 8) & 0xFF)
                except ValueError:
                    pass
                i = j; continue
            i += 2; continue
        out += c
        i += 1
    # PDF usa latin-1 por padrao; UTF-16 aparece com BOM
    if out[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return out.decode("utf-16", errors="replace")
    return out.decode("latin-1", errors="replace")


def _texto_do_stream(dados: bytes) -> str:
    partes = []
    for m in re.finditer(rb"(\[.*?\]\s*TJ)|(\((?:\\.|[^\\()])*\)\s*Tj)|(T\*|Td|TD|ET)",
                         dados, re.S):
        bloco = m.group(0)
        if bloco.endswith(b"TJ") and bloco.startswith(b"["):
            for s in _STR.findall(bloco):
                partes.append(_decodifica(s))
        elif bloco.endswith(b"Tj"):
            s = _STR.search(bloco)
            if s:
                partes.append(_decodifica(s.group(0)))
        else:
            partes.append("\n")
    txt = "".join(partes)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    return re.sub(r"\n{3,}", "\n\n", txt)


def extrai(caminho: str) -> dict:
    """{texto, paginas, chars, metodo, qualidade}."""
    blob = open(caminho, "rb").read()
    if blob[:4] != b"%PDF":
        return {"texto": "", "paginas": 0, "chars": 0,
                "metodo": "nenhum", "qualidade": 0.0,
                "erro": "arquivo nao e PDF"}

    # pypdf quando existir: melhor fidelidade
    try:
        import pypdf
        leitor = pypdf.PdfReader(caminho)
        paginas = [(p.extract_text() or "") for p in leitor.pages]
        txt = "\n\n".join(f"[PÁGINA {i+1}]\n{t}" for i, t in enumerate(paginas))
        return {"texto": txt, "paginas": len(paginas), "chars": len(txt),
                "metodo": "pypdf", "qualidade": qualidade(txt)}
    except ImportError:
        pass

    textos = []
    for m in _STREAM.finditer(blob):
        dados = m.group(1)
        try:
            dados = zlib.decompress(dados)
        except zlib.error:
            continue                                # nao comprimido ou outro filtro
        t = _texto_do_stream(dados)
        if t.strip():
            textos.append(t)
    txt = "\n\n".join(f"[PÁGINA {i+1}]\n{t}" for i, t in enumerate(textos))
    npag = blob.count(b"/Type/Page") + blob.count(b"/Type /Page")
    return {"texto": txt, "paginas": max(len(textos), npag // 2 or len(textos)),
            "chars": len(txt), "metodo": "zlib-stdlib", "qualidade": qualidade(txt)}


def qualidade(txt: str) -> float:
    """0..1. Baixo = provavelmente escaneado ou com fonte exotica."""
    if not txt:
        return 0.0
    letras = sum(1 for c in txt if c.isalpha() or c.isspace())
    return round(letras / len(txt), 3)
