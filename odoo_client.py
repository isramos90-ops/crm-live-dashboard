"""
Cliente JSON-RPC para o CRM (Odoo) da Global.
Credenciais vêm de variáveis de ambiente (ver .env.example) — nunca ficam no código.
"""
import json
import os
import urllib.request

HOST = os.environ.get("CRM_HOST", "https://global.solucoes.plus/jsonrpc")
DB = os.environ.get("CRM_DB", "global")
LOGIN = os.environ.get("CRM_LOGIN", "")
PASSWORD = os.environ.get("CRM_PASSWORD", "")

_uid_cache = None


def _rpc(service, method, args):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {"service": service, "method": method, "args": args},
        "id": 1,
    }
    req = urllib.request.Request(
        HOST,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False))
    return data["result"]


def get_uid(force=False):
    global _uid_cache
    if _uid_cache is None or force:
        if not LOGIN or not PASSWORD:
            raise RuntimeError(
                "CRM_LOGIN/CRM_PASSWORD não configurados (defina as variáveis de ambiente)."
            )
        _uid_cache = _rpc("common", "authenticate", [DB, LOGIN, PASSWORD, {}])
    return _uid_cache


def execute_kw(model, method, args, kwargs=None):
    uid = get_uid()
    try:
        return _rpc(
            "object", "execute_kw", [DB, uid, PASSWORD, model, method, args, kwargs or {}]
        )
    except RuntimeError:
        # tenta re-autenticar uma vez (sessão pode ter expirado do lado do servidor)
        uid = get_uid(force=True)
        return _rpc(
            "object", "execute_kw", [DB, uid, PASSWORD, model, method, args, kwargs or {}]
        )


def search_read(model, domain, fields=None, limit=0, order=None):
    kwargs = {"fields": fields or [], "limit": limit}
    if order:
        kwargs["order"] = order
    return execute_kw(model, "search_read", [domain], kwargs)


def search_count(model, domain):
    return execute_kw(model, "search_count", [domain])


def read_group(model, domain, fields, groupby, lazy=False):
    return execute_kw(model, "read_group", [domain, fields, groupby], {"lazy": lazy})
