# Painel CRM — Resumo com filtro PV / Supervisor / Consultor (atualização de hora em hora)

Painel ao vivo, conectado à API JSON-RPC do CRM (Odoo) em `global.solucoes.plus`,
usando a metodologia oficial de classificação definida pela Isabela (etapas →
atendido/convertido/concluído/em trâmite, e produto+solicitação → categorias de
receita). Atualiza os dados a cada 1 hora por padrão.

## Modo TV (`/tv`)

Além do painel principal (`/`), existe uma tela separada em **`/tv`**, pensada para
ficar rodando sozinha numa TV/monitor: mostra **um consultor por vez**, com
Meta x Realizado (indicador principal, receita total), metas por produto
(Renovação, Aparelhos, Banda Larga), % do mailing/leads do mês já atendidos,
funil de vendas (Proposta enviada / Aceite enviado / Proposta recusada /
Finalizado) e um ranking dos 3 consultores com maior % de meta batida — e
avança automaticamente para o próximo consultor a cada 12s (configurável via
`TV_SLIDE_SECONDS`). Não inclui Ligações nem WhatsApp (sem esses dados no CRM).
Desde 2026-09-16, o modo TV mostra **só os consultores/supervisores do PV
02** (pedido da Isabela) — pra mudar o PV ou tirar o filtro, é só editar a
constante `TV_PV_FILTRO` no início do `<script>` de `templates/tv.html`
(o painel principal `/` continua mostrando todos os PVs normalmente).

## Consulta interativa (`/explorar`)

Desde 2026-09-16, além do `/tv` (rotação automática, só PV 02), existe
**`/explorar`**: a mesma lógica e o mesmo cartão do modo TV (Meta x Realizado,
metas por produto, atendimentos, funil, ranking Top 3 e foto), mas com
**seleção manual em cascata** — três combos no topo da página: **PV →
Supervisor → Consultor**. Não avança sozinho de tela em tela; quem está
olhando escolhe o que quer ver, mas os números continuam se atualizando
sozinhos (mesmo `/api/data`, mesmo intervalo de `REFRESH_SECONDS`).

- Ao escolher só o PV, mostra a **visão geral do PV** (soma de todas as
  equipes/consultores daquele PV) — ranking Top 3 nesse caso é entre os PVs.
- Ao escolher PV + Supervisor (sem consultor), mostra a **visão geral daquele
  supervisor/equipe** — ranking Top 3 entre os supervisores do mesmo PV.
- Ao escolher PV + Supervisor + Consultor, mostra o consultor individual,
  igual ao modo TV — ranking Top 3 entre os consultores da mesma equipe.
- Mostra todos os PVs (não tem o filtro `TV_PV_FILTRO` do `/tv`).
- Foto: mesma lógica do `/tv` (casa pelo primeiro nome via `fotos.py`); no
  nível "visão geral do PV" não tem foto (não é uma pessoa), só o rótulo "PV".

As metas vêm de **`config/metas.xlsx`** (abas `EQUIPES` e `USUARIOS`, com as
colunas `RECEITA_TOTAL`, `QUANTIDADE_BL`, `RECEITA_RENOVACAO`,
`RECEITA_APARELHOS`), pré-preenchido com os valores que a Isabela mandou por
print em 2026-09-15. A meta de cada equipe é a meta do supervisor daquela
equipe; a meta de cada PV é a soma das metas das equipes/supervisores daquele
PV. Um consultor sem linha em `USUARIOS` aparece como "Sem meta" em vez de
0%. Para atualizar as metas, é só editar esse Excel (mesmo nome/abas/colunas)
e reiniciar o serviço.

**Resolvido em 2026-09-16**: o 4º produto do esboço ("Móvel") não é uma
categoria de receita nova — é a própria **Receita Total** (a Isabela já
passa ali todo o valor considerado). "Metas por produto" no modo TV agora
mostra 4 caixinhas: Receita Total, Renovação, Aparelhos e Banda Larga (grid
2x2).

**Pendências conhecidas** (avisar a Isabela): o funil de vendas mostra
apenas contagem de CNPJs/leads por etapa, sem os valores em R$ mostrados no
esboço (o esboço tinha "R$ 1,85M" etc. por etapa — dá pra adicionar usando
`expected_revenue` do lead, mas ainda não foi confirmado se é esse o campo
certo, nem se é valor esperado ou já vendido); o "velocímetro" do esboço foi
simplificado para uma barra horizontal com as mesmas 3 faixas de cor
(vermelho/amarelo/verde), em vez do arco/ponteiro literal.

