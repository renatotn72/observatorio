import requests
import json
import os
import time
import re
import subprocess
# Flask quando instalado; senao o adaptador de stdlib (_miniflask.py).
# Este ambiente nao tem flask nem pip -- sem o plano B o proxy nao sobe.
try:
    from flask_cors import CORS, cross_origin
    from flask import Flask, request, jsonify, Response, stream_with_context
except ImportError:  # pragma: no cover
    from _miniflask import (CORS, Flask, Response, cross_origin, jsonify,
                            request, stream_with_context)
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
PROPERTIES_FILE = BASE_DIR / "mcp-models.properties"
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DEFAULT_BASE_URL = "https://sai-library.saiapplications.com"
DEFAULT_TEMPLATE_ID = "689529a9bc6f5e4a68e53eb3"
DEFAULT_PUBLIC_MODEL = "gpt-5.5"
DEFAULT_REFERER = "https://sai-library.saiapplications.com/free-chat"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

LAST_CALL_DEBUG = {}


# ============================================================================
# 1. CONFIGURACAO
# ============================================================================

def carregar_properties(caminho_arquivo=None):
    """ Carrega somente o arquivo mcp-models.properties ao lado do main.py. A configuração do proxy vem exclusivamente deste arquivo. """
    config = {}

    caminho = Path(caminho_arquivo) if caminho_arquivo else PROPERTIES_FILE

    if not caminho.exists():
        print(f"⚠️ Arquivo de configuração não encontrado: {caminho}")
        return config

    with caminho.open("r", encoding="utf-8") as file:
        for linha in file:
            linha = linha.strip()

            if not linha:
                continue

            if linha.startswith("#"):
                continue

            if "=" not in linha:
                continue

            chave, valor = linha.split("=", 1)

            config[chave.strip()] = valor.strip()

    return config


def mascarar_cookie(cookie_header):
    if not cookie_header:
        return ""

    if len(cookie_header) <= 70:
        return cookie_header[:25] + "...REDACTED"

    return cookie_header[:45] + "...REDACTED..." + cookie_header[-18:]


def montar_cookie_header(config):
    """ Formatos aceitos: sai.cookie=.AspNetCore.Cookies=xxxxx sai.cookie=xxxxx mcp.streaming.cookieValue=xxxxx """

    cookie = (
        config.get("sai.cookie", "").strip()
        or config.get("mcp.streaming.cookieValue", "").strip()
    )

    if not cookie:
        return ""

    if cookie.startswith(".AspNetCore.Cookies="):
        return cookie

    return f".AspNetCore.Cookies={cookie}"


def get_modelo_publico(config):
    """ Modelo que o Hermes/OpenAI client enxerga. Nao precisa ser igual ao template real do SAI. """
    return config.get("proxy.modelName", DEFAULT_PUBLIC_MODEL)


def get_template_id(config):
    """ Template real usado no endpoint do SAI. """
    return config.get("sai.templateId", DEFAULT_TEMPLATE_ID)


# ============================================================================
# 2. CONVERSAO DE MENSAGENS OPENAI -> SAI
# ============================================================================

def normalizar_content(content):
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        partes = []

        for parte in content:
            if isinstance(parte, dict):
                if parte.get("type") == "text":
                    partes.append(str(parte.get("text", "")))
                elif "text" in parte:
                    partes.append(str(parte.get("text", "")))
                else:
                    partes.append(json.dumps(parte, ensure_ascii=False))
            else:
                partes.append(str(parte))

        return "\n".join([p for p in partes if p])

    return str(content)


def extrair_ultimo_usuario(mensagens_openai):
    for msg in reversed(mensagens_openai or []):
        if not isinstance(msg, dict):
            continue

        if msg.get("role") == "user":
            content = normalizar_content(msg.get("content", ""))
            if content.strip():
                return content

    return ""


