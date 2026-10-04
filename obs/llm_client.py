"""Cliente para endpoint OpenAI-compatible, inclusive proxy MCP local."""
from __future__ import annotations
import json, os, re, urllib.request, urllib.error
def enabled():
    if os.environ.get("OBS_ALLOW_EXTERNAL_LLM")!="1": return False,"OBS_ALLOW_EXTERNAL_LLM=1 não autorizado"
    for k in ("OBS_LLM_URL","OBS_LLM_KEY","OBS_LLM_MODEL"):
        if not os.environ.get(k): return False,f"{k} ausente"
    return True,"ok"
def parse_json(text):
    text=(text or "").strip()
    for candidate in (text, re.sub(r"^```json\s*|\s*```$","",text,flags=re.S), re.sub(r"^```\s*|\s*```$","",text,flags=re.S)):
        try:return json.loads(candidate)
        except Exception: pass
    m=re.search(r"(\{.*\})",text,re.S)
    if m: return json.loads(m.group(1))
    raise ValueError("resposta não contém JSON válido")
def chat_json(system,user,max_tokens=1400):
    ok,reason=enabled()
    if not ok:return {"ok":False,"error":reason,"external":False}
    payload={"model":os.environ["OBS_LLM_MODEL"],"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0,"max_tokens":max_tokens}
    req=urllib.request.Request(os.environ["OBS_LLM_URL"],data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Authorization":f"Bearer {os.environ['OBS_LLM_KEY']}"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=120) as r: raw=json.loads(r.read().decode())
        text=raw["choices"][0]["message"]["content"]
        return {"ok":True,"data":parse_json(text),"model":os.environ["OBS_LLM_MODEL"],"external":True}
    except (urllib.error.URLError,urllib.error.HTTPError,KeyError,ValueError) as e:
        return {"ok":False,"error":str(e),"external":True}