O tempo de troca de slide no modo TV é de **no mínimo 1 minuto** (confirmado
com a Isabela em 2026-09-15) — `TV_SLIDE_SECONDS` pode aumentar esse valor,
mas o código nunca deixa cair abaixo de 60s.

## Receita sempre do mês atual + pedidos "puxados" para o mês atual

A partir de 2026-09-15 (pedido da Isabela): **a receita (tiles do topo, metas
e o Meta x Realizado do modo TV) é sempre calculada com o período "Mês
atual"**, mesmo que o filtro de Período no topo do painel principal esteja em
"Últimos 60 dias" — esse seletor continua afetando leads, atendimento,
funil, produção e movimentações, só não afeta mais a receita.

Além disso, alguns pedidos (`sale.order`, identificados pelo número/cotação,
ex: `S41934`) foram criados/fechados no mês anterior mas **têm que contar
como receita do mês atual mesmo assim** (pedido da Isabela em 2026-09-15 —
antes a v6 tinha feito o oposto, excluído esses pedidos, o que estava
errado). A Isabela manda a lista desses números e eles entram na receita do
mês atual mesmo com a `create_date` da linha sendo de antes do início do
mês. Essa lista fica em **`config/pedidos_mes_atual.txt`** (um código por
linha, sem aspas). Para incluir mais pedidos: adicionar o(s) número(s)
nesse arquivo (uma linha por código) e reiniciar o serviço. O painel mostra
quantos pedidos foram incluídos assim como nota ao lado do filtro
PV/Supervisor/Consultor. Essa lista só afeta o período "Mês atual" (não o
"Últimos 60 dias").

Nota: 3 dos números da lista (`40541577`, `49980193`, `49984693`) não têm o
formato do número de pedido do CRM (que começa com "S", ex: `S41934`) — a
Isabela confirmou que é pra desconsiderar (não fazem mal, só não vão casar
com nenhum pedido).

## O que o painel mostra

- **Filtro de período**: Mês atual (coorte por data de criação) ou Últimos 60 dias
  (janela móvel, sempre "hoje - 60 dias" até agora), com um seletor no topo do painel.
- **Filtro PV / Supervisor / Consultor** (3 caixas de seleção em cascata, no topo):
  ao escolher um PV, o seletor de Supervisor mostra só os supervisores daquele PV; ao
  escolher um Supervisor, o de Consultor mostra só os consultores daquele supervisor.
  Com "Todos" em todos os filtros, os cards mostram o total geral.
- **Os mesmos indicadores em qualquer nível do filtro** (Todos, PV, Supervisor ou
  Consultor específico): Leads totais, Atendido, Convertido, Movimentações de etapa,
  Funil (Proposta enviada x Aceite enviado), Produção (Concluído x Em trâmite) e
  Receita (Total, Renovação, Qtd. banda larga, Aparelho) — sempre recalculados para o
  escopo e período selecionados.
- **Ranking por equipe**: total de leads, atendidos e convertidos por equipe (sempre
  para o período selecionado, independente do filtro de PV/Supervisor/Consultor).
- **Ranking por consultor**: quantidade de movimentações de etapa no escopo selecionado
  (exclui contas técnicas/sistema, configurável via `SYSTEM_USER_IDS`, e exclui etapas
  que não contam como movimentação — ver `NON_MOVEMENT_STAGES` abaixo). Se um PV ou
  Supervisor estiver selecionado, a lista mostra só os consultores daquele escopo.

A hierarquia PV → Supervisor → Consultor vem de `config/hierarquia_usuarios.xlsx`
(ver `hierarchy.py`). Leads/linhas/movimentações de usuários fora dessa hierarquia
(equipes não mapeadas, como BKO/GERENTE VIVO/PV071-00001/2/3, ou sem consultor
identificado) entram no total "Todos", mas não aparecem ao filtrar por um PV
específico — a contagem desses casos aparece como nota ao lado dos filtros.

## Metodologia (arquivos em `config/`)

