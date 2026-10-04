#!/usr/bin/env python3
"""Testa CADA ITEM da legenda "Como ler o gráfico" contra o que o gráfico desenha.

POR QUE ESTE TESTE EXISTE
Legenda e grafico sao dois codigos diferentes desenhando a mesma coisa. Quando
divergem, a legenda vira mentira -- e mentira com aparencia de documentacao, que
e pior que ausencia de legenda. Ja aconteceu neste arquivo: as regras de estilo
do marcador tem escopo `#chart` e nao alcancavam as amostras da legenda, entao o
triangulo VAZADO do macro saia cheio, identico ao corporativo. O olho nao
distinguia os dois tipos, e a legenda afirmava que distinguia.

Cada caso aqui amarra UMA AFIRMACAO da legenda ao DOM do grafico.

Rode com o painel de pe:
    python3 -m obs.cli serve --port 8199 &
    python3 scripts/test_legenda.py [porta]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

PORTA = sys.argv[1] if len(sys.argv) > 1 else "8199"
URL = f"http://127.0.0.1:{PORTA}/acao.html?t=PETR4&dias=365"
CROMO = "/opt/pw-browsers/chromium"

FALHAS = []


def ok(cond, desc, det=""):
    marca = "OK " if cond else "FALHOU"
    if not cond:
        FALHAS.append(desc)
    print(f"  [{marca}] {desc}" + (f"  -- {det}" if det else ""))


def rgb(s):
    """'rgb(11, 138, 76)' -> (11,138,76). Devolve None se nao for cor."""
    import re
    m = re.findall(r"\d+", s or "")
    return tuple(int(x) for x in m[:3]) if len(m) >= 3 else None


def verdeish(c):
    return c and c[1] > c[0] and c[1] > c[2]


def vermelhoish(c):
    return c and c[0] > c[1] and c[0] > c[2]


def cinzaish(c):
    return c and max(c) - min(c) < 40


with sync_playwright() as pw:
    nav = pw.chromium.launch(executable_path=CROMO, args=["--no-sandbox"])
    pg = nav.new_page(viewport={"width": 1500, "height": 1200})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_selector("#chart .mk", timeout=20000)
    pg.wait_for_selector("#comoler-corpo .lgi", timeout=20000)

    print("\n== SEÇÃO: TIPO DE EVENTO — A FORMA DO MARCADOR ==")
    ok(not erros, "a página carrega sem erro de JS", "; ".join(erros[:2]))

    # Para cada tipo: a amostra da legenda desenha a MESMA geometria que o
    # grafico desenha para uma noticia daquele tipo?
    tipos = pg.evaluate("() => LEG.tipos.map(t => ({id: t.id, rotulo: t.rotulo, forma: t.forma}))")
    presentes = pg.evaluate("() => [...new Set(S.news.map(n => n.tipo_evento))]")
    for i, t in enumerate(tipos):
        # 1. a legenda lista o tipo
        rot = pg.inner_text(f"#comoler-corpo .lgi >> nth={i}")
        ok(t["rotulo"] in rot, f"{t['rotulo']}: aparece na legenda", rot.split("\n")[0][:40])

        # 2. a amostra usa a geometria declarada para aquele tipo
        mesma = pg.evaluate(
            """([idx, forma]) => {
                 const sv = document.querySelectorAll('#comoler-corpo .lgi .gl svg')[idx];
                 if (!sv) return null;
                 const el = sv.querySelector('.mk');
                 if (!el) return null;
                 // redesenha pela mesma funcao, com os mesmos parametros da amostra
                 const esperado = glifo(forma, 'up', 11, 11, 7);
                 const d = el.getAttribute('d');
                 const r = el.getAttribute('r');
                 const assinatura = d !== null ? `d:${d}` : `circle:${r}`;
                 const mD = esperado.match(/d="([^"]+)"/);
                 const mR = esperado.match(/r="([^"]+)"/);
                 const esp = mD ? `d:${mD[1]}` : `circle:${mR ? mR[1] : '?'}`;
                 return {igual: assinatura === esp, achado: assinatura, esperado: esp,
                         classe: el.getAttribute('class')};
               }""", [i, t["forma"]])
        ok(mesma and mesma["igual"],
           f"{t['rotulo']}: a amostra usa a geometria '{t['forma']}'",
           "" if (mesma and mesma["igual"]) else str(mesma))

        # 3. a MESMA geometria aparece no grafico para noticia desse tipo
        if t["id"] in presentes:
            bate = pg.evaluate(
                """(id) => {
                     const n = S.news.find(x => x.tipo_evento === id);
                     const el = document.querySelector(`#chart .mk[data-id="${n.id}"]`);
                     if (!el) return null;
                     const forma = formaDe(id);
                     const esperado = glifo(forma, n.dir, 0, 0, 10);
                     const tag = el.tagName.toLowerCase();
                     const esperadoTag = esperado.trim().startsWith('<circle') ? 'circle' : 'path';
                     return {igual: tag === esperadoTag, tag, esperadoTag, forma};
                   }""", t["id"])
            ok(bate and bate["igual"],
               f"{t['rotulo']}: o gráfico desenha a mesma família de forma",
               str(bate))
        else:
            print(f"  [PULA] {t['rotulo']}: nenhuma notícia deste tipo no período")

    # 4. VAZADO: a afirmacao "triangulo vazado" tem de ser verdade nas DUAS
    #    pontas -- na legenda e no grafico. E o defeito que ja ocorreu aqui.
    print("\n  -- a afirmação 'triângulo vazado' do Macroeconômico --")
    idx_macro = next(i for i, t in enumerate(tipos) if t["id"] == "macro")
    preench = pg.evaluate(
        """(idx) => {
             const sv = document.querySelectorAll('#comoler-corpo .lgi .gl svg')[idx];
             const el = sv.querySelector('.mk');
             const cs = getComputedStyle(el);
             return {fill: cs.fill, stroke: cs.stroke, classe: el.getAttribute('class')};
           }""", idx_macro)
    ok("vazado" in (preench["classe"] or ""),
       "amostra do macro recebe a classe 'vazado'", preench["classe"])
    ok(preench["fill"] in ("none", "rgba(0, 0, 0, 0)"),
       "amostra do macro é VAZADA (fill: none) — não cheia",
       f"fill={preench['fill']}")
    ok(rgb(preench["stroke"]) is not None,
       "amostra do macro tem contorno visível", f"stroke={preench['stroke']}")

    idx_corp = next(i for i, t in enumerate(tipos) if t["id"] == "corporativo")
    corp = pg.evaluate(
        """(idx) => {
             const el = document.querySelectorAll('#comoler-corpo .lgi .gl svg')[idx]
                        .querySelector('.mk');
             return getComputedStyle(el).fill;
           }""", idx_corp)
    ok(corp not in ("none", "rgba(0, 0, 0, 0)"),
       "amostra do corporativo é CHEIA — distinguível do macro", f"fill={corp}")

    if "macro" in presentes:
        g_macro = pg.evaluate(
            """() => {
                 const n = S.news.find(x => x.tipo_evento === 'macro');
                 const el = document.querySelector(`#chart .mk[data-id="${n.id}"]`);
                 return getComputedStyle(el).fill;
               }""")
        ok(g_macro in ("none", "rgba(0, 0, 0, 0)"),
           "no GRÁFICO o macro também é vazado", f"fill={g_macro}")

    print("\n== SEÇÃO: TEMPO DO CONTEÚDO — A MARCA AO LADO ==")
    orients = pg.evaluate("() => LEG.orientacoes.map(o => ({id:o.id, rotulo:o.rotulo, marca:o.marca}))")
    for o in orients:
        txt = pg.inner_text("#comoler-corpo")
        ok(o["rotulo"] in txt, f"{o['rotulo']}: aparece na legenda")
        # existe noticia com essa marca, e ela desenha algo ao lado?
        tem = pg.evaluate(
            """(id) => {
                 const n = S.news.find(x => (x.orientacao||[]).includes(id));
                 if (!n) return {semNoticia: true};
                 const g = marcasOrient(n.orientacao, n.dir, 100, 100, 6);
                 return {semNoticia: false, desenha: g.length > 0,
                         nMarcas: (g.match(/<(path|circle)/g)||[]).length,
                         orient: n.orientacao};
               }""", o["id"])
        if tem.get("semNoticia"):
            print(f"  [PULA] {o['rotulo']}: nenhuma notícia com esta marca")
            continue
        ok(tem["desenha"], f"{o['rotulo']}: desenha marca ao lado do marcador",
           f"{tem['nMarcas']} marca(s) para {tem['orient']}")

    # a marca do PASSADO aponta para a esquerda e a do FUTURO para a direita
    sentido = pg.evaluate(
        """() => {
             const pass = marcasOrient(['passado'], 'flat', 100, 100, 6);
             const fut  = marcasOrient(['futuro'],  'flat', 100, 100, 6);
             const pres = marcasOrient(['presente'],'flat', 100, 100, 6);
             const xs = s => (s.match(/[-\\d.]+(?=,)/g)||[]).map(Number);
             return {passado: xs(pass), futuro: xs(fut), presente: pres.includes('circle')};
           }""")
    # chevron do passado: o ponto do meio e o MENOR x (aponta para a esquerda)
    p_xs, f_xs = sentido["passado"], sentido["futuro"]
    ok(len(p_xs) == 3 and p_xs[1] < p_xs[0],
       "Passado: a seta aponta para a ESQUERDA (←)", str(p_xs))
    ok(len(f_xs) == 3 and f_xs[1] > f_xs[0],
       "Futuro: a seta aponta para a DIREITA (→)", str(f_xs))
    ok(sentido["presente"], "Presente: é um ponto, não uma seta")

    # "pode ter mais de uma marca de tempo"
    duas = pg.evaluate(
        """() => {
             const n = S.news.find(x => (x.orientacao||[]).length === 2);
             if (!n) return null;
             const g = marcasOrient(n.orientacao, n.dir, 100, 100, 6);
             return {orient: n.orientacao, titulo: n.title.slice(0,60),
                     marcas: (g.match(/<(path|circle)/g)||[]).length};
           }""")
    ok(duas and duas["marcas"] == 2,
       "a nota 'pode ter mais de uma marca' é verdade: duas marcas desenhadas",
       str(duas))

    print("\n== SEÇÃO: COR E SENTIDO ==")
    cores = pg.evaluate(
        """() => {
             const out = {};
             for (const d of ['up','down','flat']) {
               const n = S.news.find(x => x.dir === d && formaDe(x.tipo_evento) === 'direcional');
               if (!n) { out[d] = null; continue; }
               const el = document.querySelector(`#chart .mk[data-id="${n.id}"]`);
               const cs = getComputedStyle(el);
               out[d] = {fill: cs.fill, tag: el.tagName.toLowerCase(),
                         s_papel: n.s_papel !== undefined ? n.s_papel : n.s};
             }
             return out;
           }""")
    if cores["up"]:
        ok(verdeish(rgb(cores["up"]["fill"])),
           "Verde apontando para cima: marcador de alta é verde", cores["up"]["fill"])
        ok(cores["up"]["tag"] == "path", "…e é triângulo (path), não círculo")
        ok(cores["up"]["s_papel"] > 0, "…e corresponde a nota POSITIVA",
           cores["up"]["s_papel"])
    if cores["down"]:
        ok(vermelhoish(rgb(cores["down"]["fill"])),
           "Vermelho apontando para baixo: marcador de queda é vermelho",
           cores["down"]["fill"])
        ok(cores["down"]["s_papel"] < 0, "…e corresponde a nota NEGATIVA",
           cores["down"]["s_papel"])
    if cores["flat"]:
        ok(cinzaish(rgb(cores["flat"]["fill"])),
           "Cinza redondo: marcador neutro é cinza", cores["flat"]["fill"])
        ok(cores["flat"]["tag"] == "circle", "…e é círculo, não triângulo")
        ok(abs(cores["flat"]["s_papel"]) <= 0.1,
           "…e corresponde a nota perto de zero", cores["flat"]["s_papel"])

    print("\n== SEÇÃO: TAMANHO E POSIÇÃO ==")
    tam = pg.evaluate(
        """() => {
             const com = S.news.filter(n => document.querySelector(`#chart .mk[data-id="${n.id}"]`));
             const raio = n => {
               const el = document.querySelector(`#chart .mk[data-id="${n.id}"]`);
               if (el.tagName.toLowerCase() === 'circle') return +el.getAttribute('r');
               const ns = (el.getAttribute('d').match(/[-\\d.]+/g)||[]).map(Number);
               const ys = ns.filter((_,i)=>i%2===1);
               return (Math.max(...ys) - Math.min(...ys)) / 2;
             };
             const ord = [...com].sort((a,b)=>a.w-b.w);
             const leve = ord[0], pesada = ord[ord.length-1];
             return {wLeve: leve.w, rLeve: raio(leve), wPesada: pesada.w, rPesada: raio(pesada)};
           }""")
    ok(tam["rPesada"] > tam["rLeve"],
       "Tamanho = peso: a notícia de maior peso é desenhada maior",
       f"peso {tam['wLeve']:.3f}→raio {tam['rLeve']:.1f} | "
       f"peso {tam['wPesada']:.3f}→raio {tam['rPesada']:.1f}")

    haste = pg.evaluate(
        """() => {
             const l = document.querySelectorAll('#chart line.stem');
             if (!l.length) return null;
             const e = l[0];
             return {n: l.length, dash: getComputedStyle(e).strokeDasharray,
                     x1: e.getAttribute('x1'), x2: e.getAttribute('x2'),
                     y1: +e.getAttribute('y1'), y2: +e.getAttribute('y2')};
           }""")
    ok(haste and haste["n"] > 0, "Haste pontilhada: existe no gráfico",
       f"{haste['n']} hastes" if haste else "nenhuma")
    if haste:
        ok(haste["dash"] not in ("none", ""), "…e é pontilhada de fato",
           haste["dash"])
        ok(haste["x1"] == haste["x2"], "…e é vertical, ligando marcador ao preço")

    faixa = pg.evaluate(
        """() => {
             const b = document.querySelectorAll('#chart .bar');
             return {n: b.length,
                     temUp: !!document.querySelector('#chart .bar.up'),
                     temDown: !!document.querySelector('#chart .bar.down')};
           }""")
    ok(faixa["n"] > 0, "Faixa inferior: as barras de pressão existem",
       f"{faixa['n']} barras")
    ok(faixa["temUp"] and faixa["temDown"],
       "…com barras para cima e para baixo (pressão com sinal)")

    print("\n== AS DUAS NOTAS DO RODAPÉ ==")
    # "o triangulo vazado aponta pelo efeito no papel, nao pelo tom do texto"
    papel = pg.evaluate(
        """() => {
             const inv = S.news.filter(n => n.driver && n.sinal_driver < 0);
             if (!inv.length) return {semCaso: true};
             const n = inv[0];
             return {semCaso: false, s: n.s, s_papel: n.s_papel, dir: n.dir,
                     dirDoTexto: n.s > 0.1 ? 'up' : n.s < -0.1 ? 'down' : 'flat'};
           }""")
    if papel.get("semCaso"):
        print("  [PULA] nenhuma notícia roteada com beta negativo neste período;")
        print("         a regra é verificada em scripts/test_evento.py")
    else:
        ok(papel["dir"] != papel["dirDoTexto"],
           "efeito no papel inverte o lado quando o beta é negativo", str(papel))

    # "nem o tipo nem o tempo entram no calculo do sinal"
    sinal = pg.evaluate("() => S.sig ? S.sig.z : null")
    pg.click("#lg-tipo button[data-tipo='corporativo']")
    pg.wait_for_timeout(300)
    sinal2 = pg.evaluate("() => S.sig ? S.sig.z : null")
    vis = pg.eval_on_selector_all("#chart .mk", "e=>e.length")
    pg.click("#lg-tipo button[data-tipo='corporativo']")
    pg.wait_for_timeout(300)
    vis2 = pg.eval_on_selector_all("#chart .mk", "e=>e.length")
    ok(sinal == sinal2,
       "filtrar a legenda NÃO muda o sinal z — tipo e tempo só descrevem",
       f"z {sinal} -> {sinal2}")
    ok(vis != vis2 or vis2 > vis,
       "…mas muda o que a tela mostra", f"{vis} marcadores com filtro, {vis2} sem")

    nav.close()

print()
if FALHAS:
    print(f"{len(FALHAS)} ITEM(NS) FALHARAM:")
    for f in FALHAS:
        print("  -", f)
    sys.exit(1)
print("todos os itens da legenda conferem com o gráfico")