def montar_prompt_cirurgico_para_sai(req_data):
    mensagens_openai = req_data.get("messages", [])
    ultimo_usuario = extrair_ultimo_usuario(mensagens_openai)
    tem_resultado_tool = existe_resultado_tool_apos_ultimo_user(mensagens_openai)

    # Captura a lista de ferramentas que o Hermes enviou na requisicao!
    nomes_tools = nomes_tools_disponiveis(req_data)
    tools_str = extrair_assinaturas_ferramentas(req_data)

    prompt = """
Voce e o cerebro de analise do Hermes Agent.
Caminhos padrao:
- EAIGEFOR: /home/rtnati/git/features/eaigefor/eaigefor
- GEFOR: /home/rtnati/git/features/gefor/gefor

Regras de ouro:
1. Responda sempre em portugues.
2. Nunca peca para o usuario executar comandos de terminal manualmente.
3. Nao invente respostas se nao tiver certeza.
""".strip()

    if tem_resultado_tool:
        prompt += """
STATUS ATUAL: SINTESE OU CONTINUACAO DE BUSCA
Voce acabou de receber o bloco "Resultado da ferramenta".
Avalie o retorno:
- Se os dados JA RESPONDEM a pergunta original, escreva a resposta final em texto normal.
- Se os dados NAO SAO SUFICIENTES (ex: um 'pwd' revelou a pasta, mas voce ainda precisa de um 'ls' ou 'read_file' para entender o projeto), continue investigando!
- Para continuar, responda APENAS com um novo bloco JSON invocando a proxima ferramenta necessaria.
- REGRA ANTI-LOOP: Nunca repita a mesma ferramenta e os mesmos argumentos que acabaram de ser executados no log acima.
""".rstrip()

    else:
        prompt += f"""

STATUS ATUAL: PLANEJAMENTO E EXECUCAO
Voce tem acesso as seguintes ferramentas via Hermes Agent: [{tools_str}]

Se precisar agir no sistema, navegar na web, manipular midia, gerenciar memoria, ler arquivos ou orquestrar tarefas, NAO escreva texto explicando o que vai fazer.
Responda APENAS com um bloco JSON valido contendo a ferramenta desejada, usando estritamente este formato:

Exemplo Arquivos: {{"tool_name": "read_file", "args": {{"file_path": "caminho"}}}}
Exemplo Terminal: {{"tool_name": "terminal", "args": {{"command": "pwd"}}}}
Exemplo Web: {{"tool_name": "web_search", "args": {{"query": "termo"}}}}
Exemplo Browser: {{"tool_name": "browser_navigate", "args": {{"url": "https://..."}}}}
Exemplo Orquestracao: {{"tool_name": "cronjob", "args": {{"action": "list"}}}}
Exemplo Memoria: {{"tool_name": "session_search", "args": {{"query": "assunto"}}}}

Importante: Escolha APENAS uma ferramenta da lista disponivel.
""".rstrip()

    if ultimo_usuario:
        prompt += "\n\nPedido atual do usuario:\n" + ultimo_usuario

    return prompt

def extrair_texto_tool_message(msg):
    """ Converte uma mensagem role=tool do protocolo OpenAI/Hermes em texto legivel para o SAI. """

    tool_name = msg.get("name") or msg.get("tool_name") or "ferramenta"
    tool_call_id = msg.get("tool_call_id", "")
    content = normalizar_content(msg.get("content", ""))

    if not content.strip():
        content = "[sem conteudo retornado pela ferramenta]"

    return (
        f"Resultado da ferramenta {tool_name}"
        + (f" tool_call_id={tool_call_id}" if tool_call_id else "")
        + ":\n"
        + content
    )


def existe_resultado_tool_apos_ultimo_user(mensagens_openai):
    mensagens = mensagens_openai or []

    ultimo_user_idx = -1

    for i, msg in enumerate(mensagens):
        if isinstance(msg, dict) and msg.get("role") == "user":
            ultimo_user_idx = i

    if ultimo_user_idx < 0:
        return False

    for msg in mensagens[ultimo_user_idx + 1:]:
        if isinstance(msg, dict) and msg.get("role") == "tool":
            return True

    return False


