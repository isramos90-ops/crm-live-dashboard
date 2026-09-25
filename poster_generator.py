"""
Gera os 5 pôsteres de ranking "estilo corrida de cavalos" (Receita Total,
Banda Larga, Renovação, Aparelhos, Atendidos) para os consultores do PV 02,
no mesmo modelo visual usado pela Vivo Empresas (pedido da Isabela em
2026-09-25).

Consome diretamente o "hierarchy" do período "month" já calculado pelo
app.py (mesma fonte de dados do painel /explorar e /tv), então os números
aqui SEMPRE batem com o resto do painel — não há nenhuma chamada extra ao
Odoo.

Uso: poster_generator.build_all(hierarchy, OUT_DIR) — salva os 5 PNGs em
OUT_DIR (ex: static/rankings/) prontos para servir como arquivos estáticos.

Reescrito do zero em 2026-09-25 para corrigir:
  - texto do nome sobrepondo o número da posição (Nº) em algumas caixas;
  - texto das análises de rodapé não cabendo no espaço da coluna;
  - exibir SEMPRE apenas o primeiro nome do consultor (pedido explícito
    da Isabela), tanto nas caixas de ranking quanto no rodapé.
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "poster_assets")
BLANK = os.path.join(ASSETS_DIR, "base_hd.png")
FDIR = os.path.join(ASSETS_DIR, "fonts")

FONT_ANTON = os.path.join(FDIR, "Anton-Regular.ttf")
FONT_BLACK = os.path.join(FDIR, "Montserrat-Black.ttf")
FONT_XBOLD = os.path.join(FDIR, "Montserrat-ExtraBold.ttf")
FONT_SEMI = os.path.join(FDIR, "Montserrat-SemiBold.ttf")
FONT_BOLDITALIC = os.path.join(FDIR, "Montserrat-BoldItalic.ttf")

# Pedido da Isabela em 2026-09-25: excluir o Elton Bitencourt destes rankings.
EXCLUDE_NAMES = {"elton bitencourt"}

# Coordenadas (x0, y0, x1, y1) de cada caixa de posição no template base_hd.png
# (2496x1664), medidas manualmente com grid de pixels e verificadas com
# overlay de retângulos verdes sobre a imagem original.
BOXES = {
    1:  (85, 385, 330, 495),
    2:  (355, 393, 600, 513),
    3:  (620, 405, 865, 525),
    4:  (875, 415, 1090, 535),
    5:  (1110, 425, 1330, 550),
    6:  (1345, 440, 1560, 565),
    7:  (1590, 490, 1810, 610),
    8:  (1815, 500, 2040, 620),
    9:  (2035, 510, 2265, 630),
    10: (2255, 520, 2480, 640),
    11: (170, 863, 435, 985),
    12: (480, 870, 745, 995),
    13: (855, 875, 1160, 1015),
    14: (1210, 875, 1420, 1015),
    15: (1480, 878, 1690, 1018),
    16: (1750, 880, 1965, 1020),
    17: (2035, 885, 2280, 1020),
}
BOX_PAD = 18

# Medido em todas as 17 caixas (detecção de pixels brancos do label "Nº"):
# o número de posição termina, de forma muito consistente, em ~54% da
# altura de cada caixa — independente do tamanho da caixa. Usamos essa
# fração fixa como ponto de partida seguro para o nome/valor abaixo dele.
LABEL_BOTTOM_FRAC = 0.54

# Frações (relativas à altura da caixa) onde centralizamos nome e valor.
# Deixadas com boa margem abaixo de LABEL_BOTTOM_FRAC para nunca colidir
# com o número, mesmo considerando o contorno (stroke) do texto.
NAME_CY_FRAC = 0.70
VALUE_CY_FRAC = 0.885

PURPLE_FILL = (58, 20, 100)
PURPLE_BORDER = (150, 110, 210)
HEADLINE_COLOR = (14, 4, 66)

KPIS = {
    "receita_total": {"title": "RECEITA TOTAL", "kind": "money", "panorama": "em receita total", "file": "receita_total.png"},
    "bl_qtd":        {"title": "BANDA LARGA", "kind": "int", "panorama": "vendas de Banda Larga", "file": "banda_larga.png"},
    "renovacao":     {"title": "RENOVAÇÃO", "kind": "money", "panorama": "em receita de renovação", "file": "renovacao.png"},
    "aparelhos":     {"title": "APARELHOS", "kind": "money", "panorama": "em receita de aparelhos", "file": "aparelhos.png"},
    "atendidos":     {"title": "ATENDIDOS", "kind": "int", "panorama": "atendimentos realizados", "file": "atendidos.png"},
}


def fmt_money(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def fmt_int(v):
    return f"{int(round(v)):,}".replace(",", ".")


def _fmt(kind, v):
    return fmt_money(v) if kind == "money" else fmt_int(v)


def first_name(full_name):
    """Pedido explícito da Isabela (2026-09-25): mostrar SEMPRE só o
    primeiro nome do consultor, em qualquer lugar do pôster."""
    words = (full_name or "").strip().split()
    return words[0].capitalize() if words else ""


def fit_font(draw, text, max_w, start_size, font_path, min_size=9):
    size = start_size
    while size > min_size:
        f = ImageFont.truetype(font_path, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return ImageFont.truetype(font_path, min_size)


def draw_centered(draw, cx, cy, text, font, fill, stroke_fill=None, stroke_width=0):
    draw.text((cx, cy), text, font=font, fill=fill, anchor="mm",
               stroke_width=stroke_width, stroke_fill=stroke_fill)


def draw_centered_multiline(draw, cx, cy, lines, font, fill, line_gap=4, stroke_fill=None, stroke_width=0):
    heights, widths = [], []
    for line in lines:
        bbox = font.getbbox(line)
        heights.append(bbox[3] - bbox[1])
        widths.append(draw.textlength(line, font=font))
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = cy - total_h / 2
    for line, h, w in zip(lines, heights, widths):
        bbox = font.getbbox(line)
        draw.text((cx - w / 2, y - bbox[1]), line, font=font, fill=fill,
                   stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += h + line_gap


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_left_multiline(draw, x, y, lines, font, fill, line_gap=5):
    cy = y
    for line in lines:
        bbox = font.getbbox(line)
        h = bbox[3] - bbox[1]
        draw.text((x, cy - bbox[1]), line, font=font, fill=fill)
        cy += h + line_gap
    return cy


def fit_wrapped(draw, text, max_width, max_height, start_size=22, min_size=12, font_path=FONT_SEMI, line_gap=5):
    """Encolhe a fonte até o texto quebrado em linhas caber tanto na
    largura (max_width) quanto na altura disponível (max_height)."""
    size = start_size
    best = None
    while size >= min_size:
        f = ImageFont.truetype(font_path, size)
        lines = wrap_text(draw, text, f, max_width)
        bbox = f.getbbox("Ág")
        line_h = bbox[3] - bbox[1]
        total_h = line_h * len(lines) + line_gap * (len(lines) - 1)
        best = (f, lines)
        if total_h <= max_height:
            return f, lines
        size -= 1
    return best


def draw_headline(draw):
    lines = ["NA PISTA DO RESULTADO,", "CADA CONSULTOR FAZ A DIFERENÇA!"]
    f = ImageFont.truetype(FONT_BOLDITALIC, 42)
    while max(draw.textlength(l, font=f) for l in lines) > 950 and f.size > 22:
        f = ImageFont.truetype(FONT_BOLDITALIC, f.size - 1)
    draw_centered_multiline(draw, 1350, 100, lines, f, HEADLINE_COLOR, line_gap=10)


def draw_tag_sign(draw):
    x0, y0, x1, y1 = 2180, 385, 2470, 505
    draw.rectangle([x0 + 28, y1 - 8, x0 + 46, y1 + 48], fill=(90, 60, 40))
    draw.rectangle([x1 - 58, y1 - 8, x1 - 40, y1 + 48], fill=(90, 60, 40))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=20, fill=PURPLE_FILL, outline=PURPLE_BORDER, width=6)
    lines = ["INTERNET", "QUE CONECTA", "RESULTADOS!"]
    cx = (x0 + x1) / 2
    f = ImageFont.truetype(FONT_XBOLD, 34)
    while max(draw.textlength(l, font=f) for l in lines) > (x1 - x0) * 0.86 and f.size > 16:
        f = ImageFont.truetype(FONT_XBOLD, f.size - 1)
    draw_centered_multiline(draw, cx, (y0 + y1) / 2, lines, f, (255, 255, 255), line_gap=4)


def draw_sign_title(base_img, kpi_title):
    # Pedido da Isabela em 2026-09-25: sem faixa/placa roxa — o texto vai
    # direto sobre a madeira da placa já existente no template, só com
    # contorno escuro para ficar legível sobre a textura de madeira.
    PW, PH = 560, 190
    patch = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    pd = ImageDraw.Draw(patch)
    f1 = ImageFont.truetype(FONT_ANTON, 42)
    f2 = fit_font(pd, kpi_title, PW - 40, 36, FONT_ANTON, min_size=22)
    f3 = ImageFont.truetype(FONT_SEMI, 16)
    draw_centered(pd, PW / 2, 48, "RANKING", f1, (255, 255, 255), stroke_fill=(40, 15, 70), stroke_width=4)
    draw_centered(pd, PW / 2, 98, kpi_title, f2, (255, 221, 74), stroke_fill=(60, 20, 10), stroke_width=4)
    draw_centered(pd, PW / 2, 148, "VENDAS POR CONSULTOR (MENSAL)", f3, (255, 255, 255), stroke_fill=(40, 15, 70), stroke_width=3)
    rotated = patch.rotate(3.3, expand=True, resample=Image.BICUBIC)
    cx, cy = 555, 115
    base_img.paste(rotated, (cx - rotated.width // 2, cy - rotated.height // 2), rotated)


def _extract_pv02_consultants(hierarchy):
    """hierarchy = data['periods']['month']['hierarchy'] do app.py."""
    out = []
    for pv_entry in hierarchy:
        if pv_entry.get("pv") != "PV 02":
            continue
        for sup in pv_entry.get("supervisors", []):
            for c in sup.get("consultores", []):
                nome = (c.get("nome") or "").strip()
                if not nome or nome.lower() in EXCLUDE_NAMES:
                    continue
                revenue = c.get("revenue", {})
                out.append({
                    "nome": nome,
                    "receita_total": revenue.get("RECEITA TOTAL", {}).get("receita", 0) or 0,
                    "bl_qtd": revenue.get("BANDA LARGA", {}).get("qtd", 0) or 0,
                    "renovacao": revenue.get("RENOVAÇÃO", {}).get("receita", 0) or 0,
                    "aparelhos": revenue.get("APARELHO", {}).get("receita", 0) or 0,
                    "atendidos": c.get("atendido", 0) or 0,
                })
    return out


def _build_one(kpi_key, consultants, out_path):
    kpi = KPIS[kpi_key]
    kind = kpi["kind"]
    qualified = [c for c in consultants if (c.get(kpi_key) or 0) > 0]
    qualified.sort(key=lambda c: c[kpi_key], reverse=True)
    ranked = qualified[:17]

    img = Image.open(BLANK).convert("RGB")
    draw_sign_title(img, kpi["title"])
    draw = ImageDraw.Draw(img)
    draw_headline(draw)
    draw_tag_sign(draw)

    # -- caixas de ranking -------------------------------------------------
    entries = []
    for i, person in enumerate(ranked, start=1):
        if i not in BOXES:
            continue
        bx0, by0, bx1, by1 = BOXES[i]
        max_w = (bx1 - bx0) - 2 * BOX_PAD
        name = first_name(person["nome"])
        value_txt = _fmt(kind, person[kpi_key])
        entries.append((i, name, value_txt, max_w))

    # Tamanho único de fonte para nome/valor em todas as caixas, mas com
    # teto conservador: preferimos texto um pouco menor e sempre legível
    # a um texto grande que invada a área do número da posição.
    min_size = 14
    name_size = min([fit_font(draw, e[1], e[3], 24, FONT_XBOLD, min_size).size for e in entries], default=20)
    val_size = min([fit_font(draw, e[2], e[3], 22, FONT_BLACK, min_size).size for e in entries], default=18)
    f_name_common = ImageFont.truetype(FONT_XBOLD, name_size)
    f_val_common = ImageFont.truetype(FONT_BLACK, val_size)

    for i, name, value_txt, max_w in entries:
        bx0, by0, bx1, by1 = BOXES[i]
        bh = by1 - by0
        cx = (bx0 + bx1) / 2
        f_name = f_name_common if draw.textlength(name, font=f_name_common) <= max_w else \
            fit_font(draw, name, max_w, name_size, FONT_XBOLD, min_size=12)
        f_val = f_val_common if draw.textlength(value_txt, font=f_val_common) <= max_w else \
            fit_font(draw, value_txt, max_w, val_size, FONT_BLACK, min_size=12)
        draw_centered(draw, cx, by0 + bh * NAME_CY_FRAC, name, f_name, (255, 255, 255),
                      stroke_fill=(0, 0, 0), stroke_width=1)
        draw_centered(draw, cx, by0 + bh * VALUE_CY_FRAC, value_txt, f_val, (255, 224, 90),
                      stroke_fill=(50, 20, 5), stroke_width=1)

    _draw_bottom_bar(draw, ranked, qualified, kpi_key, kpi)

    tmp_path = out_path + ".tmp.png"
    img.save(tmp_path, format="PNG")
    os.replace(tmp_path, out_path)  # atomic-ish swap so /static never serves a half-written file


# A faixa decorativa inferior do template (troféu / gráfico / foguete)
# tem uma área ÚTIL bem mais estreita do que a largura total de cada
# "coluna" visual, porque cada ícone ocupa a ponta esquerda e o próximo
# ícone já começa logo depois. Medido com grid de pixels sobre o
# base_hd.png: a faixa roxa vai de y=1300 a y=1468, e o texto de cada
# coluna precisa ficar ENTRE o ícone dela e o ícone da coluna seguinte.
BOTTOM_ROW_Y0 = 1300
BOTTOM_ROW_Y1 = 1468
BOTTOM_COLS = {
    "destaques": (215, 560),   # depois do troféu, antes do ícone de gráfico
    "panorama":  (710, 1110),  # depois do gráfico, antes do ícone de foguete
    "oportunidade": (1280, 1870),  # depois do foguete, antes da bandeira
}


def _draw_bottom_col(draw, key, header_text, body_text):
    x0, x1 = BOTTOM_COLS[key]
    white, lavender = (255, 255, 255), (230, 225, 245)
    header_font = fit_font(draw, header_text, x1 - x0, 23, FONT_XBOLD, min_size=14)
    draw.text((x0, BOTTOM_ROW_Y0 + 4), header_text, font=header_font, fill=white)
    body_y0 = BOTTOM_ROW_Y0 + 4 + (header_font.getbbox(header_text)[3] - header_font.getbbox(header_text)[1]) + 8
    body_h = BOTTOM_ROW_Y1 - 6 - body_y0
    f, lines = fit_wrapped(draw, body_text, x1 - x0, body_h, start_size=22, min_size=13)
    draw_left_multiline(draw, x0, body_y0, lines, f, lavender, line_gap=4)


def _draw_bottom_bar(draw, ranked, qualified, kpi_key, kpi):
    kind = kpi["kind"]

    # Coluna 1 — Destaques do mês (bem curto: só o líder, pro texto caber)
    leader = ranked[0]
    txt = f"{first_name(leader['nome'])} lidera com {_fmt(kind, leader[kpi_key])}."
    if len(ranked) > 1:
        s2 = ranked[1]
        txt = (f"{first_name(leader['nome'])} lidera ({_fmt(kind, leader[kpi_key])}), "
               f"{first_name(s2['nome'])} em 2º.")
    _draw_bottom_col(draw, "destaques", "DESTAQUES DO MÊS", txt)

    # Coluna 2 — Panorama geral
    total = sum(c[kpi_key] for c in qualified)
    top3_sum = sum(c[kpi_key] for c in ranked[:3])
    pct = (top3_sum / total * 100) if total else 0
    pct_txt = f"{pct:.0f}"
    txt = f"{_fmt(kind, total)} {kpi['panorama']}. Top 3 = {pct_txt}% do total."
    _draw_bottom_col(draw, "panorama", "PANORAMA GERAL", txt)

    # Coluna 3 — Oportunidade
    n = len(ranked)
    alert_start = max(1, n - 3)
    alert_count = n - alert_start + 1
    if n >= 2:
        txt = f"{alert_count} consultores ({alert_start}ª–{n}ª posição) precisam acelerar."
    else:
        txt = "Poucos consultores pontuando este mês."
    _draw_bottom_col(draw, "oportunidade", "OPORTUNIDADE", txt)


def build_all(hierarchy, out_dir):
    """Gera os 5 PNGs e retorna a lista de nomes de arquivo gerados."""
    os.makedirs(out_dir, exist_ok=True)
    consultants = _extract_pv02_consultants(hierarchy)
    if not consultants:
        raise ValueError("Nenhum consultor do PV 02 encontrado no hierarchy — abortando geração dos pôsteres.")
    generated = []
    for kpi_key, kpi in KPIS.items():
        out_path = os.path.join(out_dir, kpi["file"])
        _build_one(kpi_key, consultants, out_path)
        generated.append(kpi["file"])
    return generated
