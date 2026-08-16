// ============================================
// CONFIGURATION
// ============================================
const API_BASE_URL = (window.__CONFIG__?.API) || (window.location.origin.includes('ct.ws') ? 'https://botiqoption-4.onrender.com' : (window.location.protocol.startsWith('http') ? window.location.origin : 'https://botiqoption-4.onrender.com'));
let accountType = sessionStorage.getItem('accountType') || "PRACTICE";
let symbolsCache = [];
let strategiesCache = [];
let socket = null;
let wsConnected = false;
let chart = null;
let candleSeries = null;
let lastCandleTime = 0;
// Establecer timeframe por defecto acorde al botón activo en el HTML (5m = 300s)
let currentTimeframe = 300;
let lastSubscribedSymbol = "";
let lastSubscribedTimeframe = null;

const $ = (id) => document.getElementById(id);
const MAX_LOG_LINES = 250;
// Current asset filter (ALL, NORMAL, OTC). Used when rendering the assets grid.
let assetFilter = 'ALL';

// Bot stats (updated live from WebSocket events and /api/bot_status)
let botStats = { ops: 0, wins: 0, losses: 0, profit: 0 };
let botStatusInterval = null;

function updateStatCards() {
  const { ops, wins, losses, profit } = botStats;
  const rate = ops > 0 ? Math.round((wins / ops) * 100) : 0;

  const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
  set('statOps',     ops);
  set('statWins',    wins);
  set('statLosses',  losses);
  set('statWinRate', `${rate}%`);
  set('statProfit',  `$${profit >= 0 ? '+' : ''}${profit.toFixed(2)}`);

  const profitEl = $('statProfit');
  if (profitEl) {
    profitEl.style.color = profit >= 0 ? 'var(--success)' : 'var(--danger)';
  }
}
/**
 * ✅ NUEVO: Limpia la sesión y redirige al login
 * Se llama cuando detectamos una sesión expirada o inválida
 */
function handleSessionExpired(reason = "Sesión expirada") {
  console.warn(`⚠️ ${reason} - limpiando y redirigiendo al login`);
  
  // Limpiar almacenamiento local
  localStorage.clear();
  sessionStorage.clear();
  
  // Desconectar WebSocket si existe
  if (socket) {
    socket.disconnect();
    socket = null;
  }
  
  // Mostrar mensaje al usuario
  toast(reason);
  logLine(`🔒 ${reason}`, "warn");
  
  // Redirigir al login después de un breve delay
  setTimeout(() => {
    window.location.href = "index.html";
  }, 500);
}

// ============================================
// UTILITY FUNCTIONS
// ============================================
function toast(msg) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2500);
}