def existe_tool_call_assistente_apos_ultimo_user(mensagens_openai):
    mensagens = mensagens_openai or []

    ultimo_user_idx = -1

    for i, msg in enumerate(mensagens):
        if isinstance(msg, dict) and msg.get("role") == "user":
            ultimo_user_idx = i

    if ultimo_user_idx < 0:
        return False

    for msg in mensagens[ultimo_user_idx + 1:]:
        if not isinstance(msg, dict):
            continue

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return True

    return False


def deve_bloquear_novo_tool_call(req_data):
    """ Regra principal anti-loop. """
    mensagens = req_data.get("messages", []) or []

    if existe_resultado_tool_apos_ultimo_user(mensagens):
        return True

    return False
    
def converter_messages_openai_para_sai(req_data, config=None):
    # Mudamos o parametro para receber o req_data inteiro
    mensagens_openai = req_data.get("messages", [])
    config = config or {}

    modo_prompt = config.get("proxy.promptMode", "surgical").strip().lower()
    if modo_prompt == "raw":
        return converter_messages_openai_para_sai_raw(mensagens_openai)

    messages = []

    # Aqui passamos req_data para o prompt gerar as ferramentas dinamicamente
    prompt_cirurgico = montar_prompt_cirurgico_para_sai(req_data)

    # ... restante da funcao continua igual ...

    messages.append({
        "content": prompt_cirurgico,
        "role": "user"
    })

    max_historico = int(config.get("proxy.maxHistoryMessages", "12"))

    historico_limpo = []

    for msg in mensagens_openai or []:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "user")

        if role in ["system", "developer"]:
            continue

        if role in ["user", "assistant"]:
            content = normalizar_content(msg.get("content", ""))

            if not content.strip():
                continue

            historico_limpo.append({
                "content": content,
                "role": role
            })

        elif role == "tool":
            tool_text = extrair_texto_tool_message(msg)

            historico_limpo.append({
                "content": tool_text,
                "role": "user"
            })

        else:
            content = normalizar_content(msg.get("content", ""))

            if content.strip():
                historico_limpo.append({
                    "content": content,
                    "role": "user"
                })

    if historico_limpo:
        for msg in historico_limpo[-max_historico:]:
            messages.append(msg)

    if not messages:
        messages.append({
            "content": "Prosseguir",
            "role": "user"
        })

    return messages


def converter_messages_openai_para_sai_raw(mensagens_openai):
    messages = []
    system_parts = []

    for msg in mensagens_openai or []:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "user")
        content = normalizar_content(msg.get("content", ""))

        if not content.strip():
            continue

        if role in ["system", "developer"]:
            system_parts.append(content)
        elif role in ["user", "assistant"]:
            messages.append({"content": content, "role": role})
        else:
            messages.append({"content": content, "role": "user"})

    if system_parts:
        messages.insert(0, {
            "content": "Instrucoes do sistema:\n\n" + "\n\n".join(system_parts),
            "role": "user"
        })

    if not messages:
        messages.append({"content": "Prosseguir", "role": "user"})

    return messages


# ============================================================================
# 3. REQUEST SAI
# ============================================================================

def montar_sai_request(messages, config):
    base_url = config.get("sai.baseUrl", DEFAULT_BASE_URL).rstrip("/")
    template_id = get_template_id(config)

    url = f"{base_url}/api/templates/{template_id}/chatexecute"

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "[object Object]",
        "content-type": "application/json",
        "dnt": "1",
        "origin": config.get("sai.origin", base_url),
        "priority": "u=1, i",
        "referer": config.get("sai.referer", DEFAULT_REFERER),
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-gpc": "1",
        "user-agent": config.get("sai.userAgent", DEFAULT_USER_AGENT)
    }

    cookie_header = montar_cookie_header(config)

    if cookie_header:
        headers["cookie"] = cookie_header

    body = {
        "messages": messages
    }

    return url, headers, body


def is_login_html(texto):
    if not texto:
        return False

    t = texto[:5000].lower()

    return (
        "sign in to your account" in t
        or "login.microsoftonline.com" in t
        or "convergedsignin" in t
        or ("<html" in t and "microsoft" in t and "signin" in t)
    )