- `config/etapas_estagio.xlsx`: classifica cada etapa do CRM em ATENDIDO / CONVERTIDO
  / CONCLUIDO / EM TRAMITE (SIM/NÃO). Um lead é contado numa dessas categorias pela
  sua **etapa atual**.
- `config/classificacao_receita.xlsx` (abas SOLICITACAO e PRODUTOS): define, para 4
  categorias de receita (RECEITA TOTAL, RENOVAÇÃO, BANDA LARGA, APARELHO), quais tipos
  de solicitação e quais categorias de produto contam. **Uma linha de pedido só entra
  numa categoria se os dois critérios baterem (E lógico)**, confirmado com a Isabela.
  A receita é atribuída ao PV/Supervisor/Consultor pelo campo `salesman_id` da linha
  de pedido (vendedor da linha).
  **Importante (confirmado com a Isabela em 2026-09-16): as 4 categorias são
  independentes, RECEITA TOTAL não é a soma das outras 3** — em particular,
  solicitações do tipo RENOVAÇÃO/MIGRAÇÃO/MIGRAÇÃO UP/MIGRAÇÃO DOWN e as
  categorias de produto de Aparelho **propositalmente não contam** como
  RECEITA TOTAL (só contam nas suas categorias específicas). Por isso é
  normal um consultor ter, por exemplo, mais Renovação do que Receita Total —
  não é bug.
  **Além disso (confirmado com a Isabela em 2026-09-16): só conta como
  receita um pedido cujo lead/oportunidade de origem esteja atualmente na
  etapa CONCLUIDO ou EM TRAMITE** (mesmas flags de `config/etapas_estagio.xlsx`
  usadas em Produção). Um pedido cujo lead esteja em qualquer outra etapa
  (ex: Proposta enviada, Aceite enviado, etc.) ou sem lead vinculado **não
  entra em nenhuma categoria de receita**. Essa ligação é feita via
  `sale.order.line → order_id (sale.order) → opportunity_id (crm.lead) →
  stage_id`. Se o campo `opportunity_id` não existir nesse CRM (customização
  específica), o log do serviço registra o erro e a receita fica zerada
  naquele ciclo até ajustar o nome do campo em `app.py`.
  **Correção em 2026-09-16**: os tipos de solicitação aceitos para BANDA
  LARGA estavam errados — a lista correta (confirmada pela Isabela) é
  **ALTA, PORTABILIDADE, PORTABILIDADE PF, MIGRACAO DE TECNOLOGIA**
  (substituindo NOVO/PORTADO/PORTADO PF/MIGRAÇÃO DE TECNOLOGIA, que eram os
  nomes usados nas outras categorias, não os da Banda Larga). O critério de
  produto (`All / Fixa Básica - Dados` / `All / Fixa Básica PF - Dados`)
  não mudou.
- `config/hierarquia_usuarios.xlsx` (export res.users: Login, Nome, Equipes de vendas):
  usado para montar o filtro PV → Supervisor → Consultor (ver `hierarchy.py`). Regras:
  - PV = parte antes do "-" no nome da equipe (ex: "PV 02 - Equipe Alexandre" → "PV 02").
  - **Atualizado em 2026-09-16 (pedido da Isabela)**: o nível "Supervisor" do
    drill-down mostra o **resultado da equipe**, rotulado como "EQUIPE
    <NOME>" (ex: "EQUIPE CARTEIRA", "EQUIPE RICHARD", "EQUIPE ALEXANDRE"),
    em vez do nome pessoal de quem supervisiona. Antes o sistema tentava
    achar, entre os membros do time, alguém cujo primeiro nome batesse com o
    sufixo da equipe — isso deixava times como "Equipe Carteira" (a própria
    Isabela é a supervisora, mas não aparece como membro na planilha) sem
    supervisor identificado ("sem supervisor"). Agora o rótulo é sempre
    derivado do nome da equipe, então todo time tem um rótulo consistente
    nesse nível.
  - Equipes fora do padrão "PV - Equipe <Nome>" (BKO, GERENTE VIVO, PV071-00001/2/3) são
    **excluídas** deste filtro — aparecem apenas no "Ranking por equipe" normal, e a
    contagem de leads fora do escopo é mostrada como nota ao lado dos filtros.

