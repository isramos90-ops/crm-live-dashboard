"""
Painel CRM — Resumo do Mês (metodologia oficial) + Movimentações + Ranking

Atualiza os dados do CRM em segundo plano a cada REFRESH_SECONDS (padrão: 1h)
e serve um JSON agregado em /api/data. O front-end consulta esse endpoint
periodicamente — a página não precisa ser recarregada.

Todas as classificações (ATENDIDO/CONVERTIDO/CONCLUIDO/EM TRAMITE e as 4
categorias de receita) seguem a metodologia oficial enviada pela Isabela,
carregada de config/etapas_estagio.xlsx e config/classificacao_receita.xlsx
(ver classification.py).
"""
import datetime as dt
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template

import odoo_client as crm
from classification import classify_stage, line_matches_category, REVENUE_CATEGORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard")

app = Flask(__name__)

REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "3600"))  # 1h por padrão

# uid de contas técnicas/sistema a excluir dos rankings de consultor
SYSTEM_USER_IDS = {int(x) for x in os.environ.get("SYSTEM_USER_IDS", "1").split(",") if x}

STAGE_TRACKING_FIELD_ID = int(os.environ.get("STAGE_TRACKING_FIELD_ID", "6197"))

_state_lock = threading.Lock()
_state = {"data": None, "updated_at": None, "error": None}


def _month_start_str():
    now = dt.datetime.utcnow()
    return now.strftime("%Y-%m-01 00:00:00")


def _month_label():
    now = dt.datetime.utcnow()
    return now.strftime("%m/%Y")


def collect_data():
    month_start = _month_start_str()

    # ---------- Leads do mês, por etapa ----------
    # NOTA: read_group em crm.lead neste CRM retorna uma contagem menor que a
    # real (bug/limitação observada no servidor — provavelmente alguma regra
    # de agregação customizada do módulo _plus_access). Por isso buscamos os
    # registros individuais (leve: só 2 campos) e agregamos aqui em Python,
    # igual à abordagem já validada no relatório mensal.
    leads = crm.search_read(
        "crm.lead", [["create_date", ">=", month_start]],
        fields=["stage_id", "team_id"], limit=0,
    )
    total_leads = len(leads)
    qtd_atendido = qtd_convertido = qtd_concluido = qtd_tramite = 0
    qtd_proposta = qtd_aceite = 0
    for l in leads:
        stage_name = l["stage_id"][1] if l.get("stage_id") else None
        flags = classify_stage(stage_name)
        if flags["atendido"]:
            qtd_atendido += 1
        if flags["convertido"]:
            qtd_convertido += 1
        if flags["concluido"]:
            qtd_concluido += 1
        if flags["em_tramite"]:
            qtd_tramite += 1
        if stage_name and stage_name.strip().upper() == "PROPOSTA ENVIADA":
            qtd_proposta += 1
        if stage_name and stage_name.strip().upper() == "ACEITE ENVIADO":
            qtd_aceite += 1

    def pct(n):
        return round(100.0 * n / total_leads, 1) if total_leads else 0.0

    funil = {
        "total_leads": total_leads,
        "atendido": {"count": qtd_atendido, "pct": pct(qtd_atendido)},
        "convertido": {"count": qtd_convertido, "pct": pct(qtd_convertido)},
        "proposta_enviada": qtd_proposta,
        "aceite_enviado": qtd_aceite,
        "concluido": qtd_concluido,
        "em_tramite": qtd_tramite,
    }

    # ---------- Ranking por equipe (mesmo cohort do mês) ----------
    teams = {}
    for l in leads:
        team_name = l["team_id"][1] if l.get("team_id") else "(sem equipe)"
        stage_name = l["stage_id"][1] if l.get("stage_id") else None
        flags = classify_stage(stage_name)
        t = teams.setdefault(team_name, {"total": 0, "atendido": 0, "convertido": 0})
        t["total"] += 1
        if flags["atendido"]:
            t["atendido"] += 1
        if flags["convertido"]:
            t["convertido"] += 1
    team_ranking = sorted(
        [{"equipe": k, **v} for k, v in teams.items()],
        key=lambda x: -x["convertido"],
    )

    # ---------- Receita do mês (linhas de pedido) ----------
    line_rg = crm.read_group(
        "sale.order.line",
        [["create_date", ">=", month_start]],
        ["price_total:sum"],
        ["request_type_id", "product_id"],
    )
    product_ids = sorted({r["product_id"][0] for r in line_rg if r.get("product_id")})
    prod_categ = {}
    if product_ids:
        prods = crm.execute_kw("product.product", "read", [product_ids], {"fields": ["id", "categ_id"]})
        prod_categ = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else None) for p in prods}

    revenue = {cat: {"qtd": 0, "receita": 0.0} for cat in REVENUE_CATEGORIES}
    for r in line_rg:
        req_name = r["request_type_id"][1] if r.get("request_type_id") else None
        prod_id = r["product_id"][0] if r.get("product_id") else None
        categ_name = prod_categ.get(prod_id)
        for cat in REVENUE_CATEGORIES:
            if line_matches_category(categ_name, req_name, cat):
                revenue[cat]["qtd"] += r["__count"]
                revenue[cat]["receita"] += r.get("price_total") or 0.0
    for cat in revenue:
        revenue[cat]["receita"] = round(revenue[cat]["receita"], 2)

    # ---------- Movimentações de etapa no mês, por consultor ----------
    mv_rg = crm.read_group(
        "mail.tracking.value",
        [["field_id", "=", STAGE_TRACKING_FIELD_ID], ["create_date", ">=", month_start]],
        [],
        ["create_uid"],
    )
    total_movimentacoes = sum(r["__count"] for r in mv_rg)
    top_consultores = sorted(
        [
            {"consultor": r["create_uid"][1], "movimentacoes": r["__count"]}
            for r in mv_rg
            if r.get("create_uid") and r["create_uid"][0] not in SYSTEM_USER_IDS
        ],
        key=lambda x: -x["movimentacoes"],
    )[:15]

    return {
        "mes": _month_label(),
        "funil": funil,
        "revenue": revenue,
        "team_ranking": team_ranking[:20],
        "total_movimentacoes": total_movimentacoes,
        "top_consultores": top_consultores,
    }


def refresh_loop():
    while True:
        try:
            data = collect_data()
            with _state_lock:
                _state["data"] = data
                _state["updated_at"] = dt.datetime.utcnow().isoformat() + "Z"
                _state["error"] = None
            log.info("Dados atualizados com sucesso.")
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao atualizar dados do CRM")
            with _state_lock:
                _state["error"] = str(exc)
        time.sleep(REFRESH_SECONDS)


@app.route("/")
def index():
    return render_template("index.html", refresh_seconds=REFRESH_SECONDS)


@app.route("/api/data")
def api_data():
    with _state_lock:
        return jsonify(_state)


def start_background_refresh():
    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()


start_background_refresh()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