def extrair_texto_resposta_sai(data):
    if data is None:
        return ""

    if isinstance(data, str):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("message"), str):
            return data.get("message")

        for chave in ["content", "text", "response", "answer", "result", "output"]:
            if isinstance(data.get(chave), str):
                return data.get(chave)

        if isinstance(data.get("message"), dict):
            msg = data.get("message")
            if isinstance(msg.get("content"), str):
                return msg.get("content")

        return json.dumps(data, ensure_ascii=False)

    return json.dumps(data, ensure_ascii=False)


def chamar_sai_chatexecute(messages, config):
    global LAST_CALL_DEBUG

    url, headers, body = montar_sai_request(messages, config)
    timeout_seconds = int(config.get("sai.timeoutSeconds", "120"))

    headers_debug = dict(headers)

    if "cookie" in headers_debug:
        headers_debug["cookie"] = mascarar_cookie(headers_debug["cookie"])

    LAST_CALL_DEBUG = {
        "timestamp": int(time.time()),
        "method": "POST",
        "url": url,
        "headers": headers_debug,
        "body": body,
        "timeout": {
            "connectSeconds": 15,
            "readSeconds": timeout_seconds
        },
        "allowRedirects": False
    }

    print("\n" + "=" * 100)
    print("➡️ CHAMADA REAL PARA SAI")
    print("=" * 100)
    print("METHOD: POST")
    print("URL:", url)
    print("\nHEADERS:")
    print(json.dumps(headers_debug, ensure_ascii=False, indent=2))
    print("\nBODY:")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print("\nallow_redirects: False")
    print("=" * 100 + "\n")

    resp = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=(15, timeout_seconds),
        allow_redirects=False
    )

    body_preview = resp.text[:3000] if resp.text else ""
    response_headers = dict(resp.headers)

    LAST_CALL_DEBUG["response"] = {
        "statusCode": resp.status_code,
        "headers": response_headers,
        "bodyPreview": body_preview,
        "isRedirect": resp.is_redirect,
        "location": resp.headers.get("Location")
    }

    print("\n" + "=" * 100)
    print("⬅️ RESPOSTA SAI")
    print("=" * 100)
    print("STATUS:", resp.status_code)
    print("IS_REDIRECT:", resp.is_redirect)
    print("LOCATION:", resp.headers.get("Location"))
    print("\nRESPONSE HEADERS:")
    print(json.dumps(response_headers, ensure_ascii=False, indent=2))
    print("\nRESPONSE BODY PREVIEW:")
    print(body_preview)
    print("=" * 100 + "\n")

    if resp.is_redirect or resp.status_code in [301, 302, 303, 307, 308]:
        location = resp.headers.get("Location", "")
        raise PermissionError(
            "SAI redirecionou para login. Isso normalmente significa cookie ausente, expirado "
            f"ou diferente do cookie que funciona no curl. Location: {location}"
        )

    if is_login_html(resp.text):
        raise PermissionError(
            "SAI retornou HTML de login Microsoft. O cookie usado pelo Python nao esta autenticando. "
            "Copie exatamente o cookie do curl que funciona para sai.cookie no mcp-models.properties."
        )

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(
            f"{str(e)} | Body preview: {body_preview}",
            response=resp
        )

    content_type = resp.headers.get("content-type", "")

    if "application/json" in content_type:
        data = resp.json()
    else:
        texto = resp.text.strip()

        try:
            data = json.loads(texto)
        except json.JSONDecodeError:
            data = texto

    LAST_CALL_DEBUG["parsedResponse"] = data

    return extrair_texto_resposta_sai(data), data


# ============================================================================
# 4. TOOL CALLS OPENAI PARA HERMES
# ============================================================================

def nomes_tools_disponiveis(req_data):
    nomes = set()

    for tool in req_data.get("tools", []) or []:
        if not isinstance(tool, dict):
            continue

        if tool.get("type") == "function":
            fn = tool.get("function") or {}
            name = fn.get("name")
            if name:
                nomes.add(name)

    return nomes


