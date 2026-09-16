"""
Fotos de consultores/supervisores para o modo TV (bolinha do avatar no
cabeçalho). As fotos ficam em static/fotos/<primeiro_nome>.jpg (minúsculo,
sem acento) — cada arquivo casa com a pessoa pelo PRIMEIRO NOME, então tanto
faz se a pessoa aparece como consultor ou como supervisor.

Para adicionar/trocar uma foto: salvar um arquivo .jpg/.jpeg/.png em
static/fotos/ com o primeiro nome da pessoa (ex: kauan.jpg) e reiniciar o
serviço. Quem não tiver foto continua aparecendo com as iniciais, como antes.
"""
import os
import re
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FOTOS_DIR = os.path.join(BASE_DIR, "static", "fotos")


def _norm_first_name(nome):
    if not nome:
        return ""
    first = str(nome).strip().split()[0] if str(nome).strip() else ""
    first = first.upper()
    first = unicodedata.normalize("NFKD", first)
    first = "".join(c for c in first if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", first)


def _load_fotos_map():
    mapping = {}
    if not os.path.isdir(FOTOS_DIR):
        return mapping
    for fname in sorted(os.listdir(FOTOS_DIR)):
        if fname.startswith(".") or not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        stem = os.path.splitext(fname)[0]
        key = _norm_first_name(stem)
        if key:
            mapping[key] = "fotos/" + fname
    return mapping


# {PRIMEIRO_NOME_NORMALIZADO: "fotos/arquivo.jpg"} — caminho relativo a static/
FOTOS_MAP = _load_fotos_map()


def foto_for_nome(nome):
    return FOTOS_MAP.get(_norm_first_name(nome))