function logLine(msg, kind = "") {
  const box = $("log");
  if (!box) return;

  const d = new Date();
  const time = d.toLocaleTimeString();
  const div = document.createElement("div");
  div.className = `log-line ${kind}`;
  div.innerHTML = `<span class="timestamp">${time}</span>${escapeHtml(msg)}`;
  box.appendChild(div);

  // Limit log lines
  while (box.children.length > MAX_LOG_LINES) {
    box.removeChild(box.firstChild);
  }

  box.scrollTop = box.scrollHeight;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function showLoading() {
  $("loadingOverlay")?.classList.add("show");
}

function hideLoading() {
  $("loadingOverlay")?.classList.remove("show");
}

// ============================================
// SESSION MANAGEMENT
// ============================================
/**
 * Limpia la sesión y redirige al login
 * Se llama cuando detectamos una sesión expirada o inválida
 */


// ============================================
// API FUNCTIONS (CORREGIDO)
// ============================================
/**
 * Función mejorada para hacer peticiones al API
 * - NO envía Content-Type en GET sin body (evita preflight OPTIONS)
 * - Maneja automáticamente 401 (sesión expirada)
 * - Incluye credenciales (cookies)
 */
/**
 * ✅ MEJORADO: Función para hacer peticiones al API
 * 
 * Mejoras:
 * - NO envía Content-Type en GET sin body (evita preflight OPTIONS)
 * - Maneja automáticamente 401 (sesión expirada)
 * - Limpia estado y redirige al login en caso de sesión inválida
 */
async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const userId = sessionStorage.getItem('userId') || (sessionStorage.getItem('userEmail') ? sessionStorage.getItem('userEmail').split('@')[0] : '');
  
  // Configuración base
  const fetchOptions = {
    credentials: "include",  // ✅ Enviar cookies
    mode: "cors",
    ...options,
    headers: {
      ...(userId ? { "X-User-Id": userId } : {}),
      ...(options.headers || {})
    }
  };

  // ✅ CRÍTICO: SOLO agregar Content-Type si hay body
  if (options.body) {
    fetchOptions.headers["Content-Type"] = "application/json";
    
    // Convertir body a JSON si es un objeto
    if (typeof options.body === 'object') {
      fetchOptions.body = JSON.stringify(options.body);
    }
  }

  try {
    const res = await fetch(url, fetchOptions);
    
    // 🔥 MANEJO CRÍTICO: 401 = sesión expirada o inválida
    if (res.status === 401) {
      console.warn("⚠️ Sesión expirada o inválida - redirigiendo al login");
      
      // Limpiar almacenamiento
      localStorage.clear();
      sessionStorage.clear();
      
      // Desconectar WebSocket si existe
      if (socket) {
        socket.disconnect();
        socket = null;
      }
      
      // Mostrar mensaje
      logLine("🔒 Sesión expirada - redirigiendo al login", "warn");
      toast("Sesión expirada");
      
      // Redirigir al login después de un breve delay
      setTimeout(() => {
        window.location.href = "index.html";
      }, 500);
      
      // ✅ CORRECCIÓN CRÍTICA: NO devolver promesa infinita
      // Lanzar error para que el caller pueda manejarlo
      throw new Error('SESSION_EXPIRED');
    }


    // ✅ 503: sesión válida pero servicio/bridge (IQ) no disponible
    // En este caso devolvemos el JSON para que la UI lo maneje (no es un logout)
    if (res.status === 503) {
      const contentType503 = res.headers.get("content-type") || "";
      if (contentType503.includes("application/json")) {
        return await res.json();
      }
      return { authenticated: true, api_connected: false, error: "Servicio no disponible" };
    }

    // Otros errores HTTP
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${res.status}`);
    }

    // Parsear JSON si la respuesta tiene contenido
    const contentType = res.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
      return await res.json();
    }
    
    return res;
  } catch (error) {
    // Si el error es de red (no de HTTP), registrarlo
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      console.error(`Error de red en ${endpoint}:`, error);
      logLine(`🌐 Error de red: ${error.message}`, "bad");
    } else {
      console.error(`Error en ${endpoint}:`, error);
    }
    throw error;
  }
}
// ============================================
// NORMALIZATION FUNCTIONS
// ============================================
function normalizeSymbols(payload) {
  const arr = Array.isArray(payload)
    ? payload
    : (payload?.actives || payload?.symbols || payload?.data || []);

  return arr.map(x => {
    if (typeof x === "string") {
      const u = x.toUpperCase();
      const isOtc = u.includes("OTC");
      return {
        symbol: x,
        name: x,
        otc: isOtc,
        category: "",
        payout: null,
        available_24_7: isOtc
      };
    }

    const sym = String(x.symbol || x.name || x.ticker || "").trim();
    const nm = String(x.name || x.symbol || sym).trim();
    const u = sym.toUpperCase();
    const otc = Boolean(
      x.otc ?? x.is_otc ?? x.type === "OTC" ?? u.includes("OTC") ?? u.endsWith("-OTC")
    );

    const category = x.category || x.asset_class || x.group || "";
    const payout = (x.payout !== undefined && x.payout !== null) ? Number(x.payout) : null;
    const available_24_7 = Boolean(x.available_24_7 ?? x.is_24_7 ?? otc);
    const practice_only = u.includes("-OP");

    return {
      symbol: sym,
      name: nm,
      otc,
      category,
      payout: Number.isFinite(payout) ? payout : null,
      available_24_7,
      practice_only,
      id: x.id ?? x.active_id ?? x.asset_id ?? null,
    };
  }).filter(x => x.symbol);
}

function normalizeStrategies(payload) {
  const arr = Array.isArray(payload) ? payload : (payload?.strategies || payload?.data || []);

  return arr.map((x, idx) => {
    if (typeof x === "string") {
      return {
        id: `strategy_${idx + 1}`,
        name: x,
        risk: "",
        description: ""
      };
    }

    const id = x.id ?? x.key ?? x.strategy_id ?? x.slug ?? `strategy_${idx + 1}`;
    return {
      id: String(id),
      name: x.name ?? x.strategy ?? `Estrategia ${idx + 1}`,
      risk: x.risk ?? x.level ?? x.risk_level ?? "",
      description: x.description ?? x.desc ?? ""
    };
  });
}

// ============================================
// ASSETS GRID RENDERING
// ============================================
/**
 * Construye y muestra las tarjetas de activos en el grid (#assetsGrid) basándose
 * en la lista `symbolsCache`, el filtro `assetFilter` y el valor de búsqueda en
 * el input #assetSearch. Cada tarjeta incluye badges indicando la categoría,
 * si es OTC o normal, y el payout si está disponible. Al hacer clic en una
 * tarjeta se selecciona el activo y se suscribe al stream de velas.
 */
function renderAssetsGrid() {
  const grid = $("assetsGrid");
  if (!grid) return;

  // Obtener término de búsqueda en mayúsculas para comparación
  const searchInput = $("assetSearch");
  const searchTerm = searchInput ? searchInput.value.trim().toUpperCase() : "";

  // Limpiar grid existente
  grid.innerHTML = "";

  // Filtrar y ordenar activos
  symbolsCache.forEach(sym => {
    const symbolUpper = sym.symbol.toUpperCase();
    const nameUpper = (sym.name || sym.symbol).toUpperCase();
    // Filtrar por búsqueda
    if (searchTerm && !symbolUpper.includes(searchTerm) && !nameUpper.includes(searchTerm)) {
      return;
    }
    // Filtrar por tipo
    const isOtc = !!sym.otc;
    let show = false;
    if (assetFilter === 'ALL') {
      show = true;
    } else if (assetFilter === 'OTC') {
      show = isOtc;
    } else if (assetFilter === 'NORMAL' || assetFilter === 'REGULAR') {
      show = !isOtc;
    }
    if (!show) {
      return;
    }
    // Crear tarjeta
    const card = document.createElement('div');
    card.className = 'asset-card';
    card.dataset.symbol = sym.symbol;
    card.dataset.otc = isOtc;
    card.dataset.category = sym.category || '';
    card.dataset.payout = sym.payout != null ? String(sym.payout) : '';

    // Construir contenido
    const badges = [];
    if (sym.category) {
      badges.push(`<span class="badge cat">${escapeHtml(sym.category)}</span>`);
    }
    // Si es práctica, categoría “practice” no se refleja en los datos; se decide en runtime
    if (isOtc) {
      badges.push('<span class="badge otc">OTC</span>');
    } else {
      badges.push('<span class="badge live">Normal</span>');
    }
    if (sym.payout !== undefined && sym.payout !== null) {
      badges.push(`<span class="badge payout">${Number(sym.payout)}%</span>`);
    }

    card.innerHTML = `
      <div class="asset-symbol">${escapeHtml(sym.symbol)}</div>
      <div class="asset-badges">${badges.join(' ')}</div>
    `;

    card.addEventListener('click', () => {
      selectAssetCard(sym.symbol);
    });

    // Resaltar la tarjeta actualmente seleccionada
    if (sym.symbol === lastSubscribedSymbol) {
      card.classList.add('selected');
    }
    grid.appendChild(card);
  });
  // Si no hay activos que mostrar, mostrar placeholder
  if (!grid.hasChildNodes()) {
    const placeholder = document.createElement('div');
    placeholder.className = 'loading-placeholder';
    placeholder.innerHTML = '<div class="loading-spinner"></div><span>No hay activos para mostrar</span>';
    grid.appendChild(placeholder);
  }
}

/**
 * Selecciona un activo desde una tarjeta de la cuadrícula. Actualiza el
 * select #symbol, suscribe al stream de velas, actualiza la UI de selección y
 * marca la tarjeta como seleccionada.
 * @param {string} symbol El símbolo que se va a seleccionar
 */
function selectAssetCard(symbol) {
  // Actualizar el select subyacente para compatibilidad con lógica existente
  const select = $("symbol");
  if (select) {
    select.value = symbol;
    // Disparar evento de cambio manualmente
    const event = new Event('change', { bubbles: true });
    select.dispatchEvent(event);
  }
  // Actualizar clase 'selected' en tarjetas
  const grid = $("assetsGrid");
  if (grid) {
    Array.from(grid.querySelectorAll('.asset-card')).forEach(card => {
      if (card.dataset.symbol === symbol) {
        card.classList.add('selected');
      } else {
        card.classList.remove('selected');
      }
    });
  }
}

// ============================================
// UI UPDATE FUNCTIONS
// ============================================
function updateConnectionStatus(status) {
  const statusEl = $("connectionStatus");
  if (!statusEl) return;

  const statusMap = {
    connected: { text: "Conectado", class: "connected" },
    disconnected: { text: "Desconectado", class: "disconnected" },
    connecting: { text: "Conectando...", class: "connecting" }
  };

  const config = statusMap[status] || statusMap.connecting;
  statusEl.className = `status-pill ${config.class}`;
  statusEl.querySelector("span").textContent = config.text;
}

function updateWebSocketStatus(connected) {
  const wsEl = $("wsStatus");
  if (!wsEl) return;

  wsEl.className = connected ? "ws-badge connected" : "ws-badge";
}

function updateBalance(balance) {
  // Actualiza el elemento de balance antiguo (id="balance") si existe
  const balanceEl = $("balance");
  const headerBalanceEl = $("headerBalance");

  // Helper para actualizar un nodo con un número o texto
  const setAmount = (el, amount) => {
    if (!el) return;
    // Si el elemento contiene un span.amount, solo actualiza ese span
    const amountSpan = el.querySelector('.amount');
    if (amountSpan) {
      amountSpan.textContent = Number(amount).toFixed(2);
    } else {
      // Caso antiguo: poner directamente el texto completo
      el.textContent = `$ ${Number(amount).toFixed(2)}`;
    }
  };

  if (balance !== null && balance !== undefined) {
    if (balanceEl) {
      setAmount(balanceEl, balance);
      balanceEl.classList.remove('balance-cached');
    }
    if (headerBalanceEl) {
      setAmount(headerBalanceEl, balance);
      headerBalanceEl.classList.remove('balance-cached');
    }
  } else {
    // Intentar usar balance guardado antes de mostrar $0.00
    const lastBalance = sessionStorage.getItem('lastKnownBalance');
    if (lastBalance) {
      const lb = parseFloat(lastBalance);
      if (balanceEl) {
        setAmount(balanceEl, lb);
        balanceEl.classList.add('balance-cached');
      }
      if (headerBalanceEl) {
        setAmount(headerBalanceEl, lb);
        headerBalanceEl.classList.add('balance-cached');
      }
    } else {
      if (balanceEl) {
        if (balanceEl.querySelector('.amount')) {
          setAmount(balanceEl, 0);
        } else {
          balanceEl.textContent = "$ 0.00";
        }
        balanceEl.classList.remove('balance-cached');
      }
      if (headerBalanceEl) {
        setAmount(headerBalanceEl, 0);
        headerBalanceEl.classList.remove('balance-cached');
      }
    }
  }
}

function updateBotControls(isRunning) {
  const startBtn = $("btnStartBot");
  const stopBtn = $("btnStopBot");
  const statusBadge = $("botStatusBadge");

  if (!startBtn || !stopBtn) return;

  if (isRunning) {
    startBtn.disabled = true;
    startBtn.classList.add("hidden");
    stopBtn.disabled = false;
    stopBtn.classList.remove("hidden");
    if (statusBadge) {
      statusBadge.textContent = "● ACTIVO";
      statusBadge.className = "status-badge active";
    }
  } else {
    startBtn.disabled = false;
    startBtn.classList.remove("hidden");
    stopBtn.disabled = true;
    stopBtn.classList.add("hidden");
    if (statusBadge) {
      statusBadge.textContent = "● DETENIDO";
      statusBadge.className = "status-badge inactive";
    }
  }
}

// ============================================
// DATA LOADING FUNCTIONS
// ============================================
async function loadBalance() {
  try {
    const data = await apiFetch("/api/balance");

    // ✅ DEBUG: Ver qué está recibiendo (comentar en producción)
    // console.log('📊 Balance response:', data);

    // Verificar si IQ está desconectada (503)
    if (data && data.authenticated && !data.api_connected) {
      // ✅ CORREGIDO: NO resetear balance a $0.00, mantener último valor conocido
      logLine(`⚠️ IQ Option temporalmente desconectada: ${data.error || 'Reconectar necesario'}`, "warn");
      
      // Solo mostrar toast si no hay balance previo guardado
      const lastBalance = sessionStorage.getItem('lastKnownBalance');
      if (!lastBalance) {
        toast("IQ Option desconectada");
      } else {
        // Mantener el balance anterior visible
        logLine(`💰 Mostrando último balance conocido: $${parseFloat(lastBalance).toFixed(2)}`, "warn");
      }
      return;
    }

    // Todo OK - actualizar balance
    if (data && data.balance !== null && data.balance !== undefined) {
      updateBalance(data.balance);
      logLine(`💰 Balance: $${data.balance.toFixed(2)}`, "good");
      
      // ✅ Guardar en sessionStorage para persistir
      sessionStorage.setItem('lastKnownBalance', data.balance);
    } else if (data && data.api_connected === true) {
      // API conectada pero balance undefined/null - usar último conocido
      const lastBalance = sessionStorage.getItem('lastKnownBalance');
      if (lastBalance) {
        updateBalance(parseFloat(lastBalance));
        logLine(`💰 Balance (caché): $${parseFloat(lastBalance).toFixed(2)}`, "warn");
      }
    }

  } catch (error) {
    if (error.message === 'SESSION_EXPIRED') {
      // Ya manejado por apiFetch
      return;
    }

    logLine(`⚠️ Error cargando balance: ${error.message}`, "warn");
    
    // ✅ En caso de error, intentar usar balance guardado
    const lastBalance = sessionStorage.getItem('lastKnownBalance');
    if (lastBalance) {
      updateBalance(parseFloat(lastBalance));
      logLine(`💰 Balance (caché por error): $${parseFloat(lastBalance).toFixed(2)}`, "warn");
    }
  }
}

async function loadSymbols() {
  try {
    const data = await apiFetch("/api/symbols");
    if (!data) return; // Ya manejado por apiFetch si es 401
    
    const normalized = normalizeSymbols(data);
    
    symbolsCache = normalized;
    
    const select = $("symbol");
    if (!select) return;

    select.innerHTML = '<option value="">Seleccionar activo...</option>';

    normalized.forEach(sym => {
      const opt = document.createElement("option");
      opt.value = sym.symbol;
      opt.textContent = `${sym.name}${sym.otc ? ' (OTC)' : ''}${sym.payout ? ` - ${sym.payout}%` : ''}`;
      opt.dataset.otc = sym.otc;
      opt.dataset.category = sym.category || "";
      select.appendChild(opt);
    });

    logLine(`📊 ${normalized.length} activos cargados`, "good");

    // Renderizar también el grid de activos para la nueva interfaz
    renderAssetsGrid();
  } catch (error) {
    logLine(`⚠️ Error cargando activos: ${error.message}`, "warn");
  }
}

async function loadStrategies() {
  try {
    const data = await apiFetch("/api/strategies");
    if (!data) return; // Ya manejado por apiFetch si es 401
    
    const normalized = normalizeStrategies(data);
    
    strategiesCache = normalized;
    
    const select = $("strategy");
    if (!select) return;

    select.innerHTML = '<option value="">Seleccionar estrategia...</option>';

    normalized.forEach(strat => {
      const opt = document.createElement("option");
      opt.value = strat.id;
      opt.textContent = `${strat.name}${strat.risk ? ` (${strat.risk})` : ''}`;
      opt.dataset.risk = strat.risk || "";
      select.appendChild(opt);
    });

    logLine(`🎯 ${normalized.length} estrategias cargadas`, "good");
  } catch (error) {
    logLine(`⚠️ Error cargando estrategias: ${error.message}`, "warn");
  }
}

async function loadBotStatus() {
  try {
    const data = await apiFetch("/api/bot_status");
    if (!data) return;

    updateBotControls(!!data.running);

    if (data.running) {
      // Recalcular stats desde historial de operaciones
      const history = data.last_operations || [];
      const ops     = data.operations_count ?? history.length;
      const wins    = history.filter(r => (r.profit ?? r.result ?? 0) > 0).length;
      const losses  = history.filter(r => (r.profit ?? r.result ?? 0) <= 0).length;
      const profit  = typeof data.session_profit === 'number' ? data.session_profit : 0;

      botStats = { ops, wins, losses, profit };
      updateStatCards();

      logLine(`🤖 Bot activo: ${ops} ops | ${wins}W/${losses}L | $${profit.toFixed(2)}`, "good");
    }
  } catch (error) {
    updateBotControls(false);
  }
}

// ============================================
// BOT CONTROL FUNCTIONS
// ============================================
async function startBot() {
  const symbol = $("symbol")?.value;
  const amount = parseFloat($("amount")?.value || 0);
  const strategyId = $("strategy")?.value;
  const maxOps = parseInt($("maxOps")?.value || 0);
  const maxLoss = parseInt($("maxLoss")?.value || 5);

  if (!symbol) {
    toast("Selecciona un activo");
    logLine("❌ No se seleccionó un activo", "bad");
    return;
  }

  if (!amount || amount <= 0) {
    toast("Ingresa un monto válido");
    logLine("❌ Monto inválido", "bad");
    return;
  }

  if (!strategyId) {
    toast("Selecciona una estrategia");
    logLine("❌ No se seleccionó una estrategia", "bad");
    return;
  }

  const useCompound = document.getElementById("useCompound")?.checked ?? false;

  const payload = {
    symbol,
    amount,
    strategy: strategyId,
    account_type: accountType,
    max_operations: maxOps,
    max_loss_operations: maxLoss,
    use_compound: useCompound,
  };

  logLine(`🚀 Iniciando bot con configuración:`, "neutral");
  logLine(`   📊 Activo: ${symbol}`, "neutral");
  logLine(`   💵 Monto: $${amount}`, "neutral");
  logLine(`   🎯 Estrategia: ${strategyId}`, "neutral");
  logLine(`   💰 Interés Compuesto LMTA: ${useCompound ? "✅ ACTIVADO (5 niveles)" : "❌ Desactivado"}`, useCompound ? "good" : "neutral");

  try {
    showLoading();
    const data = await apiFetch("/api/start_bot", {
      method: "POST",
      body: payload
    });

    if (!data) return; // Ya manejado por apiFetch si es 401

    if (data.success) {
      toast("Bot iniciado correctamente");
      logLine("✅ Bot iniciado exitosamente", "good");
      updateBotControls(true);
      
      // Subscribe to candles for selected symbol
      subscribeToSelectedSymbol();
    } else {
      toast(data.error || "Error iniciando bot");
      logLine(`❌ Error: ${data.error || data.detail || 'Desconocido'}`, "bad");
    }
  } catch (error) {
    toast("Error al iniciar bot");
    logLine(`❌ Error iniciando bot: ${error.message}`, "bad");
  } finally {
    hideLoading();
  }
}

async function stopBot() {
  try {
    showLoading();
    const data = await apiFetch("/api/stop_bot", {
      method: "POST"
    });

    if (!data) return; // Ya manejado por apiFetch si es 401

    if (data.success) {
      toast("Bot detenido");
      logLine("🛑 Bot detenido correctamente", "good");
      updateBotControls(false);
      clearInterval(botStatusInterval);
      botStatusInterval = null;

      if (data.final_stats) {
        const fs = data.final_stats;
        logLine(`📊 Estadísticas finales:`, "neutral");
        logLine(`   Operaciones: ${fs.operations_count || 0}`, "neutral");
        logLine(`   Profit: $${fs.session_profit?.toFixed(2) || '0.00'}`, "neutral");
      }
    } else {
      toast(data.error || "Error deteniendo bot");
      logLine(`❌ Error: ${data.error}`, "bad");
    }
  } catch (error) {
    toast("Error al detener bot");
    logLine(`❌ Error deteniendo bot: ${error.message}`, "bad");
  } finally {
    hideLoading();
  }
}

// ============================================
// CHART FUNCTIONS
// ============================================
function initChart() {
  // Usar el nuevo contenedor #chartContainer si existe; de lo contrario #chart
  let container = $("chartContainer");
  if (!container) {
    container = $("chart");
  }
  if (!container) {
    logLine("⚠️ No se encontró contenedor del gráfico", "warn");
    return;
  }

  try {
    chart = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 400,
      layout: {
        background: { color: "#0a0e27" },
        textColor: "#d1d4dc"
      },
      grid: {
        vertLines: { color: "#1e2a4a" },
        horzLines: { color: "#1e2a4a" }
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "#2b3a5f"
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false
      },
      handleScale: {
        mouseWheel: false,
        pinch: true,
        axisPressedMouseMove: true
      }
    });

    candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350"
    });

    // Handle resize
    new ResizeObserver(() => {
      if (chart && container) {
        chart.applyOptions({
          width: container.clientWidth
        });
      }
    }).observe(container);

    logLine("📈 Gráfico inicializado", "good");
  } catch (error) {
    logLine(`❌ Error inicializando gráfico: ${error.message}`, "bad");
  }
}

/**
 * Normaliza cualquier formato de tiempo a Unix timestamp en segundos (número entero).
 * Maneja: número (s o ms), string ISO, objeto {year,month,day}, objeto {$date}, etc.
 */
function toUnixSeconds(t) {
  if (typeof t === 'number') {
    return t > 1e10 ? Math.floor(t / 1000) : Math.floor(t);
  }
  if (typeof t === 'string') {
    const ms = Date.parse(t);
    return isNaN(ms) ? 0 : Math.floor(ms / 1000);
  }
  if (t && typeof t === 'object') {
    if (t.year !== undefined) {
      return Math.floor(new Date(t.year, (t.month || 1) - 1, t.day || 1).getTime() / 1000);
    }
    if (t.$date !== undefined) {
      return Math.floor(new Date(t.$date).getTime() / 1000);
    }
    const ms = new Date(t).getTime();
    return isNaN(ms) ? 0 : Math.floor(ms / 1000);
  }
  return 0;
}

// Local candle store: time(s) -> {time,open,high,low,close}
let candlesMap = new Map();
let candlesMaxTime = 0;
let bulkUpdateTimer = null;

/**
 * Programa un setData() completo con todas las velas ordenadas.
 * Se hace con debounce para agrupar la ráfaga inicial del backend.
 */
function scheduleBulkUpdate() {
  if (bulkUpdateTimer) clearTimeout(bulkUpdateTimer);
  bulkUpdateTimer = setTimeout(() => {
    bulkUpdateTimer = null;
    if (!candleSeries || candlesMap.size === 0) return;
    try {
      const sorted = Array.from(candlesMap.values()).sort((a, b) => a.time - b.time);
      candleSeries.setData(sorted);
    } catch (e) {
      console.error('Chart setData error:', e);
    }
  }, 250);
}

/**
 * Limpia el almacén local de velas (al cambiar de símbolo/timeframe).
 */
function resetCandlesStore() {
  candlesMap.clear();
  candlesMaxTime = 0;
  if (bulkUpdateTimer) { clearTimeout(bulkUpdateTimer); bulkUpdateTimer = null; }
}

function updateChart(candle) {
  if (!candleSeries) return;

  const t = toUnixSeconds(candle.time);
  if (!t) return;

  const c = {
    time:  t,
    open:  Number(candle.open),
    high:  Number(candle.high),
    low:   Number(candle.low),
    close: Number(candle.close)
  };

  // Guardar / actualizar en el mapa local
  candlesMap.set(t, c);

  if (t > candlesMaxTime) {
    // Nueva vela más reciente: actualizar el tracker
    candlesMaxTime = t;
    // Si el gráfico ya tiene datos anteriores, update() es seguro
    if (candlesMap.size > 1) {
      try {
        candleSeries.update(c);
        return; // éxito, no necesitamos setData
      } catch (_) {
        // Falló (orden roto), caemos a setData
      }
    }
    scheduleBulkUpdate();
  } else {
    // Vela histórica / actualización intra-vela de timestamp antiguo
    // No llamamos update() (rompería el orden); programamos setData
    scheduleBulkUpdate();
  }
}

// ============================================
// WEBSOCKET FUNCTIONS
// ============================================
function initWebSocket() {
  try {
    logLine("🔌 Conectando WebSocket...", "neutral");
    
    const userId = sessionStorage.getItem('userId') || (sessionStorage.getItem('userEmail') ? sessionStorage.getItem('userEmail').split('@')[0] : '');
    const targetUrl = API_BASE_URL || window.location.origin;
    socket = io(targetUrl, {
      transports: ['websocket', 'polling'],
      withCredentials: true,
      auth: { user_id: userId },
      query: { user_id: userId },
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5
    });

    socket.on('connect', () => {
      wsConnected = true;
      updateWebSocketStatus(true);
      logLine("✅ WebSocket conectado", "good");
      toast("WebSocket conectado");
      
      // Resubscribe if there was a symbol
      if (lastSubscribedSymbol) {
        subscribeToCandles(lastSubscribedSymbol, lastSubscribedTimeframe || currentTimeframe);
      }

      // ✅ NUEVO: Cuando la conexión WebSocket esté lista, volver a cargar balance, símbolos y estado del bot.
      // Esto evita que se queden en blanco si la primera llamada a /api/balance o /api/symbols devolvió 503.
      loadBalance();
      loadSymbols();
      loadBotStatus();
    });

    socket.on('disconnect', (reason) => {
      wsConnected = false;
      updateWebSocketStatus(false);
      logLine(`🔌 WebSocket desconectado: ${reason}`, "warn");
      
      if (reason === 'io server disconnect') {
        // Reconnect manually if server initiated disconnect
        socket.connect();
      }
    });

    socket.on('connect_error', (error) => {
      logLine(`❌ Error de conexión WebSocket: ${error.message}`, "bad");
    });

    socket.on('error', (error) => {
      const errorMsg = typeof error === 'string' ? error : 
                      error?.message || error?.detail || JSON.stringify(error);
      logLine(`❌ Error en Socket.IO: ${errorMsg}`, "bad");
      
      // Si es un error de autenticación, manejar sesión expirada
      if (error?.type === 'auth_error' || errorMsg.includes('auth')) {
        handleSessionExpired("Error de autenticación en WebSocket");
        return;
      }
      
      // Otros tipos de error
      if (error?.type) {
        switch(error.type) {
          case 'stream_error':
            toast('Error iniciando stream de velas');
            break;
          case 'connection_lost':
            toast('Conexión perdida, reconectando...');
            break;
          default:
            toast('Error en Socket.IO');
        }
      }
    });

    socket.on('subscribed', (data) => {
      logLine(`✅ Suscrito a velas de ${data.symbol} (${data.timeframe}s)`, "good");
      lastSubscribedSymbol = data.symbol;
      lastSubscribedTimeframe = data.timeframe;
      // Actualizar UI para reflejar el símbolo y timeframe seleccionados
      const symbolBadge = $("chartSymbol");
      if (symbolBadge) {
        const span = symbolBadge.querySelector('span');
        if (span) span.textContent = data.symbol;
      }
      // Resaltar tarjeta de activo correspondiente sin disparar suscripción de nuevo
      const grid = $("assetsGrid");
      if (grid) {
        Array.from(grid.querySelectorAll('.asset-card')).forEach(card => {
          card.classList.toggle('selected', card.dataset.symbol === data.symbol);
        });
      }
      // Activar botón de timeframe correspondiente
      const tfMapReverse = {60: '1m', 300: '5m', 900: '15m', 3600: '1h', 14400: '4h'};
      const tfLabel = tfMapReverse[data.timeframe] || null;
      document.querySelectorAll('.timeframe-btn').forEach(btn => {
        if (tfLabel && btn.textContent.trim() === tfLabel) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      });
    });

    socket.on('candle_update', (data) => {
      if (!data || !data.candle) return;

      const candle = data.candle;
      const t = toUnixSeconds(candle.time);

      // Update chart
      updateChart(candle);

      // Log only new candles (new period), not intra-candle updates
      if (t && t > lastCandleTime) {
        lastCandleTime = t;
        logLine(`📊 Nueva vela: ${data.symbol} @ ${new Date(t * 1000).toLocaleTimeString()}`, "neutral");
      }
    });

    socket.on('bot_started', (data) => {
      logLine(`🤖 Bot iniciado: ${data.strategy}`, "good");
      updateBotControls(true);
      // Resetear stats locales y arrancar polling cada 5s
      botStats = { ops: 0, wins: 0, losses: 0, profit: 0 };
      updateStatCards();
      clearInterval(botStatusInterval);
      botStatusInterval = setInterval(loadBotStatus, 5000);
    });

    socket.on('bot_stopped', (data) => {
      logLine(`🛑 Bot detenido`, "neutral");
      updateBotControls(false);
      clearInterval(botStatusInterval);
      botStatusInterval = null;
    });

    socket.on('bot_error', (data) => {
      logLine(`❌ Error en bot: ${data.error || data.detail}`, "bad");
      toast("Error en el bot");
      clearInterval(botStatusInterval);
      botStatusInterval = null;
      updateBotControls(false);
    });

    socket.on('trade_opened', (data) => {
      botStats.ops += 1;
      updateStatCards();
      logLine(`📈 Op #${botStats.ops} abierta: ${(data.direction || '').toUpperCase()} $${data.amount}`, "good");
    });

    socket.on('trade_closed', (data) => {
      const pnl    = typeof data.profit === 'number' ? data.profit
                   : typeof data.result === 'number' ? data.result : 0;
      const isWin  = pnl > 0;
      botStats.profit += pnl;
      if (isWin) botStats.wins += 1; else botStats.losses += 1;
      updateStatCards();
      const sign  = pnl >= 0 ? '+' : '';
      logLine(`${isWin ? '✅' : '❌'} Op cerrada: ${isWin ? 'GANADA' : 'PERDIDA'} (${sign}$${pnl.toFixed(2)})`, isWin ? "good" : "bad");
    });

  } catch (error) {
    logLine(`❌ Error inicializando WebSocket: ${error.message}`, "bad");
  }
}

