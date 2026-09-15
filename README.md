# Painel CRM — Resumo do Mês (atualização de hora em hora)

Painel ao vivo, conectado à API JSON-RPC do CRM (Odoo) em `global.solucoes.plus`,
usando a metodologia oficial de classificação definida pela Isabela (etapas →
atendido/convertido/concluído/em trâmite, e produto+solicitação → categorias de
receita). Atualiza os dados a cada 1 hora por padrão.

## O que o painel mostra

- **Leads totais do mês, Atendido, Convertido, Movimentações de etapa** (cards do topo).
- **Funil de propostas**: Proposta enviada x Aceite enviado.
- **Produção**: Concluído x Em trâmite.
- **Receita**: Receita total, Receita de renovação, Qtd. banda larga, Receita de aparelho.
- **Ranking por equipe** (mês): total de leads, atendidos e convertidos.
- **Ranking por consultor**: quantidade de movimentações de etapa no mês (exclui
  contas técnicas/sistema, configurável via `SYSTEM_USER_IDS`).

Todos os números usam o **mês atual como coorte por data de criação** (mesma base
do relatório `relatorio_crm_mes.xlsx` já entregue) — os valores devem sempre bater
com esse Excel se gerado no mesmo momento.

## Metodologia (arquivos em `config/`)

- `config/etapas_estagio.xlsx`: classifica cada etapa do CRM em ATENDIDO / CONVERTIDO
  / CONCLUIDO / EM TRAMITE (SIM/NÃO). Um lead é contado numa dessas categorias pela
  sua **etapa atual**.
- `config/classificacao_receita.xlsx` (abas SOLICITACAO e PRODUTOS): define, para 4
  categorias de receita (RECEITA TOTAL, RENOVAÇÃO, BANDA LARGA, APARELHO), quais tipos
  de solicitação e quais categorias de produto contam. **Uma linha de pedido só entra
  numa categoria se os dois critérios baterem (E lógico)**, confirmado com a Isabela.

Se a classificação de etapas ou de receita mudar, basta substituir esses dois
arquivos (mesmo nome, mesmas abas/colunas) e reiniciar o serviço — não precisa
mexer no código.

## Como funciona (técnico)

- `odoo_client.py`: cliente JSON-RPC (autentica com `common.authenticate` e chama
  `execute_kw`/`search_read`/`read_group`).
- `classification.py`: carrega os dois arquivos de `config/` e expõe funções de
  classificação.
- `app.py`: thread em segundo plano que busca e agrega os dados a cada
  `REFRESH_SECONDS` (padrão 3600 = 1h) e guarda em memória; endpoint `/api/data`
  serve esse cache; a página consulta esse endpoint no mesmo intervalo.
- **Nota técnica**: `read_group` do Odoo nesse servidor sub-conta registros de
  `crm.lead` (provavelmente por causa de um módulo de controle de acesso
  customizado, `_plus_access`) — por isso o painel busca os leads do mês
  individualmente (só 2 campos, leve) e agrega em Python, em vez de usar
  `read_group` para esse modelo. Para `sale.order.line` e `mail.tracking.value`
  o `read_group` funciona normalmente e é usado para eficiência.

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
