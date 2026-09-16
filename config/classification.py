"""
Carrega a metodologia oficial de classificação, fornecida pela Isabela:

- config/etapas_estagio.xlsx: classifica cada etapa do CRM em 4 flags
  (ATENDIDO / CONVERTIDO / CONCLUIDO / EM TRAMITE).
- config/classificacao_receita.xlsx: define, para 4 categorias de receita
  (RECEITA TOTAL, RENOVAÇÃO, BANDA LARGA, APARELHO), quais tipos de
  solicitação e quais categorias de produto contam. Uma linha de pedido só
  entra numa categoria se AMBOS os critérios baterem (E lógico).
"""
import os
import re
import unicodedata

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ETAPAS_PATH = os.path.join(BASE_DIR, "config", "etapas_estagio.xlsx")
RECEITA_PATH = os.path.join(BASE_DIR, "config", "classificacao_receita.xlsx")

REVENUE_CATEGORIES = ["RECEITA TOTAL", "RENOVAÇÃO", "BANDA LARGA", "APARELHO"]


def norm(s):
    if s is None:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def load_stage_map():
    df = pd.read_excel(ETAPAS_PATH)
    df["_norm"] = df["Nome do estágio"].apply(norm)
    stage_map = {}
    for _, r in df.iterrows():
        stage_map[r["_norm"]] = {
            "atendido": r["ATENDIDO?"] == "SIM",
            "convertido": r["CONVERTIDO?"] == "SIM",
            "concluido": r["CONCLUIDO?"] == "SIM",
            "em_tramite": r["EM TRAMITE?"] == "SIM",
        }
    return stage_map


def load_revenue_sets():
    xl = pd.ExcelFile(RECEITA_PATH)
    solic = xl.parse("SOLICITACAO")
    prod = xl.parse("PRODUTOS")
    solic_sets = {c: set(norm(v) for v in solic[c].dropna()) for c in REVENUE_CATEGORIES}
    prod_sets = {c: set(norm(v) for v in prod[c].dropna()) for c in REVENUE_CATEGORIES}
    return solic_sets, prod_sets


STAGE_MAP = load_stage_map()
SOLIC_SETS, PROD_SETS = load_revenue_sets()

# Etapas que a Isabela NÃO considera como "movimentação" quando um lead entra
# nelas (confirmado em 2026-09-15) — mesmo sendo uma mudança de etapa
# registrada em mail.tracking.value, não deve contar no ranking/total de
# movimentações de consultor. Qualquer etapa fora desta lista conta como
# movimentação normalmente.
NON_MOVEMENT_STAGES = {
    "AGUARDANDO INTERAÇÃO",
    "TENTATIVA DE CONTATO",
    "CLIENTE JA RENOVADO",
    "CORRECAO CONSULTOR",
    "ATUALIZACOES POR ROBO",
}
NON_MOVEMENT_STAGES_NORM = {norm(s) for s in NON_MOVEMENT_STAGES}


def classify_stage(stage_name):
    return STAGE_MAP.get(norm(stage_name), {
        "atendido": False, "convertido": False, "concluido": False, "em_tramite": False,
    })


def is_movement_stage(stage_name):
    """True se uma mudança PARA esta etapa deve contar como 'movimentação'."""
    return norm(stage_name) not in NON_MOVEMENT_STAGES_NORM


def line_matches_category(categ_name, req_name, category):
    return norm(categ_name) in PROD_SETS[category] and norm(req_name) in SOLIC_SETS[category]
