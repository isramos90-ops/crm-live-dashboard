"""
Configuração da TV / Explorar — quem aparece, com que nome e com que foto.
Atualizado em 2026-10-08 (plano comercial de outubro, entrada do PV 03 e
criação do PV 04, desfeita em 2026-10-16).

Tudo que é "regra de exibição" e não vem do CRM fica aqui, num lugar só:

- PV_FOTOS: foto do proprietário em cada visão geral de PV. O proprietário
  NÃO tem nome exibido (aparece só "PV 02", "PV 03"...), pedido da Isabela.
- EQUIPES: para cada equipe do CRM (nome exato em "Equipes de vendas"):
    label   -> nome mostrado na TV (ex: a equipe "PV03 - EQUIPE CARTEIRA" do
               CRM é a equipe da Daphne, então aparece "EQUIPE DAPHNE")
    pv      -> força o PV (nenhuma equipe usa hoje)
    lideres -> fotos mostradas no cabeçalho da tela da equipe
               (ex: Equipe Daphne mostra Daphne + Elvio, o gerente)
- LOGIN_EQUIPE: força a equipe de um login, quando o plano comercial coloca
  a pessoa numa equipe diferente da cadastrada no CRM.
- NOME_EXIBICAO: nome curto mostrado na TV no lugar do nome do CRM.
- OCULTAR_DA_TV: logins que somam no resultado da equipe/PV, mas não
  ganham tela própria nem entram no Top 3 (ex: linhas de PARCEIROS do plano).
- PV_SOMENTE_VISAO_GERAL: PVs que aparecem só na tela geral (sem telas de
  equipe/consultor).
- TV_PVS: PVs exibidos na rotação da TV, na ordem.

Fotos de pessoas ficam em static/fotos/pessoas/<parte do login antes do @>.jpg
(ex: agnes.reis@global -> agnes.reis.jpg). Quem ainda não está na planilha
config/hierarquia_usuarios.xlsx tem a foto salva pelo nome do plano
(ex: amanda-coimbra.jpg) — o fotos.py também tenta casar pelo nome.
"""

TV_PVS = ["PV 02", "PV 03"]

PV_SOMENTE_VISAO_GERAL = set()

PV_FOTOS = {
    "PV 01": "fotos/pv/pv-01.jpg",
    "PV 02": "fotos/pv/pv-02.jpg",
    "PV 03": "fotos/pv/pv-03.jpg",
}

EQUIPES = {
    "PV 02 - Equipe Carteira": {
        "label": "EQUIPE CARTEIRA",
        "lideres": [{"nome": "Isabela", "cargo": "Supervisora", "foto": "fotos/lideres/isabela.jpg"}],
    },
    "PV 02 - Equipe Richard": {
        "label": "EQUIPE RICHARD",
        "lideres": [{"nome": "Richard", "cargo": "Supervisor", "foto": "fotos/lideres/richard.jpg"}],
    },
    "PV 02 - Equipe Alexandre": {
        "label": "EQUIPE ALEXANDRE",
        "lideres": [{"nome": "Alexandre", "cargo": "Supervisor", "foto": "fotos/lideres/alexandre.jpg"}],
    },
    # 2026-10-16 (Isabela): o Elton volta a ser supervisor dentro do PV 02 e
    # o resultado da equipe dele soma na gestão do PV 02 (o PV 04 deixou de
    # existir). Ele não tem tela/ranking de consultor (não está no plano
    # individual), só a da equipe.
    "PV 02 - Equipe Elton": {
        "label": "EQUIPE ELTON",
        "lideres": [{"nome": "Elton", "cargo": "Supervisor", "foto": "fotos/lideres/elton.jpg"}],
    },
    "PV03 - EQUIPE CAIO": {
        "label": "EQUIPE CAIO",
        "lideres": [{"nome": "Caio", "cargo": "Supervisor", "foto": "fotos/lideres/caio.jpg"}],
    },
    # No CRM a equipe da Daphne se chama "PV03 - EQUIPE CARTEIRA".
    "PV03 - EQUIPE CARTEIRA": {
        "label": "EQUIPE DAPHNE",
        "lideres": [
            {"nome": "Daphne", "cargo": "Supervisora", "foto": "fotos/lideres/daphne.jpg"},
            {"nome": "Elvio", "cargo": "Gerente", "foto": "fotos/lideres/elvio.jpg"},
        ],
    },
    "PV03 - EQUIPE MARCOS": {
        "label": "EQUIPE MARCOS",
        "lideres": [{"nome": "Marcos", "cargo": "Supervisor", "foto": "fotos/lideres/marcos.jpg"}],
    },
}

# Plano de outubro/2026: a Denia é da equipe do Marcos (no CRM está na
# equipe da Daphne).
LOGIN_EQUIPE = {
    "denia.marcia@global": "PV03 - EQUIPE MARCOS",
}

NOME_EXIBICAO = {
    "bruno.jose@global": "Bruno Martins",
    "cauany.santos@grupoglobal.net.br": "Cauany Santos",
}

# Vendas que só somam no resultado geral do PV — não entram em nenhuma
# equipe nem aparecem na TV como consultor (Isabela, 2026-10-09: o Elvio é
# gerente e "só entra para o resultado geral").
SO_RESULTADO_DO_PV = {
    "elvio@global",
}

# Linhas "(PARCEIROS)" do plano: a meta e as vendas somam na equipe, mas a
# pessoa não aparece como consultor na TV nem no Top 3.
OCULTAR_DA_TV = {
    "richard.souza@global",
    "alexandre@global",
}
