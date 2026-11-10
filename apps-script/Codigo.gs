/**
 * Painel CRM — versão Google Apps Script (sem Railway)
 * =====================================================
 * Mesma lógica do app.py (painel-crm), rodando de graça na conta Google:
 *
 *   - De hora em hora, o gatilho chama atualizarDados(): busca no CRM
 *     (NEO CRM / Odoo, JSON-RPC), calcula tudo (funil, produção, receita,
 *     movimentações, árvore PV → Equipe → Consultor, metas, PDU) e grava o
 *     resultado num arquivo JSON no seu Google Drive.
 *   - O link do App da Web mostra as telas, que leem esse JSON:
 *       <link>?p=tv        → modo TV (rotação automática)
 *       <link>?p=explorar  → Explorar (filtro manual + Rankings)
 *       <link>?p=painel    → painel completo (filtros e período)
 *
 * O que você mexe sem tocar em código: a planilha "Painel CRM — Configuração"
 * (criada pelo configurarPainel):
 *   - aba PEDIDOS_MES     → pedidos que contam na receita do mês atual mesmo
 *                           tendo sido cadastrados antes (um por linha)
 *   - aba METAS_EQUIPES / METAS_USUARIOS → plano comercial do mês
 *
 * Etapas, classificação de receita, hierarquia, fotos e as telas vêm do
 * GitHub (isramos90-ops/crm-live-dashboard, pasta apps-script/) — mudanças
 * lá chegam aqui sozinhas, sem colar código de novo.
 *
 * Senha do CRM: Configurações do projeto (engrenagem) → Propriedades do
 * script → CRM_PASSWORD. Nunca escreva a senha neste arquivo.
 */

// ===================== Configuração =====================
var CRM_HOST = 'https://global.solucoes.plus/jsonrpc';
var CRM_DB = 'global';
var CRM_LOGIN_PADRAO = 'bi@global';
var GITHUB_RAW = 'https://raw.githubusercontent.com/isramos90-ops/crm-live-dashboard/main/';

var SYSTEM_USER_IDS = [1];          // "Assistente Plus" — fora do ranking de movimentações
var STAGE_TRACKING_FIELD_ID = 6197; // mail.tracking.value: "Stage (Lead/Opportunity)"
var LAST_N_DAYS = 60;
var PAGE_SIZE = 5000;               // registros por chamada ao CRM
var CACHE_SECONDS = 6 * 60 * 60;    // config/telas do GitHub ficam 6h em cache

var NOME_PLANILHA = 'Painel CRM — Configuração';
var NOME_ARQUIVO_DADOS = 'painel-crm-dados.json';

// ===================== Instalação (rodar 1 vez) =====================

/**
 * Rode esta função uma vez (botão ▶ Executar com "configurarPainel"
 * selecionado). Ela cria a planilha de configuração, o arquivo de dados,
 * o gatilho de hora em hora, e já faz a primeira atualização.
 * Pode rodar de novo sem problema: não duplica nada.
 */
function configurarPainel() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('CRM_PASSWORD')) {
    throw new Error('Falta a senha do CRM: Configurações do projeto → Propriedades do script → ' +
      'adicionar CRM_PASSWORD (e, se quiser outro usuário, CRM_LOGIN).');
  }
  var ss = abrirPlanilha_(true);
  arquivoDados_(true);

  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'atualizarDados') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('atualizarDados').timeBased().everyHours(1).create();

  atualizarDados();
  Logger.log('Pronto. Planilha de configuração: ' + ss.getUrl());
  Logger.log('Agora: Implantar → Nova implantação → App da Web.');
}