- **Etapas que não contam como "movimentação"** (confirmado com a Isabela em
  2026-09-15, em `classification.py` → `NON_MOVEMENT_STAGES`): quando um lead
  entra numa dessas etapas, a mudança é ignorada na contagem de movimentações
  por consultor, mesmo aparecendo em `mail.tracking.value`:
  - AGUARDANDO INTERAÇÃO
  - TENTATIVA DE CONTATO
  - CLIENTE JA RENOVADO
  - CORRECAO CONSULTOR
  - ATUALIZACOES POR ROBO

  Qualquer outra etapa (ex: PRIMEIRO CONTATO COM O CLIENTE, NAO TEM INTERESSE,
  ATENDIMENTO AGENDADO, PROPOSTA ENVIADA, PROPOSTA RECUSADA, ACEITE ENVIADO,
  SUPER VISÃO, QUALITY CALL PENDENTE, INPUT REALIZADO, etc.) conta normalmente.
  Se essa lista mudar, é só editar o `NON_MOVEMENT_STAGES` em `classification.py`.

Se a classificação de etapas, de receita ou a hierarquia de usuários mudar, basta
substituir os arquivos correspondentes em `config/` (mesmo nome, mesmas abas/colunas)
e reiniciar o serviço — não precisa mexer no código.

## Como funciona (técnico)

- `odoo_client.py`: cliente JSON-RPC (autentica com `common.authenticate` e chama
  `execute_kw`/`search_read`/`read_group`).
- `classification.py`: carrega os dois arquivos de classificação de `config/` e expõe
  funções de classificação de etapa/receita, além de `is_movement_stage()` (etapas
  que não contam como movimentação — lista hardcoded `NON_MOVEMENT_STAGES`).
- `hierarchy.py`: carrega `config/hierarquia_usuarios.xlsx`, deriva PV/Supervisor por
  equipe e casa cada login com o `id` numérico do usuário no CRM (`res.users`).
- `app.py`: a cada `REFRESH_SECONDS` (padrão 3600 = 1h), calcula os dados para os
  **dois períodos** (mês atual e últimos 60 dias) de uma vez, e para cada período monta
  tanto o total geral ("root") quanto a árvore completa PV → Supervisor → Consultor —
  tudo já pré-calculado e guardado em memória. O endpoint `/api/data` serve esse cache
  inteiro; o filtro de período/PV/Supervisor/Consultor no front-end só troca qual pedaço
  do JSON já recebido é exibido — não faz nenhuma chamada nova ao CRM, então trocar o
  filtro é instantâneo entre uma atualização e outra.
- **Nota técnica**: `read_group` do Odoo nesse servidor sub-conta registros de
  `crm.lead` (provavelmente por causa de um módulo de controle de acesso
  customizado, `_plus_access`) — por isso o painel busca os leads do período
  individualmente (poucos campos, leve) e agrega em Python, em vez de usar
  `read_group` para esse modelo. Pelo mesmo motivo (precisar atribuir cada
  linha/movimentação a um PV/Supervisor/Consultor e, no caso das movimentações,
  filtrar pela etapa de destino), `sale.order.line` e `mail.tracking.value` também são
  buscados como registros individuais e agregados em Python.

## Rodar localmente

```bash
pip install -r requirements.txt
export CRM_LOGIN=bi@global
export CRM_PASSWORD=sua_senha
python3 app.py
# abra http://localhost:8080
```

## Deploy no Railway

1. Suba esta pasta (incluindo `config/`) para um repositório no GitHub (o `.env`
   já está no `.gitignore`).
2. No Railway: **New Project → Deploy from GitHub repo**.
3. Em **Variables**, adicione:
   - `CRM_HOST` = `https://global.solucoes.plus/jsonrpc`
   - `CRM_DB` = `global`
   - `CRM_LOGIN` = `bi@global`
   - `CRM_PASSWORD` = (a senha)
   - `REFRESH_SECONDS` = `3600`
   - `SYSTEM_USER_IDS` = `1`
   - `LAST_N_DAYS` = `60` (opcional — período alternativo do seletor; padrão já é 60)
4. O Railway detecta o `Procfile` e usa `gunicorn` automaticamente.
5. Abra a URL gerada — é essa URL que fica aberta na TV/monitor.

## Auditoria detalhada (linha a linha)

Duas rotas de diagnóstico, sem autenticação (a URL do Railway não é
divulgada, mas não coloque nada além dos próprios dados do CRM nelas):

