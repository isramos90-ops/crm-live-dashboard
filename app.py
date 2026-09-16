"""
Painel CRM — Resumo do Mês (metodologia oficial) + Movimentações + Ranking
+ Filtro PV / Supervisor / Consultor + seletor de período (mês atual / 60 dias)

Atualiza os dados do CRM em segundo plano a cada REFRESH_SECONDS (padrão: 1h)
e serve um JSON agregado em /api/data. O front-end consulta esse endpoint
periodicamente — a página não precisa ser recarregada.

Todas as classificações (ATENDIDO/CONVERTIDO/CONCLUIDO/EM TRAMITE e as 4
categorias de receita) seguem a metodologia oficial enviada pela Isabela,
carregada de config/etapas_estagio.xlsx e config/classificacao_receita.xlsx
(ver classification.py).

Cada período (mês atual, últimos 60 dias) é calculado com as mesmas métricas
(funil, produção, receita, movimentações), tanto no total geral ("Todos")
quanto quebrado por PV → Supervisor → Consultor (config/hierarquia_usuarios.xlsx,
ver hierarchy.py), para alimentar o filtro no front-end.
"""
import datetime as dt
import logging
import os
import threading
import time

from flask import Flask, jsonify, render_template

import odoo_client as crm
import metas
import fotos
from classification import classify_stage, is_movement_stage, line_matches_category, REVENUE_CATEGORIES
from hierarchy import build_user_id_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard")

app = Flask(__name__)

REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "3600"))  # 1h por padrão

# uid de contas técnicas/sistema a excluir dos rankings/atribuição de consultor
SYSTEM_USER_IDS = {int(x) for x in os.environ.get("SYSTEM_USER_IDS", "1").split(",") if x}

STAGE_TRACKING_FIELD_ID = int(os.environ.get("STAGE_TRACKING_FIELD_ID", "6197"))

LAST_N_DAYS = int(os.environ.get("LAST_N_DAYS", "60"))

