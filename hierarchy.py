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

import tv_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIERARCHY_PATH = os.path.join(BASE_DIR, "config", "hierarquia_usuarios.xlsx")

EXCLUDED_TEAMS = {"BKO", "GERENTE VIVO", "PV071-00001", "PV071-00002", "PV071-00003"}

# Equipes que continuam aparecendo no drill-down (PV -> Supervisor ->
# Consultor) com seus próprios números, mas cujo resultado NÃO deve ser
# somado ao total/plano do PV (pedido da Isabela em 2026-09-16).
# (2026-10-08) A Equipe Elton virou o PV 04 (ver tv_config.EQUIPES), então
# ninguém mais precisa ficar fora da soma do próprio PV.
EXCLUDED_FROM_PV_TOTAL = set()


def normaliza_pv(pv):
    """'PV03' / 'PV 3' / 'pv 03' -> 'PV 03' (no CRM o PV 03 vem sem espaço)."""
    m = re.match(r"^\s*PV\s*0*(\d+)\s*$", str(pv or ""), flags=re.IGNORECASE)
    return "PV {:02d}".format(int(m.group(1))) if m else str(pv or "").strip()


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
        login = row["Login"]
        equipe = tv_config.LOGIN_EQUIPE.get(login, row["Equipes de vendas"])
        cfg = tv_config.EQUIPES.get(equipe, {})
        pv = equipe.split(" - ", 1)[0].strip() if " - " in equipe else equipe
        pv = cfg.get("pv") or normaliza_pv(pv)
        result[login] = {
            "login": login,
            "nome": row["Nome"],
            "nome_exibicao": tv_config.NOME_EXIBICAO.get(login),
            "equipe": equipe,
            "pv": pv,
            "supervisor": cfg.get("label") or team_supervisor.get(equipe),
            "conta_no_pv": not is_excluded_from_pv_total(equipe),
            "ocultar_da_tv": login in tv_config.OCULTAR_DA_TV,
            "so_resultado_do_pv": login in tv_config.SO_RESULTADO_DO_PV,
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