function abrirPlanilha_(criarSeFaltar) {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('SHEET_ID');
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (e) { if (!criarSeFaltar) throw e; }
  }
  if (!criarSeFaltar) throw new Error('Planilha de configuração não encontrada — rode configurarPainel().');
  var cfg = getConfig_();
  var ss = SpreadsheetApp.create(NOME_PLANILHA);

  var shPed = ss.getSheets()[0];
  shPed.setName('PEDIDOS_MES');
  var pedidos = [];
  try {
    pedidos = (UrlFetchApp.fetch(GITHUB_RAW + 'config/pedidos_mes_atual.txt').getContentText() || '')
      .split(/\r?\n/).map(function (s) { return s.trim(); }).filter(String);
  } catch (e) { /* começa vazia */ }
  var linhas = [['PEDIDO (um por linha — conta na receita do mês atual mesmo cadastrado antes)']]
    .concat(pedidos.map(function (p) { return [p]; }));
  shPed.getRange(1, 1, linhas.length, 1).setValues(linhas);
  shPed.getRange(1, 1).setFontWeight('bold');
  shPed.setColumnWidth(1, 520);

  var cab = ['EQUIPE'].concat(cfg.metas_fields);
  var shEq = ss.insertSheet('METAS_EQUIPES');
  var eq = [cab].concat(cfg.metas_equipes_padrao);
  shEq.getRange(1, 1, eq.length, cab.length).setValues(eq);
  shEq.getRange(1, 1, 1, cab.length).setFontWeight('bold');

  var cabU = ['USUARIO'].concat(cfg.metas_fields);
  var shUs = ss.insertSheet('METAS_USUARIOS');
  var us = [cabU].concat(cfg.metas_usuarios_padrao);
  shUs.getRange(1, 1, us.length, cabU.length).setValues(us);
  shUs.getRange(1, 1, 1, cabU.length).setFontWeight('bold');

  props.setProperty('SHEET_ID', ss.getId());
  return ss;
}

function arquivoDados_(criarSeFaltar) {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('DATA_FILE_ID');
  if (id) {
    try { return DriveApp.getFileById(id); } catch (e) { if (!criarSeFaltar) throw e; }
  }
  if (!criarSeFaltar) return null;
  var f = DriveApp.createFile(NOME_ARQUIVO_DADOS,
    JSON.stringify({ data: null, updated_at: null, error: 'Aguardando a primeira atualização.' }),
    'application/json');
  props.setProperty('DATA_FILE_ID', f.getId());
  return f;
}

// ===================== Atualização de hora em hora =====================

function atualizarDados() {
  var arquivo = arquivoDados_(true);
  var anterior = {};
  try { anterior = JSON.parse(arquivo.getBlob().getDataAsString('UTF-8')); } catch (e) { anterior = {}; }
  var estado;
  try {
    var data = collectData_(new Date());
    estado = { data: data, updated_at: new Date().toISOString(), error: null };
  } catch (err) {
    // Mantém os últimos dados bons na tela e só registra o erro.
    estado = { data: anterior.data || null, updated_at: anterior.updated_at || null,
      error: String(err && err.message || err) };
    Logger.log('Falha ao atualizar: ' + estado.error);
  }
  arquivo.setContent(JSON.stringify(estado));
  CacheService.getScriptCache().remove('estado');
  if (estado.error) throw new Error(estado.error);
}

// ===================== Web app =====================