# Tempo mínimo de cada slide no modo TV: pelo menos 1 minuto (confirmado com
# a Isabela em 2026-09-15). TV_SLIDE_SECONDS pode aumentar esse valor, mas
# nunca reduzir abaixo de 60s.
TV_SLIDE_SECONDS = max(60, int(os.environ.get("TV_SLIDE_SECONDS", "60")))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_pedidos_mes_atual():
    """Números de pedido/cotação (sale.order 'name', ex: S41934) que a
    Isabela quer contar DENTRO da receita do mês atual mesmo que a
    'create_date' da linha seja de um mês anterior (pedido criado no mês
    passado mas que só fechou/andou agora) — ver config/pedidos_mes_atual.txt
    e README. Um código por linha."""
    path = os.path.join(BASE_DIR, "config", "pedidos_mes_atual.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return {line.strip().upper() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


PEDIDOS_MES_ATUAL = _load_pedidos_mes_atual()

_state_lock = threading.Lock()
_state = {"data": None, "updated_at": None, "error": None}


def new_metric_bucket():
    return {
        "total": 0, "atendido": 0, "convertido": 0, "proposta_enviada": 0,
        "aceite_enviado": 0, "proposta_recusada": 0, "concluido": 0, "em_tramite": 0,
        "movimentacoes": 0,
        "revenue": {cat: {"qtd": 0, "receita": 0.0} for cat in REVENUE_CATEGORIES},
    }


def add_lead_to_bucket(bucket, stage_name, flags):
    bucket["total"] += 1
    if flags["atendido"]:
        bucket["atendido"] += 1
    if flags["convertido"]:
        bucket["convertido"] += 1
    if flags["concluido"]:
        bucket["concluido"] += 1
    if flags["em_tramite"]:
        bucket["em_tramite"] += 1
    if stage_name and stage_name.strip().upper() == "PROPOSTA ENVIADA":
        bucket["proposta_enviada"] += 1
    if stage_name and stage_name.strip().upper() == "ACEITE ENVIADO":
        bucket["aceite_enviado"] += 1
    if stage_name and stage_name.strip().upper() == "PROPOSTA RECUSADA":
        bucket["proposta_recusada"] += 1


def hierarchy_buckets(pv_tree, uid_map, user_id):
    """Retorna [bucket_pv, bucket_supervisor, bucket_consultor] para o
    usuário do CRM informado, criando os nós que faltarem — ou None se o
    usuário não está mapeado na hierarquia (fora do escopo do drill-down)."""
    info = uid_map.get(user_id) if user_id else None
    if not info:
        return None
    pv_node = pv_tree.setdefault(info["pv"], {"metrics": new_metric_bucket(), "supervisors": {}})
    sup_name = info["supervisor"] or "(sem supervisor)"
    sup_node = pv_node["supervisors"].setdefault(
        sup_name, {"metrics": new_metric_bucket(), "consultores": {}, "equipe": info["equipe"]},
    )
    cons_bucket = sup_node["consultores"].setdefault(info["nome"], new_metric_bucket())
    return [pv_node["metrics"], sup_node["metrics"], cons_bucket]


def compute_period_metrics(start_dt, label, uid_map, force_include_orders=None):
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    force_include_orders = force_include_orders or set()

    root = new_metric_bucket()
    pv_tree = {}
    leads_fora_do_escopo = 0

    # ---------- Leads do período, por etapa ----------
    # NOTA: read_group em crm.lead neste CRM retorna uma contagem menor que a
    # real (bug/limitação observada no servidor). Por isso buscamos os
    # registros individuais (leve: só 3 campos) e agregamos aqui em Python.
    leads = crm.search_read(
        "crm.lead", [["create_date", ">=", start_str]],
        fields=["stage_id", "team_id", "user_id"], limit=0,
    )

    teams = {}
    for l in leads:
        stage_name = l["stage_id"][1] if l.get("stage_id") else None
        flags = classify_stage(stage_name)

        add_lead_to_bucket(root, stage_name, flags)

        team_name = l["team_id"][1] if l.get("team_id") else "(sem equipe)"
        t = teams.setdefault(team_name, {"total": 0, "atendido": 0, "convertido": 0})
        t["total"] += 1
        if flags["atendido"]:
            t["atendido"] += 1
        if flags["convertido"]:
            t["convertido"] += 1

        user = l.get("user_id")
        buckets = hierarchy_buckets(pv_tree, uid_map, user[0] if user else None)
        if not buckets:
            leads_fora_do_escopo += 1
            continue
        for b in buckets:
            add_lead_to_bucket(b, stage_name, flags)

    team_ranking = sorted(
        [{"equipe": k, **v} for k, v in teams.items()],
        key=lambda x: -x["convertido"],
    )[:20]

    # ---------- Receita do período (linhas de pedido) ----------
    # Domínio: linhas criadas dentro do período OU pertencentes a um pedido
    # da lista "force_include_orders" (pedidos de um mês anterior que a
    # Isabela quer contar neste período mesmo assim — ver
    # config/pedidos_mes_atual.txt e README). Um único search evita duplicar
    # linhas que já caem nas duas condições.
    lines_domain = [["create_date", ">=", start_str]]
    if force_include_orders:
        lines_domain = ["|", ["create_date", ">=", start_str], ["order_id.name", "in", sorted(force_include_orders)]]
    lines = crm.search_read(
        "sale.order.line", lines_domain,
        fields=["product_id", "request_type_id", "price_total", "salesman_id", "order_id"], limit=0,
    )
    product_ids = sorted({r["product_id"][0] for r in lines if r.get("product_id")})
    prod_categ = {}
    if product_ids:
        prods = crm.execute_kw("product.product", "read", [product_ids], {"fields": ["id", "categ_id"]})
        prod_categ = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else None) for p in prods}

    pedidos_mes_atual_count = 0
    for r in lines:
        order = r.get("order_id")
        order_name = order[1].strip().upper() if order else None
        if order_name and order_name in force_include_orders:
            pedidos_mes_atual_count += 1
        req_name = r["request_type_id"][1] if r.get("request_type_id") else None
        prod_id = r["product_id"][0] if r.get("product_id") else None
        categ_name = prod_categ.get(prod_id)
        price = r.get("price_total") or 0.0
        salesman = r.get("salesman_id")
        buckets = hierarchy_buckets(pv_tree, uid_map, salesman[0] if salesman else None)
        for cat in REVENUE_CATEGORIES:
            if line_matches_category(categ_name, req_name, cat):
                root["revenue"][cat]["qtd"] += 1
                root["revenue"][cat]["receita"] += price
                if buckets:
                    for b in buckets:
                        b["revenue"][cat]["qtd"] += 1
                        b["revenue"][cat]["receita"] += price
    root["revenue"] = {c: {"qtd": v["qtd"], "receita": round(v["receita"], 2)} for c, v in root["revenue"].items()}

    def round_bucket_revenue(bucket):
        bucket["revenue"] = {c: {"qtd": v["qtd"], "receita": round(v["receita"], 2)} for c, v in bucket["revenue"].items()}

    # ---------- Movimentações de etapa no período, por consultor ----------
    # Busca os registros individuais (em vez de read_group) para poder
    # filtrar por etapa de destino (new_value_char): algumas etapas não
    # contam como "movimentação" (ver classification.NON_MOVEMENT_STAGES).
    mv_records = crm.search_read(
        "mail.tracking.value",
        [["field_id", "=", STAGE_TRACKING_FIELD_ID], ["create_date", ">=", start_str]],
        fields=["create_uid", "new_value_char"], limit=0,
    )
    mv_counts = {}
    for r in mv_records:
        if not is_movement_stage(r.get("new_value_char")):
            continue
        root["movimentacoes"] += 1
        cu = r.get("create_uid")
        if not cu:
            continue
        if cu[0] not in SYSTEM_USER_IDS:
            entry = mv_counts.setdefault(cu[0], {"consultor": cu[1], "movimentacoes": 0})
            entry["movimentacoes"] += 1
        buckets = hierarchy_buckets(pv_tree, uid_map, cu[0])
        if buckets:
            for b in buckets:
                b["movimentacoes"] += 1
    top_consultores = sorted(mv_counts.values(), key=lambda x: -x["movimentacoes"])[:15]

    # ---------- Monta a árvore final PV -> Supervisor -> Consultor ----------
    # Cada nível ganha também "meta": {RECEITA_TOTAL, QUANTIDADE_BL,
    # RECEITA_RENOVACAO, RECEITA_APARELHOS} — metas de config/metas.xlsx
    # (equipe = meta do supervisor daquela equipe; consultor = meta individual;
    # PV = soma das metas das equipes/supervisores daquele PV).
    hierarchy = []
    for pv, pv_node in sorted(pv_tree.items()):
        round_bucket_revenue(pv_node["metrics"])
        supervisors = []
        pv_metas = []
        for sup, sup_node in sorted(pv_node["supervisors"].items(), key=lambda x: -x[1]["metrics"]["convertido"]):
            round_bucket_revenue(sup_node["metrics"])
            sup_meta = metas.meta_for_equipe(sup_node.get("equipe"))
            pv_metas.append(sup_meta)
            consultores = []
            for nome, metrics_bucket in sorted(sup_node["consultores"].items(), key=lambda x: -x[1]["convertido"]):
                round_bucket_revenue(metrics_bucket)
                consultores.append({"nome": nome, "meta": metas.meta_for_usuario(nome), **metrics_bucket})
            supervisors.append({
                "supervisor": sup, "meta": sup_meta, **sup_node["metrics"], "consultores": consultores,
            })
        hierarchy.append({
            "pv": pv, "meta": metas.sum_metas(*pv_metas), **pv_node["metrics"], "supervisors": supervisors,
        })

    return {
        "label": label,
        "root": root,
        "root_meta": metas.sum_metas(*[pv["meta"] for pv in hierarchy]),
        "team_ranking": team_ranking,
        "top_consultores": top_consultores,
        "hierarchy": hierarchy,
        "leads_fora_do_escopo": leads_fora_do_escopo,
        "pedidos_mes_atual_count": pedidos_mes_atual_count,
    }


def collect_data():
    now = dt.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_n_start = now - dt.timedelta(days=LAST_N_DAYS)

    uid_map = build_user_id_map(crm.search_read)

    # PEDIDOS_MES_ATUAL só se aplica ao período "mês atual" — são pedidos de
    # um mês anterior que a Isabela quer contar como receita deste mês
    # mesmo assim (ver config/pedidos_mes_atual.txt).
    month = compute_period_metrics(month_start, now.strftime("%m/%Y"), uid_map, force_include_orders=PEDIDOS_MES_ATUAL)
    last_n_label = "Últimos {}d ({} a {})".format(
        LAST_N_DAYS, last_n_start.strftime("%d/%m"), now.strftime("%d/%m"),
    )
    last_n = compute_period_metrics(last_n_start, last_n_label, uid_map)

    return {
        "periods": {
            "month": month,
            "last_n": last_n,
        },
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


@app.route("/tv")
def tv():
    return render_template(
        "tv.html", refresh_seconds=REFRESH_SECONDS,
        slide_seconds=TV_SLIDE_SECONDS,
        fotos_map=fotos.FOTOS_MAP,
    )


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
