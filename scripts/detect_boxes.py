"""
Detecta automaticamente as coordenadas exatas das 17 caixas de posição no
template poster_assets/base_hd.png, por segmentação de cor (o fill de cada
caixa é bem saturado e distinto do fundo fotográfico).

Rodar a partir da raiz do projeto: python3 scripts/detect_boxes.py
Usa poster_generator.BOXES como estimativa inicial (janela de busca), então
NÃO precisa estar perfeito ali — só precisa estar "perto" da caixa real.
Gera /tmp/detected_overlay.png para conferência visual antes de aplicar os
valores no BOXES do poster_generator.py.
"""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import poster_generator as pg


def detect_all(base_path=pg.BLANK, guess=None, margin=120):
    guess = guess or pg.BOXES
    img = Image.open(base_path).convert("RGB")
    arr = np.array(img).astype(int)
    H, W, _ = arr.shape
    out = {}
    for i, (x0, y0, x1, y1) in guess.items():
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        mx0, my0 = max(0, x0 - margin), max(0, y0 - margin)
        mx1, my1 = min(W, x1 + margin), min(H, y1 + margin)
        win = arr[my0:my1, mx0:mx1]
        ccx, ccy = cx - mx0, cy - my0
        seed = None
        for dy in range(0, win.shape[0] - ccy):
            y = ccy + dy
            px = win[y, ccx]
            sat = int(px.max()) - int(px.min())
            if sat > 20 and px.sum() < 400:
                seed = (y, ccx)
                break
        if seed is None:
            out[i] = None
            continue
        seed_color = win[seed[0], seed[1]].astype(int)
        dist = np.sqrt(((win - seed_color) ** 2).sum(axis=2))
        mask = dist < 70
        lbl, _ = ndimage.label(mask)
        comp = lbl == lbl[seed[0], seed[1]]
        ys, xs = np.where(comp)
        out[i] = (int(xs.min() + mx0), int(ys.min() + my0), int(xs.max() + mx0), int(ys.max() + my0))
    return out


if __name__ == "__main__":
    detected = detect_all()
    img = Image.open(pg.BLANK).convert("RGB")
    d = ImageDraw.Draw(img)
    for i, box in detected.items():
        if box is None:
            print(i, "NAO ENCONTRADO")
            continue
        l, t, r, b = box
        d.rectangle([l, t, r, b], outline=(0, 255, 0), width=4)
        d.text((l + 4, t + 4), str(i), fill=(0, 255, 0))
        print(f"{i}: ({l}, {t}, {r}, {b})")
    img.save("/tmp/detected_overlay.png")
    print("Overlay salvo em /tmp/detected_overlay.png")