function doGet(e) {
  var p = ((e && e.parameter && e.parameter.p) || 'tv').toLowerCase();
  var paginas = { tv: 'Painel CRM — TV', explorar: 'Painel CRM — Explorar', painel: 'Painel CRM' };
  if (!paginas[p]) p = 'tv';
  var html = githubTexto_('apps-script/web/' + p + '.html');
  return HtmlService.createHtmlOutput(html)
    .setTitle(paginas[p])
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/** Chamado pelas telas (google.script.run) — devolve o JSON da última atualização. */
function getDataJson() {
  var cache = CacheService.getScriptCache();
  var txt = cache.get('estado');
  if (txt) return txt;
  var arquivo = arquivoDados_(false);
  txt = arquivo ? arquivo.getBlob().getDataAsString('UTF-8')
    : JSON.stringify({ data: null, updated_at: null, error: 'Rode configurarPainel() primeiro.' });
  if (txt.length < 95000) cache.put('estado', txt, 600);
  return txt;
}

/** Use depois de mudar algo no GitHub, pra não esperar as 6h de cache. */
function limparCache() {
  CacheService.getScriptCache().removeAll(['gh:apps-script/config.json', 'gh:apps-script/web/tv.html',
    'gh:apps-script/web/explorar.html', 'gh:apps-script/web/painel.html', 'estado']);
}

function githubTexto_(caminho) {
  var cache = CacheService.getScriptCache();
  var chave = 'gh:' + caminho;
  var txt = cache.get(chave);
  if (txt) return txt;
  var resp = UrlFetchApp.fetch(GITHUB_RAW + caminho, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) {
    throw new Error('Não consegui baixar ' + caminho + ' do GitHub (HTTP ' + resp.getResponseCode() + ')');
  }
  txt = resp.getContentText('UTF-8');
  if (txt.length < 95000) cache.put(chave, txt, CACHE_SECONDS);
  return txt;
}

var _CONFIG = null;
function getConfig_() {
  if (!_CONFIG) _CONFIG = JSON.parse(githubTexto_('apps-script/config.json'));
  return _CONFIG;
}

// ===================== Cliente do CRM (Odoo JSON-RPC) =====================

var _UID = null;

function rpc_(service, method, args) {
  var resp = UrlFetchApp.fetch(CRM_HOST, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { service: service, method: method, args: args }, id: 1 }),
    muteHttpExceptions: true,
  });
  var code = resp.getResponseCode();
  if (code !== 200) throw new Error('CRM respondeu HTTP ' + code + ': ' + resp.getContentText().slice(0, 300));
  var data = JSON.parse(resp.getContentText('UTF-8'));
  if (data.error) throw new Error('Erro do CRM: ' + JSON.stringify(data.error).slice(0, 500));
  return data.result;
}

function crmCreds_() {
  var props = PropertiesService.getScriptProperties();
  var senha = props.getProperty('CRM_PASSWORD');
  if (!senha) throw new Error('CRM_PASSWORD não configurada nas Propriedades do script.');
  return { login: props.getProperty('CRM_LOGIN') || CRM_LOGIN_PADRAO, senha: senha };
}

function getUid_(force) {
  if (_UID === null || force) {
    var c = crmCreds_();
    _UID = rpc_('common', 'authenticate', [CRM_DB, c.login, c.senha, {}]);
    if (!_UID) throw new Error('Login no CRM recusado (confira CRM_LOGIN / CRM_PASSWORD).');
  }
  return _UID;
}

function executeKw_(model, method, args, kwargs) {
  var senha = crmCreds_().senha;
  var uid = getUid_(false);
  try {
    return rpc_('object', 'execute_kw', [CRM_DB, uid, senha, model, method, args, kwargs || {}]);
  } catch (e) {
    uid = getUid_(true); // sessão pode ter expirado: re-autentica uma vez
    return rpc_('object', 'execute_kw', [CRM_DB, uid, senha, model, method, args, kwargs || {}]);
  }
}