def tem_tool(req_data, nome):
    return nome in nomes_tools_disponiveis(req_data)


def inferir_path_padrao(req_data, config):
    ultimo = extrair_ultimo_usuario(req_data.get("messages", [])).lower()

    if "eaigefor" in ultimo:
        return config.get(
            "proxy.eaigeforPath",
            "/home/rtnati/git/features/eaigefor/eaigefor"
        )

    if "gefor" in ultimo:
        return config.get(
            "proxy.geforPath",
            "/home/rtnati/git/features/gefor/gefor"
        )

    return config.get(
        "proxy.defaultSearchPath",
        "/home/rtnati/git"
    )


def inferir_pattern_busca(req_data):
    ultimo = extrair_ultimo_usuario(req_data.get("messages", []))

    termos = []

    candidatos = [
        "reciclag",
        "recicla",
        "curso",
        "agend",
        "agendamento",
        "TRX",
        "controller",
        "Action",
        "transacao"
    ]

    texto_lower = ultimo.lower()

    for termo in candidatos:
        if termo.lower() in texto_lower:
            termos.append(termo)

    if not termos:
        termos = ["reciclag", "recicla", "curso", "agend", "agendamento", "TRX"]

    escaped = []

    for termo in termos:
        escaped.append(re.escape(termo))

    return "(?i)" + "|".join(escaped)

def extrair_caminho_arquivo_do_texto(texto):
    """ Tenta capturar um caminho de arquivo util no texto gerado pela IA """
    match = re.search(r'([a-zA-Z0-9_/\-\.]+\.[a-zA-Z0-9]+)', texto)
    if match:
        return match.group(1).strip()
    return ""
 
def extrair_assinaturas_ferramentas(req_data):
    """ Lê as ferramentas enviadas pelo Hermes e extrai os campos obrigatorios """
    assinaturas = []
    
    for tool in req_data.get("tools", []) or []:
        if isinstance(tool, dict) and tool.get("type") == "function":
            fn = tool.get("function") or {}
            name = fn.get("name")
            
            if name:
                params = fn.get("parameters", {})
                required = params.get("required", [])
                
                if required:
                    # Monta string: fact_store (Exige: "action")
                    req_str = ", ".join([f'"{req}"' for req in required])
                    assinaturas.append(f'{name} (Exige: {req_str})')
                else:
                    assinaturas.append(name)
                    
    return ", ".join(assinaturas) if assinaturas else "Nenhuma ferramenta"

def detectar_pedido_de_ferramenta(texto, req_data, config):
    if not texto:
        return None

    if not req_data.get("tools"):
        return None

    # Regex gulosa: do primeiro '{' ate o ultimo '}'
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    
    if match:
        bloco_json = match.group(0)
        try:
            comando_ia = json.loads(bloco_json)
            
            # 1. Aceita tanto 'tool_name' quanto apenas 'tool'
            nome = comando_ia.get("tool_name")
            if not nome:
                nome = comando_ia.get("tool")
                
            # 2. Busca o bloco 'args'. Se nao existir, agrupa os campos da raiz.
            args = comando_ia.get("args")
            if args is None:
                # Copia tudo que nao for o nome da ferramenta para dentro de args
                args = {}
                for chave, valor in comando_ia.items():
                    if chave != "tool_name" and chave != "tool":
                        args[chave] = valor
            
            # Tolerancia para search_files
            if nome == "search_files":
                args = {
                    "pattern": args.get("pattern") or args.get("query") or ".*",
                    "path": args.get("path") or inferir_path_padrao(req_data, config),
                    "file_glob": "*.java",
                    "limit": 50,
                    "output_mode": "content",
                    "context": 2
                }
                
            # Tolerancia para fact_store
            if nome == "fact_store":
                if "action" not in args:
                    args["action"] = "add"

            if nome:
                return {
                    "name": nome,
                    "arguments": args
                }
                
        except Exception as e:
            print("⚠️ [PROXY] Erro ao tentar ler o JSON da IA:", str(e))
            pass