- **`/api/export_linhas_mes`**: todas as linhas de pedido do mês atual
  (mesmo critério usado no cálculo de receita), uma por produto vendido, com
  cliente, número do pedido, PV/Supervisor/Consultor, categoria de produto,
  tipo de solicitação, valor, etapa do lead vinculado e se conta como
  receita. É a fonte da aba "Por Consultor - Detalhado" do Excel que a
  Isabela pede pra auditar os resultados.
- **`/api/debug_pedidos?nomes=S12345,S67890`**: mesma coisa, mas só pra uma
  lista específica de números de pedido — útil pra investigar um caso
  pontual sem baixar tudo.

## Alterações de 2026-09-16 (texto e ranking)

- **"Meta" → "Plano Comercial"**: por questões internas da Isabela, todo texto
  visível no `/tv` e no `/explorar` que dizia "Meta"/"Metas" agora diz "Plano
  Comercial" (ex: "Plano Comercial x Realizado", "Plano Comercial por
  produto", "Sem plano" quando não há meta cadastrada). Isso é só o texto
  exibido — nomes internos de variáveis/CSS e o arquivo `config/metas.xlsx`
  continuam com "meta" no nome, sem impacto para quem só usa o painel.
- **Ranking Top 3 redesenhado**: o widget de ranking (1º/2º/3º colocado por %
  de plano batido) agora mostra a **foto do consultor maior**, com uma borda
  circular colorida (ouro/prata/bronze) e uma medalha 🥇🥈🥉 sobre a foto,
  em vez da lista antiga com números simples e fotos pequenas — presente
  tanto no `/tv` quanto no `/explorar`, em qualquer nível do filtro (no nível
  "equipe", sem foto de pessoa, usa as iniciais "EQ" como no restante do
  painel).

## Alterações de 2026-09-16 (2ª rodada — exclusão da Equipe Elton e fotos especiais)

- **Equipe Elton fora do resultado do PV** (pedido da Isabela): a "Equipe
  Elton" (`PV 02 - Equipe Elton`) continua aparecendo normalmente no
  `/explorar` como equipe selecionável, com seus próprios números — mas o
  resultado dela (leads, produção, receita, movimentações e a meta/plano)
  **não entra mais na soma do PV 02**. Antes de somar, é como se essa equipe
  não existisse para efeito do total do PV; ela só aparece quando alguém
  seleciona especificamente "EQUIPE ELTON" no filtro de Supervisor. Para
  adicionar/remover outra equipe dessa mesma exclusão, edite o conjunto
  `EXCLUDED_FROM_PV_TOTAL` em `hierarchy.py` (usa o nome completo da equipe,
  ex: `"PV 02 - Equipe Elton"`).
- **Fotos no nível "PV" e "Equipe"** (`/explorar`): esses níveis não são uma
  pessoa, então por padrão apareceriam sem foto (avatar "PV"/"EQ"). Duas
  regras (a 2ª corrigida em 2026-09-17 a pedido da Isabela, depois que
  "EQUIPE ALEXANDRE"/"EQUIPE RICHARD" continuaram sem foto na 1ª versão):
  - **PV 02**: sempre mostra a foto do **Flávio** (proprietário — arquivo
    `static/fotos/flavio-dono-pv02.jpg`, com nome de arquivo próprio, não
    `flavio.jpg`, pra não colidir com o casamento automático por primeiro
    nome do `fotos.py` — existe um consultor real chamado "Flavio Manoel"
    no PV03 que precisa continuar com as iniciais "FM", não a foto do dono).
    Outros PVs (ex: PV03) continuam com o avatar "PV".
  - **Qualquer equipe**: como a maioria das equipes leva o nome de quem é
    o supervisor/dono dela (ex: "EQUIPE ALEXANDRE" → Alexandre Ornellas,
    "EQUIPE RICHARD" → Richard Oliveira de Souza, "EQUIPE ELTON" → Elton
    Bitencourt), a foto é buscada normalmente pelo primeiro nome (mesmo
    casamento do `fotos.py`, usando o texto depois de "EQUIPE "). Quando
    existe o arquivo (ex: `alexandre.jpg`, `richard.jpg`, `elton.jpg`),
    aparece; quando não existe, cai no avatar "EQ" como antes. A única
    exceção é a **Equipe Carteira do PV 02**, onde ninguém se chama
    "Carteira" — nesse caso mostra a foto da própria **Isabela**
    (supervisora real dessa equipe — arquivo
    `static/fotos/isabela-supervisora.jpg`).
  Essas fotos só aparecem no `/explorar`; o `/tv` nunca mostra visão de PV
  nem de equipe (só consultor individual), então não é
  afetado.

