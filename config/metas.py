"""
Carrega as metas por equipe (= por supervisor) e por consultor de
config/metas.xlsx (abas EQUIPES e USUARIOS), enviadas pela Isabela em
2026-09-15 como print de uma planilha.

Cada meta tem 4 valores, nos mesmos moldes das 4 categorias de receita já
calculadas em classification.py: RECEITA_TOTAL, QUANTIDADE_BL (qtd. banda
larga), RECEITA_RENOVACAO, RECEITA_APARELHOS.

Para trocar as metas, basta editar config/metas.xlsx (mesmas abas/colunas)
e reiniciar o serviço.
"""
import os
import re
import unicodedata

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
METAS_PATH = os.path.join(BASE_DIR, "config", "metas.xlsx")

METAS_FIELDS = ["RECEITA_TOTAL", "QUANTIDADE_BL", "RECEITA_RENOVACAO", "RECEITA_APARELHOS"]


def _norm(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def empty_meta():
    return {f: 0 for f in METAS_FIELDS}


def _load_sheet(sheet, key_col):
    try:
        df = pd.read_excel(METAS_PATH, sheet_name=sheet)
    except (FileNotFoundError, ValueError):
        return {}
    out = {}
    for _, row in df.iterrows():
        key = _norm(row[key_col])
        if not key:
            continue
        out[key] = {f: float(row[f]) if pd.notna(row[f]) else 0.0 for f in METAS_FIELDS}
    return out


METAS_EQUIPES = _load_sheet("EQUIPES", "EQUIPE")
METAS_USUARIOS = _load_sheet("USUARIOS", "USUARIO")


def meta_for_equipe(nome_equipe):
    return METAS_EQUIPES.get(_norm(nome_equipe), empty_meta())


def meta_for_usuario(nome_usuario):
    return METAS_USUARIOS.get(_norm(nome_usuario), empty_meta())


def sum_metas(*metas):
    total = empty_meta()
    for m in metas:
        for f in METAS_FIELDS:
            total[f] += m.get(f, 0)
    return total