function subscribeToCandles(symbol, timeframe = 60) {
  if (!socket || !wsConnected) {
    logLine("⚠️ WebSocket no conectado", "warn");
    return;
  }

  // Unsubscribe from previous if different
  if (lastSubscribedSymbol && lastSubscribedSymbol !== symbol) {
    socket.emit('unsubscribe_candles', {
      symbol: lastSubscribedSymbol,
      timeframe: lastSubscribedTimeframe || currentTimeframe
    });
  }

  // Reset candle store so the new symbol starts fresh
  resetCandlesStore();

  logLine(`📡 Suscribiendo a velas de ${symbol} (${timeframe}s)...`, "neutral");
  
  socket.emit('subscribe_candles', {
    symbol: symbol,
    timeframe: timeframe
  });
}

function subscribeToSelectedSymbol() {
  const symbol = $("symbol")?.value;
  if (!symbol) {
    logLine("⚠️ No hay símbolo seleccionado", "warn");
    return;
  }

  const timeframe = parseInt($("timeframe")?.value || currentTimeframe);
  subscribeToCandles(symbol, timeframe);
}

// ============================================
// UTILITY ACTIONS
// ============================================
function switchAccount(type) {
  accountType = type;
  sessionStorage.setItem('accountType', type);

  const practiceBtn = $("accPractice");
  const realBtn = $("accReal");

  if (practiceBtn && realBtn) {
    if (type === "PRACTICE") {
      practiceBtn.classList.add("active");
      realBtn.classList.remove("active");
    } else {
      realBtn.classList.add("active");
      practiceBtn.classList.remove("active");
    }
  }

  const headerTypeEl = $("headerAccountType");
  if (headerTypeEl) {
    headerTypeEl.textContent = (type === 'PRACTICE') ? 'PRÁCTICA' : 'REAL';
  }

  logLine(`💼 Cambiando a cuenta ${type}...`, "neutral");

  // Notificar al backend para que IQ Option cambie el balance activo
  apiFetch("/api/change_account", { method: "POST", body: { account_type: type } })
    .then(data => {
      if (!data) return;
      if (data.success) {
        logLine(`✅ Cuenta ${type} activa | Balance: $${(data.balance || 0).toFixed(2)}`, "good");
        updateBalance(data.balance || 0);
        sessionStorage.setItem('lastKnownBalance', data.balance || 0);
      } else {
        const msg = data.error || 'No se pudo cambiar de cuenta';
        logLine(`❌ ${msg}`, "bad");
        toast(msg);
        // Revertir UI al tipo anterior si el cambio falló
        const prev = type === 'REAL' ? 'PRACTICE' : 'REAL';
        accountType = prev;
        sessionStorage.setItem('accountType', prev);
        if (practiceBtn && realBtn) {
          practiceBtn.classList.toggle("active", prev === "PRACTICE");
          realBtn.classList.toggle("active", prev === "REAL");
        }
        if (headerTypeEl) {
          headerTypeEl.textContent = prev === 'PRACTICE' ? 'PRÁCTICA' : 'REAL';
        }
      }
    })
    .catch(() => loadBalance());
}

