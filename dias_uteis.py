"""
Cálculo de dias úteis e PDU (Produção por Dia Útil) — pedido da Isabela em
2026-09-17: sempre consideramos o plano comercial (Receita Total) dividido
pelos dias úteis do mês pra saber quanto precisa "bater" por dia útil.
Conforme os dias passam, o valor que ainda falta pra bater o plano é
redividido pelos dias úteis que ainda restam no mês — então o PDU necessário
sobe se as vendas estão atrasadas em relação ao ritmo esperado, e desce se
estão adiantadas.

Período considerado no mês: do dia 1 até o "dia de corte" (normalmente o
último dia do calendário, mas configurável em CORTE_MES — ex: setembro/2026
fecha dia 29, não dia 30, conforme pedido da Isabela em 2026-09-17: "do dia
01/09 até dia 29/09"). Dias não úteis = sábados, domingos e os feriados
listados em config/feriados.txt (editável sem precisar mexer no código).
"""
import datetime as dt
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FERIADOS_PATH = os.path.join(BASE_DIR, "config", "feriados.txt")

# Dia de corte do mês pro cálculo de PDU, quando for diferente do último dia
# do calendário. Chave: (ano, mês) -> dia do corte. Editar/adicionar aqui
# quando um mês tiver um fechamento comercial antes do fim do mês (o padrão,
# quando o mês não está listado aqui, é o último dia do calendário).
CORTE_MES = {
    (2026, 9): 29,  # pedido da Isabela em 2026-09-17
}


def _load_feriados():
    feriados = set()
    if not os.path.isfile(FERIADOS_PATH):
        return feriados
    with open(FERIADOS_PATH, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            partes = line.split("/")
            if len(partes) != 3:
                continue
            try:
                d, m, y = (int(p) for p in partes)
                feriados.add(dt.date(y, m, d))
            except ValueError:
                continue
    return feriados


FERIADOS = _load_feriados()


def is_dia_util(d):
    return d.weekday() < 5 and d not in FERIADOS


def dias_uteis_no_periodo(inicio, fim):
    """Conta dias úteis entre `inicio` e `fim` (objetos date), ambos inclusive."""
    if fim < inicio:
        return 0
    total = 0
    d = inicio
    while d <= fim:
        if is_dia_util(d):
            total += 1
        d += dt.timedelta(days=1)
    return total


def fim_do_mes(ano, mes):
    corte = CORTE_MES.get((ano, mes))
    if corte:
        return dt.date(ano, mes, corte)
    if mes == 12:
        proximo = dt.date(ano + 1, 1, 1)
    else:
        proximo = dt.date(ano, mes + 1, 1)
    return proximo - dt.timedelta(days=1)


def info_dias_uteis(hoje):
    """Retorna {dias_uteis_totais, dias_uteis_decorridos, dias_uteis_restantes,
    inicio, fim} pro mês de `hoje` (objeto date), considerando o dia de corte
    (CORTE_MES) e os feriados de config/feriados.txt. "Decorridos" inclui o
    dia de hoje (se for dia útil) — o painel assume que o dado de hoje já
    conta como produção do dia."""
    inicio_mes = dt.date(hoje.year, hoje.month, 1)
    fim_mes = fim_do_mes(hoje.year, hoje.month)
    totais = dias_uteis_no_periodo(inicio_mes, fim_mes)
    fim_decorrido = min(hoje, fim_mes)
    decorridos = dias_uteis_no_periodo(inicio_mes, fim_decorrido) if fim_decorrido >= inicio_mes else 0
    restantes = max(0, totais - decorridos)
    return {
        "inicio": inicio_mes.isoformat(),
        "fim": fim_mes.isoformat(),
        "dias_uteis_totais": totais,
        "dias_uteis_decorridos": decorridos,
        "dias_uteis_restantes": restantes,
    }


def calcula_pdu(meta, realizado, dias_info):
    """PDU inicial = plano ÷ dias úteis totais do mês (ritmo parelho, do
    jeito que seria se desse pra dividir tudo igual desde o dia 1).
    PDU necessário = (plano - realizado) ÷ dias úteis que ainda restam —
    esse é o valor que realmente importa no dia a dia, porque já leva em
    conta o quanto já foi vendido."""
    totais = dias_info["dias_uteis_totais"]
    restantes = dias_info["dias_uteis_restantes"]
    meta = meta or 0
    realizado = realizado or 0
    pdu_inicial = round(meta / totais, 2) if totais else None
    falta = max(0.0, meta - realizado)
    if restantes > 0:
        pdu_necessario = round(falta / restantes, 2)
    elif falta > 0:
        # Não sobrou dia útil no mês (ou já passou do corte) e ainda falta
        # bater plano: não tem mais como diluir, mostra o valor cheio.
        pdu_necessario = round(falta, 2)
    else:
        pdu_necessario = 0.0
    return {
        "pdu_inicial": pdu_inicial,
        "pdu_necessario": pdu_necessario,
        "falta": round(falta, 2),
    }
