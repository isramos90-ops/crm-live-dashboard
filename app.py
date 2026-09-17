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

from flask import Flask, jsonify, render_template, request

import odoo_client as crm
import metas
import fotos
from classification import classify_stage, is_movement_stage, line_matches_category, REVENUE_CATEGORIES
import dias_uteis
import hierarchy as hierarchy_mod
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
        # Receita Total realizada, quebrada por etapa do lead de origem
        # (pedido da Isabela em 2026-09-17) — mantém "revenue" como já era
        # (usado pra Plano x Realizado e pro grid de produtos), só adiciona
        # essa quebra específica de RECEITA TOTAL pra mostrar quanto do
        # realizado já está CONCLUIDO e quanto ainda está EM TRAMITE.
        "receita_total_status": {"concluido": 0.0, "em_tramite": 0.0},
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
    usuário não está mapeado na hierarquia (fora do escopo do drill-down).

    Times com "conta_no_pv": False (ver hierarchy.EXCLUDED_FROM_PV_TOTAL —
    hoje só a Equipe Elton, pedido da Isabela em 2026-09-16) continuam
    aparecendo normalmente como equipe/consultor, mas o bucket do PV fica de
    fora da lista, então o resultado deles nunca é somado ao total do PV."""
    info = uid_map.get(user_id) if user_id else None
    if not info:
        return None
    pv_node = pv_tree.setdefault(info["pv"], {"metrics": new_metric_bucket(), "supervisors": {}})
    sup_name = info["supervisor"] or "(sem supervisor)"
    sup_node = pv_node["supervisors"].setdefault(
        sup_name, {"metrics": new_metric_bucket(), "consultores": {}, "equipe": info["equipe"]},
    )
    cons_bucket = sup_node["consultores"].setdefault(info["nome"], new_metric_bucket())
    if not info.get("conta_no_pv", True):
        return [sup_node["metrics"], cons_bucket]
    return [pv_node["metrics"], sup_node["metrics"], cons_bucket]


def compute_period_metrics(start_dt, label, uid_map, force_include_orders=None, dias_uteis_info=None):
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

    # ---------- Só conta receita de pedido cujo lead/oportunidade de origem
    # esteja em CONCLUIDO ou EM TRAMITE (confirmado com a Isabela em
    # 2026-09-16) ----------
    # sale.order.line -> sale.order (order_id) -> crm.lead (opportunity_id) -> stage_id.
    # Pedido sem lead vinculado, ou cujo lead esteja em outra etapa, não conta
    # como receita.
    order_ids = sorted({r["order_id"][0] for r in lines if r.get("order_id")})
    lead_stage_by_order = {}
    if order_ids:
        try:
            orders = crm.execute_kw("sale.order", "read", [order_ids], {"fields": ["id", "opportunity_id"]})
            lead_ids = sorted({o["opportunity_id"][0] for o in orders if o.get("opportunity_id")})
            lead_stage = {}
            if lead_ids:
                lead_recs = crm.execute_kw("crm.lead", "read", [lead_ids], {"fields": ["id", "stage_id"]})
                lead_stage = {l["id"]: (l["stage_id"][1] if l.get("stage_id") else None) for l in lead_recs}
            for o in orders:
                opp = o.get("opportunity_id")
                lead_stage_by_order[o["id"]] = lead_stage.get(opp[0]) if opp else None
        except Exception:
            log.exception(
                "Não foi possível ligar pedidos (sale.order) ao lead de origem via "
                "'opportunity_id' — receita ficará vazia neste ciclo até isso ser corrigido."
            )

    pedidos_mes_atual_count = 0
    for r in lines:
        order = r.get("order_id")
        order_id_num = order[0] if order else None
        stage_name_lead = lead_stage_by_order.get(order_id_num)
        flags_lead = classify_stage(stage_name_lead)
        if not (flags_lead["concluido"] or flags_lead["em_tramite"]):
            continue
        order_name = order[1].strip().upper() if order else None
        if order_name and order_name in force_include_orders:
            pedidos_mes_atual_count += 1
        req_name = r["request_type_id"][1] if r.get("request_type_id") else None
        prod_id = r["product_id"][0] if r.get("product_id") else None
        categ_name = prod_categ.get(prod_id)
        prod_name = r["product_id"][1] if r.get("product_id") else None
        price = r.get("price_total") or 0.0
        salesman = r.get("salesman_id")
        buckets = hierarchy_buckets(pv_tree, uid_map, salesman[0] if salesman else None)
        status_key = "concluido" if flags_lead["concluido"] else "em_tramite"
        for cat in REVENUE_CATEGORIES:
            if line_matches_category(categ_name, req_name, cat, prod_name=prod_name):
                root["revenue"][cat]["qtd"] += 1
                root["revenue"][cat]["receita"] += price
                if cat == "RECEITA TOTAL":
                    root["receita_total_status"][status_key] += price
                if buckets:
                    for b in buckets:
                        b["revenue"][cat]["qtd"] += 1
                        b["revenue"][cat]["receita"] += price
                        if cat == "RECEITA TOTAL":
                            b["receita_total_status"][status_key] += price
    root["revenue"] = {c: {"qtd": v["qtd"], "receita": round(v["receita"], 2)} for c, v in root["revenue"].items()}
    root["receita_total_status"] = {k: round(v, 2) for k, v in root["receita_total_status"].items()}

    def round_bucket_revenue(bucket):
        bucket["revenue"] = {c: {"qtd": v["qtd"], "receita": round(v["receita"], 2)} for c, v in bucket["revenue"].items()}
        bucket["receita_total_status"] = {k: round(v, 2) for k, v in bucket["receita_total_status"].items()}

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
    #
    # PDU (Produção por Dia Útil, pedido da Isabela em 2026-09-17): só faz
    # sentido pro período "mês atual" (dias_uteis_info vem preenchido só
    # nesse caso — ver collect_data) — pra "últimos N dias" não se aplica,
    # por isso "pdu" fica None nesse período.
    def pdu_com_realizado(meta_dict, metrics_bucket):
        if not dias_uteis_info:
            return None
        realizado = metrics_bucket["revenue"]["RECEITA TOTAL"]["receita"]
        return dias_uteis.calcula_pdu(meta_dict.get("RECEITA_TOTAL"), realizado, dias_uteis_info)

    hierarchy = []
    for pv, pv_node in sorted(pv_tree.items()):
        round_bucket_revenue(pv_node["metrics"])
        supervisors = []
        pv_metas = []
        for sup, sup_node in sorted(pv_node["supervisors"].items(), key=lambda x: -x[1]["metrics"]["convertido"]):
            round_bucket_revenue(sup_node["metrics"])
            sup_meta = metas.meta_for_equipe(sup_node.get("equipe"))
            # A Equipe Elton continua com seu próprio "meta" (plano), mas não
            # entra na soma do plano do PV — mesma exclusão aplicada ao
            # realizado em hierarchy_buckets() (pedido da Isabela em
            # 2026-09-16).
            if not hierarchy_mod.is_excluded_from_pv_total(sup_node.get("equipe")):
                pv_metas.append(sup_meta)
            consultores = []
            for nome, metrics_bucket in sorted(sup_node["consultores"].items(), key=lambda x: -x[1]["convertido"]):
                round_bucket_revenue(metrics_bucket)
                cons_meta = metas.meta_for_usuario(nome)
                consultores.append({
                    "nome": nome, "meta": cons_meta, "pdu": pdu_com_realizado(cons_meta, metrics_bucket),
                    **metrics_bucket,
                })
            supervisors.append({
                "supervisor": sup, "meta": sup_meta, "pdu": pdu_com_realizado(sup_meta, sup_node["metrics"]),
                **sup_node["metrics"], "consultores": consultores,
            })
        pv_meta = metas.sum_metas(*pv_metas)
        hierarchy.append({
            "pv": pv, "meta": pv_meta, "pdu": pdu_com_realizado(pv_meta, pv_node["metrics"]),
            **pv_node["metrics"], "supervisors": supervisors,
        })

    root_meta = metas.sum_metas(*[pv["meta"] for pv in hierarchy])
    return {
        "label": label,
        "root": root,
        "root_meta": root_meta,
        "root_pdu": pdu_com_realizado(root_meta, root),
        "dias_uteis": dias_uteis_info,
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

    # "Hoje" no horário de Brasília (UTC-3) pro cálculo de PDU — usar a data
    # em UTC direto erraria o dia perto da meia-noite (ex: 23h em Brasília
    # já é dia seguinte em UTC).
    hoje_br = (now - dt.timedelta(hours=3)).date()
    dias_uteis_info = dias_uteis.info_dias_uteis(hoje_br)

    # PEDIDOS_MES_ATUAL só se aplica ao período "mês atual" — são pedidos de
    # um mês anterior que a Isabela quer contar como receita deste mês
    # mesmo assim (ver config/pedidos_mes_atual.txt).
    month = compute_period_metrics(
        month_start, now.strftime("%m/%Y"), uid_map,
        force_include_orders=PEDIDOS_MES_ATUAL, dias_uteis_info=dias_uteis_info,
    )
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


@app.route("/explorar")
def explorar():
    """Versão do modo TV com seleção manual em cascata (PV → Supervisor →
    Consultor) em vez de rotação automática — mesma lógica de metas/receita
    e mesmas fotos, mas cada nível pode ser visto individualmente ou em
    'visão geral' (agregado). Os dados continuam se atualizando sozinhos
    (mesma origem /api/data), só a seleção fica nas mãos de quem está
    olhando (pedido da Isabela em 2026-09-16)."""
    return render_template(
        "explorar.html", refresh_seconds=REFRESH_SECONDS,
        fotos_map=fotos.FOTOS_MAP,
    )


@app.route("/api/data")
def api_data():
    with _state_lock:
        return jsonify(_state)


@app.route("/api/export_linhas_mes")
def export_linhas_mes():
    """Exporta TODAS as linhas de pedido do mês atual (mesmo domínio usado
    no cálculo de receita: create_date do mês OU pedido em
    config/pedidos_mes_atual.txt), uma linha por produto vendido, com
    cliente, número do pedido, PV/Supervisor/Consultor, categoria de
    produto, tipo de solicitação, valor, etapa do lead e se conta como
    receita — pra auditoria detalhada (a Isabela pediu em 2026-09-16).
    """
    now = dt.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_str = month_start.strftime("%Y-%m-%d %H:%M:%S")

    uid_map = build_user_id_map(crm.search_read)

    lines_domain = [["create_date", ">=", start_str]]
    if PEDIDOS_MES_ATUAL:
        lines_domain = ["|", ["create_date", ">=", start_str], ["order_id.name", "in", sorted(PEDIDOS_MES_ATUAL)]]
    lines = crm.search_read(
        "sale.order.line", lines_domain,
        fields=["product_id", "request_type_id", "price_total", "salesman_id", "order_id",
                "order_partner_id", "create_date"],
        limit=0,
    )

    product_ids = sorted({r["product_id"][0] for r in lines if r.get("product_id")})
    prod_categ = {}
    if product_ids:
        prods = crm.execute_kw("product.product", "read", [product_ids], {"fields": ["id", "categ_id"]})
        prod_categ = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else None) for p in prods}

    order_ids = sorted({r["order_id"][0] for r in lines if r.get("order_id")})
    lead_stage_by_order = {}
    lookup_erro = None
    if order_ids:
        try:
            orders = crm.execute_kw("sale.order", "read", [order_ids], {"fields": ["id", "opportunity_id"]})
            lead_ids = sorted({o["opportunity_id"][0] for o in orders if o.get("opportunity_id")})
            lead_stage = {}
            if lead_ids:
                lead_recs = crm.execute_kw("crm.lead", "read", [lead_ids], {"fields": ["id", "stage_id"]})
                lead_stage = {l["id"]: (l["stage_id"][1] if l.get("stage_id") else None) for l in lead_recs}
            for o in orders:
                opp = o.get("opportunity_id")
                lead_stage_by_order[o["id"]] = lead_stage.get(opp[0]) if opp else None
        except Exception as exc:  # noqa: BLE001
            lookup_erro = str(exc)

    out = []
    for r in lines:
        order = r.get("order_id")
        order_name = order[1].strip().upper() if order else None
        order_id_num = order[0] if order else None
        stage_name_lead = lead_stage_by_order.get(order_id_num)
        flags_lead = classify_stage(stage_name_lead)
        req_name = r["request_type_id"][1] if r.get("request_type_id") else None
        prod_id = r["product_id"][0] if r.get("product_id") else None
        categ_name = prod_categ.get(prod_id)
        prod_name = r["product_id"][1] if r.get("product_id") else None
        categorias_ok = [cat for cat in REVENUE_CATEGORIES if line_matches_category(categ_name, req_name, cat, prod_name=prod_name)]
        salesman = r.get("salesman_id")
        info = uid_map.get(salesman[0]) if salesman else None
        out.append({
            "pv": info["pv"] if info else None,
            "supervisor": info["supervisor"] if info else None,
            "consultor": info["nome"] if info else (salesman[1] if salesman else None),
            "cliente": r["order_partner_id"][1] if r.get("order_partner_id") else None,
            "pedido": order_name,
            "create_date": r.get("create_date"),
            "produto": r["product_id"][1] if r.get("product_id") else None,
            "categoria_produto": categ_name,
            "tipo_solicitacao": req_name,
            "price_total": r.get("price_total"),
            "lead_stage": stage_name_lead,
            "lead_concluido_ou_em_tramite": bool(flags_lead["concluido"] or flags_lead["em_tramite"]),
            "categorias_de_receita_que_bateram": categorias_ok,
            "conta_como_receita": bool(categorias_ok) and bool(flags_lead["concluido"] or flags_lead["em_tramite"]),
            "pedido_forcado_mes_atual": bool(order_name and order_name in PEDIDOS_MES_ATUAL),
        })

    return jsonify({
        "periodo": now.strftime("%m/%Y"),
        "gerado_em": now.isoformat() + "Z",
        "total_linhas": len(out),
        "erro_lookup_lead": lookup_erro,
        "linhas": out,
    })


@app.route("/api/debug_pedidos")
def debug_pedidos():
    """Diagnóstico manual: mostra, pra uma lista de números de pedido
    (Número da Cotação, ex: S42104), exatamente como cada linha foi
    classificada — categoria de produto, tipo de solicitação, valor, etapa
    do lead vinculado e em quais categorias de receita a linha entrou (ou
    por que não entrou em nenhuma). Uso: /api/debug_pedidos?nomes=S42104,S41771
    """
    nomes_param = request.args.get("nomes", "")
    nomes = [n.strip().upper() for n in nomes_param.split(",") if n.strip()]
    if not nomes:
        return jsonify({"erro": "passe ?nomes=S12345,S67890"}), 400

    lines = crm.search_read(
        "sale.order.line", [["order_id.name", "in", nomes]],
        fields=["product_id", "request_type_id", "price_total", "price_subtotal", "price_unit",
                "product_uom_qty", "salesman_id", "order_id", "create_date"],
        limit=0,
    )
    product_ids = sorted({r["product_id"][0] for r in lines if r.get("product_id")})
    prod_categ = {}
    if product_ids:
        prods = crm.execute_kw("product.product", "read", [product_ids], {"fields": ["id", "categ_id"]})
        prod_categ = {p["id"]: (p["categ_id"][1] if p.get("categ_id") else None) for p in prods}

    order_ids = sorted({r["order_id"][0] for r in lines if r.get("order_id")})
    lead_stage_by_order = {}
    order_totais = {}
    lookup_erro = None
    if order_ids:
        try:
            orders = crm.execute_kw(
                "sale.order", "read", [order_ids],
                {"fields": ["id", "name", "opportunity_id", "amount_total", "amount_untaxed"]},
            )
            lead_ids = sorted({o["opportunity_id"][0] for o in orders if o.get("opportunity_id")})
            lead_stage = {}
            if lead_ids:
                lead_recs = crm.execute_kw("crm.lead", "read", [lead_ids], {"fields": ["id", "stage_id"]})
                lead_stage = {l["id"]: (l["stage_id"][1] if l.get("stage_id") else None) for l in lead_recs}
            for o in orders:
                opp = o.get("opportunity_id")
                lead_stage_by_order[o["id"]] = lead_stage.get(opp[0]) if opp else None
                order_totais[o["id"]] = {
                    "amount_total": o.get("amount_total"),
                    "amount_untaxed": o.get("amount_untaxed"),
                }
        except Exception as exc:  # noqa: BLE001
            lookup_erro = str(exc)

    out = []
    encontrados = {n: False for n in nomes}
    for r in lines:
        order = r.get("order_id")
        order_name = order[1].strip().upper() if order else None
        if order_name in encontrados:
            encontrados[order_name] = True
        order_id_num = order[0] if order else None
        stage_name_lead = lead_stage_by_order.get(order_id_num)
        flags_lead = classify_stage(stage_name_lead)
        req_name = r["request_type_id"][1] if r.get("request_type_id") else None
        prod_id = r["product_id"][0] if r.get("product_id") else None
        categ_name = prod_categ.get(prod_id)
        prod_name = r["product_id"][1] if r.get("product_id") else None
        categorias_ok = [cat for cat in REVENUE_CATEGORIES if line_matches_category(categ_name, req_name, cat, prod_name=prod_name)]
        out.append({
            "pedido": order_name,
            "create_date": r.get("create_date"),
            "produto": r["product_id"][1] if r.get("product_id") else None,
            "categoria_produto": categ_name,
            "tipo_solicitacao": req_name,
            "price_total": r.get("price_total"),
            "price_subtotal": r.get("price_subtotal"),
            "price_unit": r.get("price_unit"),
            "product_uom_qty": r.get("product_uom_qty"),
            "vendedor": r["salesman_id"][1] if r.get("salesman_id") else None,
            "lead_stage": stage_name_lead,
            "lead_concluido_ou_em_tramite": bool(flags_lead["concluido"] or flags_lead["em_tramite"]),
            "categorias_de_receita_que_bateram": categorias_ok,
            "conta_como_receita": bool(categorias_ok) and bool(flags_lead["concluido"] or flags_lead["em_tramite"]),
        })

    totais_por_pedido = {}
    for r in lines:
        order = r.get("order_id")
        if not order:
            continue
        name = order[1].strip().upper()
        totais_por_pedido.setdefault(name, {"soma_linhas_price_total": 0.0, **order_totais.get(order[0], {})})
        totais_por_pedido[name]["soma_linhas_price_total"] += r.get("price_total") or 0.0
    for v in totais_por_pedido.values():
        v["soma_linhas_price_total"] = round(v["soma_linhas_price_total"], 2)

    nao_encontrados = [n for n, achou in encontrados.items() if not achou]
    return jsonify({
        "linhas": out,
        "totais_por_pedido": totais_por_pedido,
        "pedidos_nao_encontrados_como_sale_order_line": nao_encontrados,
        "erro_lookup_lead": lookup_erro,
    })


def start_background_refresh():
    t = threading.Thread(target=refresh_loop, daemon=True)
    t.start()


start_background_refresh()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