function filterAssets(filterType) {
  // Actualizar filtro actual y volver a renderizar el grid
  assetFilter = filterType;
  renderAssetsGrid();
  
  // Actualizar estados de botones/chips de filtro. Se usan ids: fltAll, fltNormal, fltOtc.
  ["fltAll", "fltNormal", "fltOtc", "fltOTC", "fltREGULAR"].forEach(id => {
    const btn = $(id);
    if (!btn) return;
    // Mapear id a filtro
    let type;
    if (id.toLowerCase().includes('all')) type = 'ALL';
    else if (id.toLowerCase().includes('normal') || id.toLowerCase().includes('regular')) type = 'NORMAL';
    else if (id.toLowerCase().includes('otc')) type = 'OTC';
    if (type === filterType) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  logLine(`🔍 Filtro aplicado: ${filterType}`, "neutral");
}

function clearLog() {
  const box = $("log");
  if (!box) return;
  box.innerHTML = "";
  logLine("📋 Log limpiado", "neutral");
}

function copyLog() {
  const box = $("log");
  if (!box) return;

  const lines = Array.from(box.children).map(div => div.textContent).join("\n");
  
  navigator.clipboard.writeText(lines)
    .then(() => {
      toast("Log copiado al portapapeles");
      logLine("📋 Log copiado", "good");
    })
    .catch(() => {
      toast("Error copiando log");
      logLine("❌ Error copiando log", "bad");
    });
}

async function calculateOptimalAmount() {
  const strategyId = $("strategy")?.value;
  
  if (!strategyId) {
    toast("Selecciona una estrategia primero");
    return;
  }

  try {
    const data = await apiFetch("/api/optimal_amount", {
      method: "POST",
      body: {
        strategy: strategyId,
        base_amount: 1
      }
    });

    if (!data) return; // Ya manejado por apiFetch si es 401

    if (data.optimal_amount) {
      const amountInput = $("amount");
      if (amountInput) {
        amountInput.value = data.optimal_amount.toFixed(2);
        toast(`Monto óptimo: $${data.optimal_amount.toFixed(2)}`);
        logLine(`💡 Monto óptimo calculado: $${data.optimal_amount.toFixed(2)}`, "good");
      }
    }
  } catch (error) {
    logLine(`❌ Error calculando monto óptimo: ${error.message}`, "bad");
  }
}

/**
 * Logout manual del usuario
 */
/**
 * ✅ CORREGIDO: Logout que SIEMPRE funciona
 */
async function logout() {
  try {
    logLine("🚪 Cerrando sesión...", "neutral");

    // Intentar llamar al endpoint de logout
    // Si falla, no importa - de todas formas limpiamos localmente
    try {
      await fetch(`${API_BASE_URL}/api/logout`, {
        method: "POST",
        credentials: "include",
        mode: "cors"
      });
    } catch (apiError) {
      console.warn("⚠️ Error llamando /api/logout:", apiError);
      // Continuar de todas formas
    }

  } catch (error) {
    console.error("Error en logout:", error);
  } finally {
    // ✅ SIEMPRE ejecutar esto, aunque el backend falle
    localStorage.clear();
    sessionStorage.clear();

    // Desconectar WebSocket
    if (socket) {
      socket.disconnect();
      socket = null;
    }

    toast("Sesión cerrada");
    logLine("✅ Sesión cerrada correctamente", "good");

    // Redirigir al login
    setTimeout(() => {
      window.location.href = "index.html";
    }, 300);
  }
}

/**
 * Alias global para el botón de salir que usa onclick="handleLogout()" en el HTML.
 * Llama a la función logout() definida arriba.
 * Esto asegura que el botón de tu HTML siga funcionando sin modificar el atributo onclick.
 */
function handleLogout() {
  return logout();
}

// ============================================
// EVENT LISTENERS SETUP
// ============================================
function setupEventListeners() {
  // Bot controls
  $("btnStartBot")?.addEventListener("click", startBot);
  $("btnStopBot")?.addEventListener("click", stopBot);

  // Symbol change
  $("symbol")?.addEventListener("change", (e) => {
    const symbol = e.target.value;
    if (symbol && wsConnected) {
      subscribeToSelectedSymbol();
    }
  });

  // Timeframe change: deprecated select. We keep for backward compatibility.
  $("timeframe")?.addEventListener("change", (e) => {
    currentTimeframe = parseInt(e.target.value || 60);
    if (lastSubscribedSymbol) {
      subscribeToCandles(lastSubscribedSymbol, currentTimeframe);
    }
  });

  // Strategy selection - show info
  $("strategy")?.addEventListener("change", (e) => {
    const strategyId = e.target.value;
    const infoEl = $("strategyInfo");
    
    if (!infoEl) return;

    if (!strategyId) {
      infoEl.innerHTML = '<div class="strategy-placeholder">Selecciona una estrategia para ver los detalles</div>';
      return;
    }

    const strategy = strategiesCache.find(s => s.id === strategyId);
    if (!strategy) {
      infoEl.innerHTML = '<div class="strategy-placeholder">Información no disponible</div>';
      return;
    }

    infoEl.innerHTML = `
      <div class="strategy-name">${escapeHtml(strategy.name)}</div>
      ${strategy.description ? `<div class="strategy-desc">${escapeHtml(strategy.description)}</div>` : ''}
      <div class="strategy-meta">
        <div class="meta-item">
          <span class="meta-label">ID</span>
          <span class="meta-value">${escapeHtml(String(strategy.id))}</span>
        </div>
        ${strategy.risk ? `
        <div class="meta-item">
          <span class="meta-label">Nivel de Riesgo</span>
          <span class="meta-value">${escapeHtml(strategy.risk)}</span>
        </div>
        ` : ''}
      </div>
    `;
  });

  // Account switching
  $("accPractice")?.addEventListener("click", () => switchAccount("PRACTICE"));
  $("accReal")?.addEventListener("click", () => switchAccount("REAL"));

  // Filtro de activos para nueva interfaz (chips).
  $("fltAll")?.addEventListener("click", () => filterAssets("ALL"));
  $("fltNormal")?.addEventListener("click", () => filterAssets("NORMAL"));
  $("fltOtc")?.addEventListener("click", () => filterAssets("OTC"));

  // 🔍 Búsqueda de activos: renderizar grid al escribir
  const searchInput = $("assetSearch");
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      renderAssetsGrid();
    });
  }

  // 🕒 Selector de timeframe mediante botones (1m,5m,15m,1h,4h)
  const timeframeMap = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400 };
  document.querySelectorAll('.timeframe-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      // Cambiar activo visual
      document.querySelectorAll('.timeframe-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const label = btn.textContent.trim();
      const tf = timeframeMap[label];
      if (tf) {
        currentTimeframe = tf;
        // Si ya hay un símbolo suscrito, suscribir con el nuevo timeframe
        if (lastSubscribedSymbol) {
          subscribeToCandles(lastSubscribedSymbol, currentTimeframe);
        }
      }
    });
  });

  // Utility buttons
  $("btnClearLog")?.addEventListener("click", clearLog);
  $("btnCopyLog")?.addEventListener("click", copyLog);
  $("btnCalculateAmount")?.addEventListener("click", calculateOptimalAmount);
  
  // ✅ Logout button
  $("logoutBtn")?.addEventListener("click", logout);
}

