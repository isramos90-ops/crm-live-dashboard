"""
Carrega a hierarquia PV / Supervisor / Consultor a partir de
config/hierarquia_usuarios.xlsx (export res.users: Login, Nome, Equipes de vendas).

Regras confirmadas com a Isabela (2026-09-15):
- PV = parte antes do "-" no nome da equipe (ex: "PV 02 - Equipe Alexandre" -> "PV 02").
- Supervisor = o membro do time cujo primeiro nome bate com o sufixo da equipe
  (ex: "Alexandre Ornellas" é membro de "PV 02 - Equipe Alexandre" -> supervisor).
  Times cujo sufixo não bate com nenhum nome de membro (ex: "Equipe Carteira")
  ficam sem supervisor identificado.
- Equipes que não seguem o padrão "PV - Equipe <Nome>" (BKO, GERENTE VIVO,
  PV071-00001/2/3) são excluídas do drill-down PV/Supervisor/Consultor.
"""
import os
import re

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIERARCHY_PATH = os.path.join(BASE_DIR, "config", "hierarquia_usuarios.xlsx")

EXCLUDED_TEAMS = {"BKO", "GERENTE VIVO", "PV071-00001", "PV071-00002", "PV071-00003"}


def _first_name(full_name):
    return full_name.strip().split()[0].upper() if full_name else ""


def load_hierarchy_by_login():
    """Retorna {login: {"nome":..., "equipe":..., "pv":..., "supervisor": nome ou None}}"""
    df = pd.read_excel(HIERARCHY_PATH)
    df = df[df["Equipes de vendas"].notna()]
    df = df[~df["Equipes de vendas"].isin(EXCLUDED_TEAMS)]

    # descobre o supervisor de cada equipe (membro cujo primeiro nome bate com o sufixo)
    team_supervisor = {}
    for equipe, group in df.groupby("Equipes de vendas"):
        if " - " not in equipe:
            continue
        suffix = equipe.split(" - ", 1)[1]
        suffix = re.sub(r"^Equipe\s+", "", suffix, flags=re.IGNORECASE).strip().upper()
        supervisor = None
        for _, row in group.iterrows():
            if _first_name(row["Nome"]) == suffix:
                supervisor = row["Nome"]
                break
        team_supervisor[equipe] = supervisor

    result = {}
    for _, row in df.iterrows():
        equipe = row["Equipes de vendas"]
        pv = equipe.split(" - ", 1)[0].strip() if " - " in equipe else equipe
        result[row["Login"]] = {
            "nome": row["Nome"],
            "equipe": equipe,
            "pv": pv,
            "supervisor": team_supervisor.get(equipe),
        }
    return result


def build_user_id_map(crm_search_read):
    """Casa cada login com o id numérico do usuário no CRM (res.users)."""
    by_login = load_hierarchy_by_login()
    logins = list(by_login.keys())
    users = crm_search_read("res.users", [["login", "in", logins]], fields=["id", "login"], limit=0)
    result = {}
    for u in users:
        info = by_login.get(u["login"])
        if info:
            result[u["id"]] = info
    return result
