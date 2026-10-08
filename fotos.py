"""
Fotos das pessoas para o modo TV e o Explorar.

Desde 2026-10-08 as fotos são casadas pelo LOGIN do CRM (único), e não mais
pelo primeiro nome — com a entrada do PV 03 passaram a existir várias
pessoas com o mesmo primeiro nome (duas Larissas, duas Rafaelas, dois
Brunos, Flavio Manoel x Flávio dono do PV 02...), e o casamento por primeiro
nome trocava as fotos.

Arquivos: static/fotos/pessoas/<parte do login antes do @>.jpg
  ex: agnes.reis@global       -> static/fotos/pessoas/agnes.reis.jpg
      larissa.menezes@grupoglobal.net.br -> static/fotos/pessoas/larissa.menezes.jpg

Se não houver arquivo pelo login, tenta pelo nome (sem acento, minúsculo,
espaços viram "-"): nome completo do CRM, nome de exibição, e as duas
primeiras palavras do nome (ex: "amanda-coimbra.jpg"). Quem não tiver foto
continua aparecendo com as iniciais.

Fotos de proprietários de PV e de líderes de equipe são definidas em
tv_config.py (PV_FOTOS e EQUIPES[...]["lideres"]).
"""
import os
import re
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PESSOAS_DIR = os.path.join(BASE_DIR, "static", "fotos", "pessoas")
EXTENSOES = (".jpg", ".jpeg", ".png")


def _slug(texto):
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9.]+", "-", t).strip("-")


def _load():
    mapa = {}
    if not os.path.isdir(PESSOAS_DIR):
        return mapa
    for fname in sorted(os.listdir(PESSOAS_DIR)):
        if fname.startswith(".") or not fname.lower().endswith(EXTENSOES):
            continue
        mapa[os.path.splitext(fname)[0].lower()] = "fotos/pessoas/" + fname
    return mapa


# {chave (login sem domínio ou nome em slug): "fotos/pessoas/arquivo.jpg"}
FOTOS_PESSOAS = _load()


def foto_pessoa(login=None, *nomes):
    """Caminho relativo a static/ da foto da pessoa, ou None."""
    chaves = []
    if login:
        chaves.append(str(login).split("@", 1)[0].lower())
    for nome in nomes:
        s = _slug(nome)
        if s:
            chaves.append(s)
            partes = s.split("-")
            if len(partes) > 2:
                chaves.append("-".join(partes[:2]))
    for k in chaves:
        if k in FOTOS_PESSOAS:
            return FOTOS_PESSOAS[k]
    return None