/** search_read paginado (equivale ao limit=0 do app.py, em lotes). */
function searchReadAll_(model, domain, fields) {
  var out = [];
  var offset = 0;
  while (true) {
    var lote = executeKw_(model, 'search_read', [domain], { fields: fields, limit: PAGE_SIZE, offset: offset });
    out = out.concat(lote);
    if (lote.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }
  return out;
}

function readIds_(model, ids, fields) {
  var out = [];
  for (var i = 0; i < ids.length; i += 1000) {
    out = out.concat(executeKw_(model, 'read', [ids.slice(i, i + 1000)], { fields: fields }));
  }
  return out;
}

// ===================== Classificação (classification.py) =====================

function norm_(s) {
  if (s === null || s === undefined || s === false) return '';
  return String(s).trim().toUpperCase().normalize('NFKD').replace(/\p{M}/gu, '').replace(/\s+/g, ' ');
}

function Classificador_(cfg) {
  var self = this;
  this.cats = cfg.revenue_categories;
  this.stageMap = cfg.stage_map;
  this.solic = {}; this.prod = {};
  this.cats.forEach(function (c) {
    self.solic[c] = toSet_(cfg.solic_sets[c]);
    self.prod[c] = toSet_(cfg.prod_sets[c]);
  });
  this.nonMov = toSet_(cfg.non_movement_stages);
  this.miscatBL = toSet_(cfg.miscategorized_as_banda_larga);
}
Classificador_.prototype.classify = function (stageName) {
  return this.stageMap[norm_(stageName)] || { atendido: false, convertido: false, concluido: false, em_tramite: false };
};
Classificador_.prototype.isMovement = function (stageName) {
  return !this.nonMov[norm_(stageName)];
};
Classificador_.prototype.lineMatches = function (categName, reqName, cat, prodName) {
  if (cat === 'BANDA LARGA' && prodName !== null && prodName !== undefined && this.miscatBL[norm_(prodName)]) return false;
  return !!this.prod[cat][norm_(categName)] && !!this.solic[cat][norm_(reqName)];
};

function toSet_(arr) {
  var s = {};
  (arr || []).forEach(function (v) { s[v] = true; });
  return s;
}

// ===================== Metas (metas.py) — da planilha =====================

function Metas_(fields, equipesRows, usuariosRows) {
  this.fields = fields;
  this.eq = this._load(equipesRows);
  this.us = this._load(usuariosRows);
}
Metas_.prototype._load = function (rows) {
  var self = this, out = {};
  (rows || []).forEach(function (r) {
    var key = norm_(r[0]);
    if (!key) return;
    var m = {};
    self.fields.forEach(function (f, i) {
      var v = r[i + 1];
      m[f] = (v === '' || v === null || v === undefined || isNaN(Number(v))) ? 0.0 : Number(v);
    });
    out[key] = m;
  });
  return out;
};
Metas_.prototype.empty = function () {
  var m = {}; this.fields.forEach(function (f) { m[f] = 0; }); return m;
};
Metas_.prototype.equipe = function (nome) {
  var m = this.eq[norm_(nome)]; return m ? copia_(m) : this.empty();
};
Metas_.prototype.usuario = function (nome) {
  var m = this.us[norm_(nome)]; return m ? copia_(m) : this.empty();
};
Metas_.prototype.soma = function (lista) {
  var self = this, t = this.empty();
  lista.forEach(function (m) { self.fields.forEach(function (f) { t[f] += (m[f] || 0); }); });
  return t;
};

function copia_(o) { return JSON.parse(JSON.stringify(o)); }

// ===================== Dias úteis / PDU (dias_uteis.py) =====================

function isoDate_(d) { // d = Date em UTC representando uma data
  return d.toISOString().slice(0, 10);
}

function infoDiasUteis_(hoje, cfg) { // hoje: Date (UTC meia-noite) do dia em Brasília
  var feriados = toSet_(cfg.feriados);
  var ano = hoje.getUTCFullYear(), mes = hoje.getUTCMonth();
  var inicio = new Date(Date.UTC(ano, mes, 1));
  var corte = cfg.corte_mes[ano + '-' + ('0' + (mes + 1)).slice(-2)];
  var fim = corte ? new Date(Date.UTC(ano, mes, corte)) : new Date(Date.UTC(ano, mes + 1, 0));
  function contar(a, b) {
    if (b < a) return 0;
    var n = 0;
    for (var d = new Date(a.getTime()); d <= b; d = new Date(d.getTime() + 86400000)) {
      var wd = d.getUTCDay(); // 0=domingo
      if (wd !== 0 && wd !== 6 && !feriados[isoDate_(d)]) n++;
    }
    return n;
  }
  var totais = contar(inicio, fim);
  var fimDec = hoje < fim ? hoje : fim;
  var decorridos = fimDec >= inicio ? contar(inicio, fimDec) : 0;
  return {
    inicio: isoDate_(inicio), fim: isoDate_(fim),
    dias_uteis_totais: totais, dias_uteis_decorridos: decorridos,
    dias_uteis_restantes: Math.max(0, totais - decorridos),
  };
}

function round2_(x) { return Math.round((x + (x >= 0 ? 1 : -1) * 1e-9) * 100) / 100; }

function calculaPdu_(meta, realizado, info) {
  var totais = info.dias_uteis_totais, restantes = info.dias_uteis_restantes;
  meta = meta || 0; realizado = realizado || 0;
  var falta = Math.max(0.0, meta - realizado);
  var nec;
  if (restantes > 0) nec = round2_(falta / restantes);
  else if (falta > 0) nec = round2_(falta);
  else nec = 0.0;
  return { pdu_inicial: totais ? round2_(meta / totais) : null, pdu_necessario: nec, falta: round2_(falta) };
}

// ===================== Hierarquia (hierarchy.py) =====================

function buildUserIdMap_(cfg) {
  var byLogin = cfg.hierarchy_by_login;
  var logins = Object.keys(byLogin);
  var users = searchReadAll_('res.users', [['login', 'in', logins]], ['id', 'login']);
  var map = {};
  users.forEach(function (u) { if (byLogin[u.login]) map[u.id] = byLogin[u.login]; });
  return map;
}

// ===================== Cálculo (app.py) =====================

function newBucket_(cats) {
  var rev = {};
  cats.forEach(function (c) { rev[c] = { qtd: 0, receita: 0.0 }; });
  return {
    total: 0, atendido: 0, convertido: 0, proposta_enviada: 0,
    aceite_enviado: 0, proposta_recusada: 0, concluido: 0, em_tramite: 0,
    movimentacoes: 0,
    receita_total_status: { concluido: 0.0, em_tramite: 0.0 },
    revenue: rev,
  };
}

function addLead_(b, stageName, f) {
  b.total += 1;
  if (f.atendido) b.atendido += 1;
  if (f.convertido) b.convertido += 1;
  if (f.concluido) b.concluido += 1;
  if (f.em_tramite) b.em_tramite += 1;
  var s = stageName ? String(stageName).trim().toUpperCase() : '';
  if (s === 'PROPOSTA ENVIADA') b.proposta_enviada += 1;
  if (s === 'ACEITE ENVIADO') b.aceite_enviado += 1;
  if (s === 'PROPOSTA RECUSADA') b.proposta_recusada += 1;
}

function m2o_(v, i) { return (v && v !== false) ? v[i] : null; } // many2one [id, nome]

function fmtOdoo_(d) { // 'YYYY-MM-DD HH:MM:SS' em UTC
  return d.toISOString().slice(0, 19).replace('T', ' ');
}

function sortedKeys_(o) { return Object.keys(o).sort(); }

function stableSortDesc_(arr, keyFn) {
  return arr.map(function (v, i) { return [v, i]; })
    .sort(function (a, b) { return (keyFn(b[0]) - keyFn(a[0])) || (a[1] - b[1]); })
    .map(function (x) { return x[0]; });
}

function computePeriodMetrics_(ctx, startDt, label, forceOrders, diasInfo) {
  var cfg = ctx.cfg, cls = ctx.cls, metas = ctx.metas, uidMap = ctx.uidMap, cats = cls.cats;
  var startStr = fmtOdoo_(startDt);
  forceOrders = forceOrders || {};
  var forceList = Object.keys(forceOrders).sort();
  var excluidosPv = toSet_(cfg.excluded_from_pv_total);
  var tv = cfg.tv;

  var root = newBucket_(cats);
  var pvTree = {};
  var pvOrdem = [];
  var leadsFora = 0;

  function hierarchyBuckets(userId) {
    var info = userId ? uidMap[userId] : null;
    if (!info) return null;
    if (!pvTree[info.pv]) { pvTree[info.pv] = { metrics: newBucket_(cats), supervisors: {}, supOrdem: [] }; pvOrdem.push(info.pv); }
    var pvNode = pvTree[info.pv];
    if (info.so_resultado_do_pv) return [pvNode.metrics];
    var sup = info.supervisor || '(sem supervisor)';
    if (!pvNode.supervisors[sup]) {
      pvNode.supervisors[sup] = { metrics: newBucket_(cats), consultores: {}, consOrdem: [], equipe: info.equipe, consultores_info: {} };
      pvNode.supOrdem.push(sup);
    }
    var supNode = pvNode.supervisors[sup];
    if (!supNode.consultores[info.nome]) { supNode.consultores[info.nome] = newBucket_(cats); supNode.consOrdem.push(info.nome); }
    supNode.consultores_info[info.nome] = info;
    var cons = supNode.consultores[info.nome];
    if (info.conta_no_pv === false) return [supNode.metrics, cons];
    return [pvNode.metrics, supNode.metrics, cons];
  }

  // ---------- Leads do período, por etapa ----------
  var leads = searchReadAll_('crm.lead', [['create_date', '>=', startStr]], ['stage_id', 'team_id', 'user_id']);
  var teams = {}, teamOrdem = [];
  leads.forEach(function (l) {
    var stageName = m2o_(l.stage_id, 1);
    var f = cls.classify(stageName);
    addLead_(root, stageName, f);
    var teamName = m2o_(l.team_id, 1) || '(sem equipe)';
    if (!teams[teamName]) { teams[teamName] = { total: 0, atendido: 0, convertido: 0 }; teamOrdem.push(teamName); }
    var t = teams[teamName];
    t.total += 1;
    if (f.atendido) t.atendido += 1;
    if (f.convertido) t.convertido += 1;
    var bs = hierarchyBuckets(m2o_(l.user_id, 0));
    if (!bs) { leadsFora += 1; return; }
    bs.forEach(function (b) { addLead_(b, stageName, f); });
  });
  var teamRanking = stableSortDesc_(teamOrdem.map(function (k) {
    return { equipe: k, total: teams[k].total, atendido: teams[k].atendido, convertido: teams[k].convertido };
  }), function (x) { return x.convertido; }).slice(0, 20);

  // ---------- Receita do período (linhas de pedido) ----------
  var linesDomain = [['create_date', '>=', startStr]];
  if (forceList.length) linesDomain = ['|', ['create_date', '>=', startStr], ['order_id.name', 'in', forceList]];
  var lines = searchReadAll_('sale.order.line', linesDomain,
    ['product_id', 'request_type_id', 'price_total', 'salesman_id', 'order_id']);

  var prodIds = uniqSorted_(lines.map(function (r) { return m2o_(r.product_id, 0); }));
  var prodCateg = {};
  if (prodIds.length) {
    readIds_('product.product', prodIds, ['id', 'categ_id']).forEach(function (p) { prodCateg[p.id] = m2o_(p.categ_id, 1); });
  }

  // Só conta receita de pedido cujo lead de origem esteja em CONCLUIDO ou EM TRAMITE.
  var orderIds = uniqSorted_(lines.map(function (r) { return m2o_(r.order_id, 0); }));
  var leadStageByOrder = {};
  if (orderIds.length) {
    try {
      var orders = readIds_('sale.order', orderIds, ['id', 'opportunity_id']);
      var leadIds = uniqSorted_(orders.map(function (o) { return m2o_(o.opportunity_id, 0); }));
      var leadStage = {};
      if (leadIds.length) {
        readIds_('crm.lead', leadIds, ['id', 'stage_id']).forEach(function (l) { leadStage[l.id] = m2o_(l.stage_id, 1); });
      }
      orders.forEach(function (o) {
        var opp = m2o_(o.opportunity_id, 0);
        leadStageByOrder[o.id] = opp ? (leadStage[opp] === undefined ? null : leadStage[opp]) : null;
      });
    } catch (e) {
      Logger.log('Não foi possível ligar pedidos ao lead de origem: ' + e);
    }
  }

  var pedidosForcadosCount = 0;
  lines.forEach(function (r) {
    var orderId = m2o_(r.order_id, 0);
    var stageLead = leadStageByOrder[orderId];
    var fl = cls.classify(stageLead === undefined ? null : stageLead);
    if (!(fl.concluido || fl.em_tramite)) return;
    var orderName = r.order_id ? String(r.order_id[1]).trim().toUpperCase() : null;
    if (orderName && forceOrders[orderName]) pedidosForcadosCount += 1;
    var req = m2o_(r.request_type_id, 1);
    var pid = m2o_(r.product_id, 0);
    var categ = pid !== null && prodCateg[pid] !== undefined ? prodCateg[pid] : null;
    var prodName = m2o_(r.product_id, 1);
    var price = r.price_total || 0.0;
    var bs = hierarchyBuckets(m2o_(r.salesman_id, 0));
    var statusKey = fl.concluido ? 'concluido' : 'em_tramite';
    cats.forEach(function (cat) {
      if (!cls.lineMatches(categ, req, cat, prodName)) return;
      root.revenue[cat].qtd += 1;
      root.revenue[cat].receita += price;
      if (cat === 'RECEITA TOTAL') root.receita_total_status[statusKey] += price;
      if (bs) bs.forEach(function (b) {
        b.revenue[cat].qtd += 1;
        b.revenue[cat].receita += price;
        if (cat === 'RECEITA TOTAL') b.receita_total_status[statusKey] += price;
      });
    });
  });

  function roundRev(b) {
    cats.forEach(function (c) { b.revenue[c] = { qtd: b.revenue[c].qtd, receita: round2_(b.revenue[c].receita) }; });
    b.receita_total_status = { concluido: round2_(b.receita_total_status.concluido), em_tramite: round2_(b.receita_total_status.em_tramite) };
  }
  roundRev(root);

  // ---------- Movimentações de etapa no período ----------
  var mv = searchReadAll_('mail.tracking.value',
    [['field_id', '=', STAGE_TRACKING_FIELD_ID], ['create_date', '>=', startStr]], ['create_uid', 'new_value_char']);
  var sysIds = toSet_(SYSTEM_USER_IDS);
  var mvCounts = {}, mvOrdem = [];
  mv.forEach(function (r) {
    if (!cls.isMovement(r.new_value_char === false ? null : r.new_value_char)) return;
    root.movimentacoes += 1;
    var cu = r.create_uid;
    if (!cu) return;
    if (!sysIds[cu[0]]) {
      if (!mvCounts[cu[0]]) { mvCounts[cu[0]] = { consultor: cu[1], movimentacoes: 0 }; mvOrdem.push(cu[0]); }
      mvCounts[cu[0]].movimentacoes += 1;
    }
    var bs = hierarchyBuckets(cu[0]);
    if (bs) bs.forEach(function (b) { b.movimentacoes += 1; });
  });
  var topConsultores = stableSortDesc_(mvOrdem.map(function (k) { return mvCounts[k]; }),
    function (x) { return x.movimentacoes; }).slice(0, 15);

  // ---------- Árvore final PV → Equipe → Consultor ----------
  function pduCom(meta, bucket) {
    if (!diasInfo) return null;
    return calculaPdu_(meta.RECEITA_TOTAL, bucket.revenue['RECEITA TOTAL'].receita, diasInfo);
  }
  function fotoDe(info) { return info && info.foto ? info.foto : null; }

  var hierarchy = [];
  pvOrdem.slice().sort().forEach(function (pv) {
    var pvNode = pvTree[pv];
    roundRev(pvNode.metrics);
    var supervisors = [], pvMetas = [];
    var supsOrd = stableSortDesc_(pvNode.supOrdem, function (s) { return pvNode.supervisors[s].metrics.convertido; });
    supsOrd.forEach(function (sup) {
      var supNode = pvNode.supervisors[sup];
      roundRev(supNode.metrics);
      var supMeta = metas.equipe(supNode.equipe);
      if (!excluidosPv[supNode.equipe]) pvMetas.push(supMeta);
      var consultores = [];
      var consOrd = stableSortDesc_(supNode.consOrdem, function (n) { return supNode.consultores[n].convertido; });
      consOrd.forEach(function (nome) {
        var mb = supNode.consultores[nome];
        roundRev(mb);
        var consMeta = metas.usuario(nome);
        var info = supNode.consultores_info[nome] || {};
        var temPlano = Object.keys(consMeta).some(function (k) { return consMeta[k] > 0; });
        var item = {
          nome: nome, nome_exibicao: info.nome_exibicao || nome,
          foto: fotoDe(info),
          exibir_tv: !!(temPlano && !info.ocultar_da_tv),
          meta: consMeta, pdu: pduCom(consMeta, mb),
        };
        Object.keys(mb).forEach(function (k) { item[k] = mb[k]; });
        consultores.push(item);
      });
      var eqCfg = tv.EQUIPES[supNode.equipe] || {};
      var lideres = eqCfg.lideres || [];
      var s = {
        supervisor: sup, meta: supMeta, pdu: pduCom(supMeta, supNode.metrics),
        lideres: lideres, foto: (lideres[0] || {}).foto || null,
      };
      Object.keys(supNode.metrics).forEach(function (k) { s[k] = supNode.metrics[k]; });
      s.consultores = consultores;
      supervisors.push(s);
    });
    var pvMeta = metas.soma(pvMetas);
    var node = {
      pv: pv, meta: pvMeta, pdu: pduCom(pvMeta, pvNode.metrics),
      foto: tv.PV_FOTOS[pv] || null,
      somente_visao_geral: (tv.PV_SOMENTE_VISAO_GERAL || []).indexOf(pv) >= 0,
    };
    Object.keys(pvNode.metrics).forEach(function (k) { node[k] = pvNode.metrics[k]; });
    node.supervisors = supervisors;
    hierarchy.push(node);
  });

  var rootMeta = metas.soma(hierarchy.map(function (p) { return p.meta; }));
  return {
    label: label, root: root, root_meta: rootMeta, root_pdu: pduCom(rootMeta, root),
    dias_uteis: diasInfo || null, team_ranking: teamRanking, top_consultores: topConsultores,
    hierarchy: hierarchy, leads_fora_do_escopo: leadsFora, pedidos_mes_atual_count: pedidosForcadosCount,
  };
}

function uniqSorted_(arr) {
  var s = {};
  arr.forEach(function (v) { if (v !== null && v !== undefined && v !== false) s[v] = true; });
  return Object.keys(s).map(Number).sort(function (a, b) { return a - b; });
}

function lerPlanilha_() {
  var ss = abrirPlanilha_(false);
  function valores(nome) {
    var sh = ss.getSheetByName(nome);
    if (!sh || sh.getLastRow() < 2) return [];
    return sh.getRange(2, 1, sh.getLastRow() - 1, Math.max(1, sh.getLastColumn())).getValues();
  }
  var pedidos = {};
  valores('PEDIDOS_MES').forEach(function (r) {
    var p = String(r[0] || '').trim().toUpperCase();
    if (p) pedidos[p] = true;
  });
  return { pedidos: pedidos, metasEquipes: valores('METAS_EQUIPES'), metasUsuarios: valores('METAS_USUARIOS') };
}

/** Monta o mesmo JSON que o /api/data do app.py devolvia em "data". */
function collectData_(now, planilha) {
  var cfg = getConfig_();
  planilha = planilha || lerPlanilha_();
  var ctx = {
    cfg: cfg,
    cls: new Classificador_(cfg),
    metas: new Metas_(cfg.metas_fields, planilha.metasEquipes, planilha.metasUsuarios),
  };
  ctx.uidMap = buildUserIdMap_(cfg);

  var monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  var lastNStart = new Date(now.getTime() - LAST_N_DAYS * 86400000);
  var brt = new Date(now.getTime() - 3 * 3600000);
  var hojeBr = new Date(Date.UTC(brt.getUTCFullYear(), brt.getUTCMonth(), brt.getUTCDate()));
  var dias = infoDiasUteis_(hojeBr, cfg);

  function ddmm(d) { return ('0' + d.getUTCDate()).slice(-2) + '/' + ('0' + (d.getUTCMonth() + 1)).slice(-2); }
  var mesLabel = ('0' + (now.getUTCMonth() + 1)).slice(-2) + '/' + now.getUTCFullYear();

  var month = computePeriodMetrics_(ctx, monthStart, mesLabel, planilha.pedidos, dias);
  var lastN = computePeriodMetrics_(ctx, lastNStart,
    'Últimos ' + LAST_N_DAYS + 'd (' + ddmm(lastNStart) + ' a ' + ddmm(now) + ')', null, null);
  return { periods: { month: month, last_n: lastN } };
}

/** Teste rápido: roda a coleta e mostra um resumo no log, sem gravar nada. */
function testarConexao() {
  var uid = getUid_(true);
  Logger.log('Login no CRM OK (uid ' + uid + ').');
  var d = collectData_(new Date());
  var r = d.periods.month.root;
  Logger.log('Mês ' + d.periods.month.label + ': ' + r.total + ' leads, receita total R$ ' +
    r.revenue['RECEITA TOTAL'].receita + ', pedidos da lista que entraram: ' + d.periods.month.pedidos_mes_atual_count);
}