def montar_openai_tool_call_response(chat_id, modelo_final, tool_name, arguments):
    return {
        "id": chat_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{int(time.time())}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False)
                            }
                        }
                    ]
                },
                "finish_reason": "tool_calls"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }


def gerar_stream_tool_call(chat_id, modelo_final, tool_name, arguments):
    created = int(time.time())
    call_id = f"call_{created}"
    arguments_json = json.dumps(arguments, ensure_ascii=False)

    chunk_1 = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant"
                },
                "finish_reason": None
            }
        ]
    }

    yield f"data: {json.dumps(chunk_1, ensure_ascii=False)}\n\n"

    chunk_2 = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": ""
                            }
                        }
                    ]
                },
                "finish_reason": None
            }
        ]
    }

    yield f"data: {json.dumps(chunk_2, ensure_ascii=False)}\n\n"

    chunk_3 = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {
                                "arguments": arguments_json
                            }
                        }
                    ]
                },
                "finish_reason": None
            }
        ]
    }

    yield f"data: {json.dumps(chunk_3, ensure_ascii=False)}\n\n"

    chunk_final = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "tool_calls"
            }
        ]
    }

    yield f"data: {json.dumps(chunk_final, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================================
# 5. RESPOSTAS OPENAI
# ============================================================================

def montar_openai_chat_response(chat_id, modelo_final, texto_completo):
    if texto_completo is None:
        texto_completo = ""

    texto_completo = str(texto_completo)

    if not texto_completo.strip():
        texto_completo = "[Proxy Warning: resposta vazia.]"

    return {
        "id": chat_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": texto_completo
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }


def gerar_stream_texto(chat_id, modelo_final, texto_completo, config):
    created = int(time.time())

    first_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant"
                },
                "finish_reason": None
            }
        ]
    }

    yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

    content_to_send = texto_completo

    if content_to_send is None:
        content_to_send = ""

    content_to_send = str(content_to_send)

    if not content_to_send.strip():
        content_to_send = "[Proxy Warning: resposta vazia.]"

    chunk_size = int(config.get("proxy.streamChunkSize", "120"))

    if chunk_size <= 0:
        chunk_size = 120

    for i in range(0, len(content_to_send), chunk_size):
        delta_text = content_to_send[i:i + chunk_size]

        chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": modelo_final,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": delta_text
                    },
                    "finish_reason": None
                }
            ]
        }

        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    final_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": modelo_final,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }
        ]
    }

    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"

    usage_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": modelo_final,
        "choices": [],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

    yield f"data: {json.dumps(usage_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================================
# 6. ROTAS
# ============================================================================

@app.route("/", methods=["GET"])
@cross_origin()
def root():
    return jsonify({
        "status": "ok",
        "service": "sai-openai-proxy",
        "port": 8100,
        "endpoints": [
            "GET /health",
            "GET /v1/models",
            "GET /api/tags",
            "GET /debug/last-call",
            "POST /v1/chat/completions"
        ]
    })


@app.route("/health", methods=["GET"])
@cross_origin()
def health():
    return jsonify({
        "status": "ok"
    })


@app.route("/debug/last-call", methods=["GET"])
@cross_origin()
def debug_last_call():
    return jsonify(LAST_CALL_DEBUG or {
        "message": "Nenhuma chamada SAI feita ainda."
    })


@app.route("/api/tags", methods=["GET"])
@app.route("/v1/models", methods=["GET"])
@cross_origin()
def list_models():
    config = carregar_properties()
    modelo_publico = get_modelo_publico(config)

    return jsonify({
        "object": "list",
        "models": [
            {
                "name": modelo_publico
            }
        ],
        "data": [
            {
                "id": modelo_publico,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "sai-proxy"
            }
        ]
    })


