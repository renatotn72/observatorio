"""Adaptador minimo de Flask sobre http.server da stdlib.

POR QUE EXISTE
    `proxy/main.py` foi escrito em Flask, e este ambiente nao tem `flask` nem
    `pip` para instalar. Reescrever 1.192 linhas seria arriscado e
    desnecessario: o arquivo usa uma superficie minuscula do Flask --
    `route`, `run`, `request.get_json`, `jsonify`, `Response`,
    `stream_with_context` e CORS. Este modulo implementa exatamente isso.

    Com o Flask de verdade instalado, `main.py` o usa e ignora este arquivo.
    Este e o plano B, nao a substituicao.

O QUE NAO IMPLEMENTA
    Blueprints, sessoes, templates, before/after_request, g, url_for,
    conversores de rota alem de <nome>. Se `main.py` passar a usar algo
    disso, o import falha de forma barulhenta em vez de silenciosa.
"""
from __future__ import annotations
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_local = threading.local()


class _Request:
    """Objeto `request` do Flask, na parte que o proxy usa."""

    @property
    def _atual(self):
        return getattr(_local, "req", None)

    def get_json(self, force=False, silent=False):
        r = self._atual
        if r is None:
            return None
        try:
            return json.loads(r["body"] or b"{}")
        except (ValueError, TypeError):
            if silent:
                return None
            raise

    @property
    def json(self):
        return self.get_json(silent=True)

    @property
    def args(self):
        r = self._atual
        return {k: v[0] for k, v in parse_qs(r["query"]).items()} if r else {}

    @property
    def headers(self):
        return self._atual["headers"] if self._atual else {}

    @property
    def method(self):
        return self._atual["method"] if self._atual else "GET"

    @property
    def path(self):
        return self._atual["path"] if self._atual else "/"

    def get_data(self, as_text=False):
        r = self._atual
        b = (r["body"] if r else b"") or b""
        return b.decode("utf-8", "replace") if as_text else b


request = _Request()


class Response:
    def __init__(self, resposta=None, status=200, headers=None,
                 mimetype=None, content_type=None):
        self.corpo = resposta
        self.status_code = status
        self.headers = dict(headers or {})
        tipo = content_type or (f"{mimetype}; charset=utf-8" if mimetype else None)
        if tipo:
            self.headers["Content-Type"] = tipo


def jsonify(*args, **kwargs):
    dado = kwargs if kwargs else (args[0] if len(args) == 1 else list(args))
    return Response(json.dumps(dado, ensure_ascii=False),
                    content_type="application/json; charset=utf-8")


def stream_with_context(gen):
    """No Flask preserva o contexto; aqui o contexto ja e por thread."""
    return gen


def cross_origin(*a, **kw):
    def deco(fn):
        return fn
    return deco


def CORS(app=None, **kw):          # noqa: N802  (nome da API original)
    if app is not None:
        app.cors = True
    return app


class Flask:
    def __init__(self, nome, *a, **kw):
        self.nome = nome
        self.rotas = []            # (metodos, regex, nomes, funcao)
        self.cors = False

    def route(self, regra, methods=None, **kw):
        metodos = [m.upper() for m in (methods or ["GET"])]
        nomes = re.findall(r"<(?:[^:<>]+:)?([^<>]+)>", regra)
        padrao = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"(?P<\1>[^/]+)", regra)

        def deco(fn):
            self.rotas.append((metodos, re.compile(f"^{padrao}/?$"), nomes, fn))
            return fn
        return deco

    def _casa(self, metodo, caminho):
        for metodos, rx, _nomes, fn in self.rotas:
            m = rx.match(caminho)
            if m:
                if metodo not in metodos and metodo != "OPTIONS":
                    continue
                return fn, m.groupdict()
        return None, {}

    def run(self, host="127.0.0.1", port=5000, debug=False, threaded=True, **kw):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                if debug:
                    BaseHTTPRequestHandler.log_message(self, *a)

            def _cors(self):
                if app.cors:
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Headers", "*")
                    self.send_header("Access-Control-Allow-Methods",
                                     "GET,POST,OPTIONS,DELETE,PUT")

            def _responde(self, metodo):
                u = urlparse(self.path)
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(tam) if tam else b""
                _local.req = {"method": metodo, "path": u.path, "query": u.query,
                              "body": corpo, "headers": dict(self.headers)}
                fn, kwargs = app._casa(metodo, u.path)
                if metodo == "OPTIONS":
                    self.send_response(204); self._cors()
                    self.send_header("Content-Length", "0"); self.end_headers()
                    return
                if fn is None:
                    self._envia(404, b'{"error":"not found"}',
                                "application/json; charset=utf-8")
                    return
                try:
                    r = fn(**kwargs)
                except Exception as exc:                          # noqa: BLE001
                    self._envia(500,
                                json.dumps({"error": str(exc)}).encode(),
                                "application/json; charset=utf-8")
                    return
                self._entrega(r)

            def _entrega(self, r):
                if isinstance(r, tuple):
                    r, status = r[0], (r[1] if len(r) > 1 else 200)
                else:
                    status = None
                if isinstance(r, Response):
                    status = status or r.status_code
                    corpo, cabecalhos = r.corpo, r.headers
                elif isinstance(r, (dict, list)):
                    status, corpo = status or 200, json.dumps(r, ensure_ascii=False)
                    cabecalhos = {"Content-Type": "application/json; charset=utf-8"}
                else:
                    status, corpo = status or 200, r
                    cabecalhos = {"Content-Type": "text/plain; charset=utf-8"}

                if hasattr(corpo, "__iter__") and not isinstance(corpo, (str, bytes)):
                    self.send_response(status)
                    for k, v in cabecalhos.items():
                        self.send_header(k, v)
                    self._cors()
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        for pedaco in corpo:
                            if isinstance(pedaco, str):
                                pedaco = pedaco.encode("utf-8")
                            if not pedaco:
                                continue
                            self.wfile.write(f"{len(pedaco):X}\r\n".encode())
                            self.wfile.write(pedaco + b"\r\n")
                            self.wfile.flush()
                        self.wfile.write(b"0\r\n\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return

                if isinstance(corpo, str):
                    corpo = corpo.encode("utf-8")
                self._envia(status, corpo or b"",
                            cabecalhos.get("Content-Type", "text/plain; charset=utf-8"),
                            cabecalhos)

            def _envia(self, status, corpo, tipo, extras=None):
                self.send_response(status)
                for k, v in (extras or {}).items():
                    if k.lower() != "content-type":
                        self.send_header(k, v)
                self.send_header("Content-Type", tipo)
                self._cors()
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                try:
                    self.wfile.write(corpo)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):     self._responde("GET")
            def do_POST(self):    self._responde("POST")
            def do_OPTIONS(self): self._responde("OPTIONS")
            def do_DELETE(self):  self._responde("DELETE")
            def do_PUT(self):     self._responde("PUT")

        srv = ThreadingHTTPServer((host, port), Handler)
        print(f"[miniflask] {app.nome} em http://{host}:{port}  "
              f"({len(app.rotas)} rotas, sem Flask instalado)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
