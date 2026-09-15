# Painel CRM — Resumo com filtro PV / Supervisor / Consultor (atualização de hora em hora)

Painel ao vivo, conectado à API JSON-RPC do CRM (Odoo) em `global.solucoes.plus`,
usando a metodologia oficial de classificação definida pela Isabela (etapas →
atendido/convertido/concluído/em trâmite, e produto+solicitação → categorias de
receita). Atualiza os dados a cada 1 hora por padrão.

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
- `config/hierarquia_usuarios.xlsx` (export res.users: Login, Nome, Equipes de vendas):
  usado para montar o filtro PV → Supervisor → Consultor (ver `hierarchy.py`). Regras:
  - PV = parte antes do "-" no nome da equipe (ex: "PV 02 - Equipe Alexandre" → "PV 02").
  - Supervisor = o membro do time cujo primeiro nome bate com o sufixo da equipe (ex:
    "Alexandre Ornellas" é o supervisor de "PV 02 - Equipe Alexandre"). Quando o sufixo
    não bate com ninguém (ex: "Equipe Carteira"), o time fica sem supervisor identificado.
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
