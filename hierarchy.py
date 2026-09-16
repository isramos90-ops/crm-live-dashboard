"""
Carrega a hierarquia PV / Supervisor / Consultor a partir de
config/hierarquia_usuarios.xlsx (export res.users: Login, Nome, Equipes de vendas).

Regras confirmadas com a Isabela (2026-09-15):
- PV = parte antes do "-" no nome da equipe (ex: "PV 02 - Equipe Alexandre" -> "PV 02").
- Equipes que não seguem o padrão "PV - Equipe <Nome>" (BKO, GERENTE VIVO,
  PV071-00001/2/3) são excluídas do drill-down PV/Supervisor/Consultor.

Rótulo do nível "Supervisor" (2026-09-16): mostra o RESULTADO DA EQUIPE, com
o nome da equipe (ex: "EQUIPE CARTEIRA", "EQUIPE RICHARD", "EQUIPE
ALEXANDRE") — não o nome pessoal de quem supervisiona. Antes tentava achar
o supervisor pelo membro do time cujo primeiro nome batesse com o sufixo da
equipe, mas isso deixava times como "Equipe Carteira" (a própria Isabela é
supervisora, mas não aparece como membro na planilha) sem rótulo.

Exclusão do resultado do PV (2026-09-16, pedido da Isabela): a "Equipe
Elton" (equipe "PV 02 - Equipe Elton") continua aparecendo normalmente como
equipe/consultor no drill-down, com seus próprios números — mas o resultado
dela NÃO entra na soma/plano do PV 02 (ver EXCLUDED_FROM_PV_TOTAL e
`conta_no_pv` abaixo, usados em app.py).
"""
import os
import re

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIERARCHY_PATH = os.path.join(BASE_DIR, "config", "hierarquia_usuarios.xlsx")

EXCLUDED_TEAMS = {"BKO", "GERENTE VIVO", "PV071-00001", "PV071-00002", "PV071-00003"}

# Equipes que continuam aparecendo no drill-down (PV -> Supervisor ->
# Consultor) com seus próprios números, mas cujo resultado NÃO deve ser
# somado ao total/plano do PV (pedido da Isabela em 2026-09-16).
EXCLUDED_FROM_PV_TOTAL = {"PV 02 - Equipe Elton"}


def is_excluded_from_pv_total(equipe):
    return equipe in EXCLUDED_FROM_PV_TOTAL


def load_hierarchy_by_login():
    """Retorna {login: {"nome":..., "equipe":..., "pv":..., "supervisor": nome ou None}}"""
    df = pd.read_excel(HIERARCHY_PATH)
    df = df[df["Equipes de vendas"].notna()]
    df = df[~df["Equipes de vendas"].isin(EXCLUDED_TEAMS)]

    # Rótulo do 2º nível do drill-down (PV -> "Supervisor" -> Consultor): a
    # Isabela pediu em 2026-09-16 pra mostrar o RESULTADO DA EQUIPE nesse
    # nível, com o nome da equipe (ex: "EQUIPE CARTEIRA", "EQUIPE RICHARD",
    # "EQUIPE ALEXANDRE") em vez do nome pessoal do supervisor — inclusive
    # pra equipes como "Equipe Carteira", onde ninguém do time bate com o
    # sufixo do nome da equipe (ela mesma é a supervisora, mas não aparece
    # como membro da planilha) e antes ficava "(sem supervisor)".
    team_supervisor = {}
    for equipe in df["Equipes de vendas"].unique():
        if " - " not in equipe:
            continue
        suffix = equipe.split(" - ", 1)[1]
        suffix = re.sub(r"^Equipe\s+", "", suffix, flags=re.IGNORECASE).strip().upper()
        team_supervisor[equipe] = "EQUIPE " + suffix

    result = {}
    for _, row in df.iterrows():
        equipe = row["Equipes de vendas"]
        pv = equipe.split(" - ", 1)[0].strip() if " - " in equipe else equipe
        result[row["Login"]] = {
            "nome": row["Nome"],
            "equipe": equipe,
            "pv": pv,
            "supervisor": team_supervisor.get(equipe),
            "conta_no_pv": not is_excluded_from_pv_total(equipe),
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