## PDU — Produção por Dia Útil (2026-09-17, pedido da Isabela)

Novo card "📅 PDU — Produção por Dia Útil" no `/tv` (por consultor) e no
`/explorar` (em qualquer nível: PV, equipe ou consultor), logo abaixo do
Funil de vendas. Mostra quanto cada nível precisa "bater" de Receita Total
por dia útil pra fechar o Plano Comercial do mês:

- **PDU inicial** = Plano Comercial ÷ dias úteis totais do mês — o ritmo que
  seria necessário se desse pra dividir tudo igualzinho desde o dia 1.
- **PDU necessário agora** = (Plano Comercial − Realizado) ÷ dias úteis que
  ainda restam no mês — esse é o número que importa no dia a dia, porque já
  desconta o que já foi vendido e redivide o que falta pelos dias úteis que
  sobraram. Sobe se as vendas estão atrasadas em relação ao ritmo esperado,
  desce se estão adiantadas.
- Também mostra quantos dias úteis já passaram e quantos ainda restam no
  período considerado.

**Período do mês considerado**: dias úteis = segunda a sexta, exceto
feriados. A lista de feriados fica em **`config/feriados.txt`** (um por
linha, formato `DD/MM/AAAA`, já vem preenchida com os feriados nacionais de
2026 e 2027, incluindo Carnaval e Corpus Christi) — pra adicionar um feriado
municipal/estadual ou remover um que não se aplica à operação, é só editar
esse arquivo e reiniciar o serviço. O mês normalmente vai do dia 1 até o
último dia do calendário, mas dá pra configurar um "dia de corte" diferente
em `CORTE_MES` (no início de `dias_uteis.py`) pra meses em que o ciclo
comercial fecha antes — já está configurado **setembro/2026 fechando dia
29** (pedido explícito da Isabela: "do dia 01/09 até dia 29/09"). "Hoje" é
calculado no horário de Brasília (UTC-3), não no horário do servidor (UTC),
pra não errar a contagem de dias perto da meia-noite.

**Nota**: o PDU hoje é calculado só em cima da Receita Total (o indicador
principal "Plano Comercial x Realizado"). Se a Isabela quiser um PDU
separado por produto (Renovação, Aparelhos, Banda Larga) depois, dá pra
estender.

## Receita Concluída x Receita Em Trâmite (2026-09-17, pedido da Isabela)

Dentro do card do indicador principal ("Plano Comercial x Realizado —
Receita Total") em `/tv` e `/explorar`, além das linhas que já existiam
(Plano Comercial / Realizado / Falta bater), agora tem mais duas: **Receita
Concluída** e **Receita Em Trâmite** — a quebra do valor já Realizado de
Receita Total pela etapa do lead de origem (mesma classificação
CONCLUIDO/EM TRAMITE de `config/etapas_estagio.xlsx` usada no resto do
painel). As duas juntas somam exatamente o "Realizado" de cima, porque só
pedido cujo lead está em uma dessas duas etapas conta como receita (ver
seção de Metodologia). Essa quebra vale nos três níveis (PV, equipe,
consultor).

## Observações e próximos ajustes possíveis

- "Assistente Plus" (uid 1) aparece com muitas movimentações — parece ser uma
  conta técnica/automação, não uma pessoa; já vem excluída do ranking por padrão
  (`SYSTEM_USER_IDS=1`), mas vale confirmar.
- A equipe "Sales" ainda concentra um volume desproporcional de leads — mesma
  observação da v1, ainda não filtrada.
- Tipos de solicitação fora das 4 listas de receita (ex: "MIGRAÇÃO PP", "TT")
  simplesmente não contam para nenhuma categoria — isso é esperado, mas vale
  revisar periodicamente se surgirem tipos novos não classificados.
- A receita é atribuída pelo vendedor da linha de pedido (`salesman_id`), que pode
  não ser sempre o mesmo consultor dono do lead (`user_id`) — vale confirmar com a
  Isabela se isso é o esperado ou se a atribuição deveria seguir o dono do lead.