// ============================================
// INITIALIZATION (MEJORADO)
// ============================================
async function init() {
  logLine("🚀 Iniciando dashboard...", "neutral");

  // ✅ PASO 1: VALIDAR SESIÓN ANTES DE TODO
  try {
    const sessionData = await apiFetch("/api/validate_session");
    if (!sessionData || !sessionData.valid) {
      logLine("❌ Sesión inválida - redirigiendo al login", "bad");
      handleSessionExpired("Sesión no válida");
      return;
    }

    logLine("✅ Sesión válida", "good");

  } catch (error) {
    console.error("Error validando sesión:", error);
    logLine(`⚠️ Advertencia al validar sesión: ${error.message}`, "warn");
    // No redirigir inmediatamente en caso de error de red temporal para evitar loops
    if (error.message.includes('SESSION_EXPIRED') || error.message.includes('401')) {
      handleSessionExpired("Sesión no válida");
      return;
    }
  }

  // ✅ PASO 2: Sesión validada - continuar con setup normal


  // Setup
  setupEventListeners();
  updateConnectionStatus("connected");

  // Set account type buttons
  switchAccount(accountType);

  // Initialize chart
  initChart();

  // Initialize WebSocket
  initWebSocket();

  // Load data
  showLoading();
  try {
    await Promise.all([
      loadBalance(),
      loadSymbols(),
      loadStrategies(),
      loadBotStatus()
    ]);
  } catch (error) {
    logLine(`❌ Error cargando datos iniciales: ${error.message}`, "bad");
  } finally {
    hideLoading();
  }

  logLine("✅ Dashboard inicializado", "good");
  toast("Bienvenido a BotIQ");

  // Auto subscribe si ya hay símbolo seleccionado
  const sym = $("symbol")?.value;
  if (sym) subscribeToSelectedSymbol();
}

// Start when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
