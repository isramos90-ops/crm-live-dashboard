"""
Gera os arquivos que a versão Google Apps Script do painel lê do GitHub:

- apps-script/config.json   -> etapas, classificação de receita, hierarquia
                                (já com foto de cada pessoa), metas padrão,
                                feriados, dia de corte e regras de exibição
                                da TV (tudo que hoje vem de config/*.xlsx,
                                config/feriados.txt, tv_config.py e fotos.py)
- apps-script/web/*.html    -> painel, tv e explorar, convertidos dos
                                templates Flask (templates/*.html)

Rodar sempre que mudar algo em config/ ou templates/ (depois dar push):

    python3 apps-script/build.py

O Codigo.gs (colado no Apps Script) baixa esses arquivos do GitHub e guarda
em cache — então mudanças aqui chegam no painel sem precisar colar nada de
novo no Apps Script.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pandas as pd  # noqa: E402

import classification  # noqa: E402
import dias_uteis  # noqa: E402
import fotos  # noqa: E402
import hierarchy  # noqa: E402
import metas  # noqa: E402
import tv_config  # noqa: E402

OUT_DIR = os.path.join(ROOT, "apps-script")
WEB_DIR = os.path.join(OUT_DIR, "web")
RAW_BASE = "https://raw.githubusercontent.com/isramos90-ops/crm-live-dashboard/main/"
STATIC_BASE = RAW_BASE + "static/"


def build_config():
    by_login = hierarchy.load_hierarchy_by_login()
    for login, info in by_login.items():
        info["foto"] = fotos.foto_pessoa(login, info["nome"], info.get("nome_exibicao"))

    def metas_rows(sheet, key_col):
        df = pd.read_excel(metas.METAS_PATH, sheet_name=sheet)
        rows = []
        for _, r in df.iterrows():
            if pd.isna(r[key_col]) or not str(r[key_col]).strip():
                continue
            rows.append([str(r[key_col]).strip()] + [
                float(r[f]) if pd.notna(r[f]) else 0.0 for f in metas.METAS_FIELDS
            ])
        return rows

    return {
        "revenue_categories": classification.REVENUE_CATEGORIES,
        "stage_map": classification.STAGE_MAP,
        "solic_sets": {k: sorted(v) for k, v in classification.SOLIC_SETS.items()},
        "prod_sets": {k: sorted(v) for k, v in classification.PROD_SETS.items()},
        "non_movement_stages": sorted(classification.NON_MOVEMENT_STAGES_NORM),
        "miscategorized_as_banda_larga": sorted(classification.MISCATEGORIZED_AS_BANDA_LARGA_NORM),
        "hierarchy_by_login": by_login,
        "excluded_from_pv_total": sorted(hierarchy.EXCLUDED_FROM_PV_TOTAL),
        "metas_fields": metas.METAS_FIELDS,
        "metas_equipes_padrao": metas_rows("EQUIPES", "EQUIPE"),
        "metas_usuarios_padrao": metas_rows("USUARIOS", "USUARIO"),
        "feriados": sorted(d.isoformat() for d in dias_uteis.FERIADOS),
        "corte_mes": {"{}-{:02d}".format(a, m): d for (a, m), d in dias_uteis.CORTE_MES.items()},
        "tv": {
            "TV_PVS": tv_config.TV_PVS,
            "PV_SOMENTE_VISAO_GERAL": sorted(tv_config.PV_SOMENTE_VISAO_GERAL),
            "PV_FOTOS": tv_config.PV_FOTOS,
            "EQUIPES": tv_config.EQUIPES,
            "RANKING_PV_META": tv_config.RANKING_PV_META,
        },
    }


# Substituições Jinja/Flask -> Apps Script. Os dados deixam de vir de
# fetch('/api/data') e passam a vir de google.script.run.getDataJson().
API_SHIM = """
function apiData() {
  return new Promise(function (resolve, reject) {
    google.script.run
      .withSuccessHandler(function (txt) { resolve(JSON.parse(txt)); })
      .withFailureHandler(reject)
      .getDataJson();
  });
}
"""

FETCH_PATTERNS = [
    # tv.html / explorar.html
    (re.compile(r"const res = await fetch\('/api/data'\);\s*const state = await res\.json\(\);"),
     "const state = await apiData();"),
    # index.html
    (re.compile(r"const res = await fetch\('/api/data'\);\s*onNewState\(await res\.json\(\)\);"),
     "onNewState(await apiData());"),
]


def convert_template(name, refresh_seconds=3600, slide_seconds=60):
    src = open(os.path.join(ROOT, "templates", name + ".html"), encoding="utf-8").read()
    out = src
    out = out.replace("{{ url_for('static', filename='logo-grupo-global.png') }}", STATIC_BASE + "logo-grupo-global.png")
    out = out.replace("{{ url_for('static', filename='') }}", STATIC_BASE)
    out = out.replace("{{ refresh_seconds * 1000 }}", str(refresh_seconds * 1000))
    out = out.replace("{{ refresh_seconds }}", str(refresh_seconds))
    out = out.replace("{{ slide_seconds * 1000 }}", str(slide_seconds * 1000))
    out = out.replace("{{ slide_seconds }}", str(slide_seconds))
    out = out.replace("{{ tv_pvs | tojson }}", json.dumps(tv_config.TV_PVS, ensure_ascii=False))
    out = out.replace("{{ ranking_pv_meta | tojson }}", json.dumps(tv_config.RANKING_PV_META, ensure_ascii=False))
    n_fetch = 0
    for pat, rep in FETCH_PATTERNS:
        out, n = pat.subn(rep, out)
        n_fetch += n
    if n_fetch != 1:
        raise SystemExit("{}: esperava 1 fetch('/api/data'), achei {}".format(name, n_fetch))
    # Pôsteres de ranking (PNG gerados pelo poster_generator.py com Pillow)
    # não existem na versão Apps Script — a rotação da TV fica só com as telas.
    if name == "tv":
        out, n = re.subn(r"SLIDES = \[\.\.\.slides, \.\.\.rankingPosterSlides\(\)\];", "SLIDES = [...slides];", out)
        if n != 1:
            raise SystemExit("tv: não achei a linha dos pôsteres")
    # injeta o shim logo no começo do primeiro <script> inline
    idx = out.find("<script>")
    out = out[:idx + len("<script>")] + API_SHIM + out[idx + len("<script>"):]
    if "{{" in out or "{%" in out:
        sobra = re.findall(r"\{\{.*?\}\}|\{%.*?%\}", out)
        raise SystemExit("{}: sobrou Jinja: {}".format(name, sobra))
    return out


def main():
    os.makedirs(WEB_DIR, exist_ok=True)
    cfg = build_config()
    with open(os.path.join(OUT_DIR, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1, sort_keys=True)
    for name, page in (("index", "painel"), ("tv", "tv"), ("explorar", "explorar")):
        html = convert_template(name)
        with open(os.path.join(WEB_DIR, page + ".html"), "w", encoding="utf-8") as f:
            f.write(html)
    print("ok: config.json + web/painel.html, web/tv.html, web/explorar.html")


if __name__ == "__main__":
    main()