@app.route("/v1/chat/completions", methods=["POST"])
@cross_origin()
def openai_proxy_chat_completions():
    req_data = request.get_json(silent=True) or {}

    print("\n" + "=" * 100)
    print("📥 REQUEST RECEBIDO EM /v1/chat/completions")
    print("=" * 100)
    # print(json.dumps(req_data, ensure_ascii=False, indent=2))
    # print("=" * 100 + "\n")

    config = carregar_properties()

    modelo_final = get_modelo_publico(config)
    chat_id = f"chatcmpl-sai-{int(time.time())}"

    raw_stream = req_data.get("stream", False)
    is_stream = str(raw_stream).lower() in ["true", "1", "yes"]

    resposta_bruta_sai = None
    erro_detectado = False
    texto_completo = ""

    try:
        # ATENCAO: Aqui passamos o req_data inteiro, e nao apenas a lista de messages
        messages_sai = converter_messages_openai_para_sai(
            req_data,
            config
        )

        texto_completo, resposta_bruta_sai = chamar_sai_chatexecute(
            messages_sai,
            config
        )

        if texto_completo is None:
            texto_completo = ""

        texto_completo = str(texto_completo)

        if not texto_completo.strip():
            texto_completo = "[Proxy Warning: SAI retornou resposta vazia.]"
            erro_detectado = True

    except PermissionError as e:
        print(f"🔐 [PROXY] Erro de autenticacao: {e}")
        texto_completo = f"[SAI Auth Error: {str(e)}]"
        erro_detectado = True

    except requests.exceptions.RequestException as e:
        print(f"❌ [PROXY] Erro HTTP/rede com a SAI: {e}")
        texto_completo = f"[Network Proxy Error: {str(e)}]"
        erro_detectado = True

    except Exception as e:
        print(f"❌ [PROXY] Erro inesperado: {e}")
        texto_completo = f"[Proxy Error: {str(e)}]"
        erro_detectado = True

    # =========================================================================
    # DETECCAO SEMANTICA DE FERRAMENTA (Baseada no JSON da IA)
    # =========================================================================

    tool_request = None

    if not erro_detectado:
        tool_request = detectar_pedido_de_ferramenta(
            texto_completo,
            req_data,
            config
        )

    # Se a IA enviou um JSON pedindo acao, o proxy manda o Hermes executar
    if tool_request:
        print("\n" + "=" * 100)
        print("🛠️ CONVERTENDO RESPOSTA TEXTUAL DO SAI EM TOOL_CALL OPENAI")
        print("=" * 100)
        print(json.dumps(tool_request, ensure_ascii=False, indent=2))
        print("=" * 100 + "\n")

        if is_stream:
            return Response(
                stream_with_context(
                    gerar_stream_tool_call(
                        chat_id,
                        modelo_final,
                        tool_request["name"],
                        tool_request["arguments"]
                    )
                ),
                status=200,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )

        response_tool = montar_openai_tool_call_response(
            chat_id,
            modelo_final,
            tool_request["name"],
            tool_request["arguments"]
        )

        return jsonify(response_tool), 200

    # Se nao for ferramenta, devolve a resposta final em texto
    if is_stream:
        return Response(
            stream_with_context(
                gerar_stream_texto(
                    chat_id,
                    modelo_final,
                    texto_completo,
                    config
                )
            ),
            status=200,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    response_openai = montar_openai_chat_response(
        chat_id,
        modelo_final,
        texto_completo
    )

    return jsonify(response_openai), 200


# ============================================================================
# 7. INICIALIZACAO
# ============================================================================

if __name__ == "__main__":
    config = carregar_properties()

    porta = int(config.get("server.port", os.environ.get("PORT", "8100")))

    print("\n🚀 SAI OpenAI Proxy iniciado")
    print("=" * 74)
    print(f"🌐 Porta: {porta}")
    print(f"🤖 Template real SAI: {get_template_id(config)}")
    print(f"🤖 Modelo publico: {get_modelo_publico(config)}")
    print(f"📍 Health: http://localhost:{porta}/health")
    print(f"📍 Models: http://localhost:{porta}/v1/models")
    print(f"📍 Chat: http://localhost:{porta}/v1/chat/completions")
    print(f"📍 Debug: http://localhost:{porta}/debug/last-call")
    print("=" * 74 + "\n")

    app.run(host="0.0.0.0", port=porta, threaded=True)
