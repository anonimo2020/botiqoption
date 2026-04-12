const API = "https://botiqoption-4.onrender.com"; // tu Render
let accountType = "PRACTICE"; // DEMO por defecto

// cache local
let symbolsCache = [];
let strategiesCache = [];

const $ = (id) => document.getElementById(id);

// ---- Log control (evita que "Live data" buguee la UI) ----
const MAX_LOG_LINES = 250;

function toast(msg){
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(()=> el.classList.remove("show"), 2200);
}

function logLine(msg, kind=""){
  const box = $("log");
  const d = new Date();
  const time = d.toLocaleTimeString();
  const div = document.createElement("div");
  div.className = `line ${kind}`;
  div.innerHTML = `<span class="t">${time}</span>${escapeHtml(msg)}`;
  box.appendChild(div);

  // recorta líneas viejas para que no se congele
  while (box.children.length > MAX_LOG_LINES) {
    box.removeChild(box.firstChild);
  }

  box.scrollTop = box.scrollHeight;
}

function escapeHtml(s){
  return String(s)
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;");
}

async function apiFetch(path, { method="GET", body=null } = {}){
  const opts = {
    method,
    headers: { "Content-Type":"application/json" },
    credentials: "include" // IMPORTANTE para cookies/sesión
  };
  if(body) opts.body = JSON.stringify(body);

  const res = await fetch(`${API}${path}`, opts);
  const text = await res.text();

  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }

  if(!res.ok){
    const msg = data?.error || data?.message || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function setPill(el, mode, text){
  el.classList.remove("ok","bad","warn","neutral");
  if(mode) el.classList.add(mode);
  el.textContent = text;
}

function setAccountButtons(){
  $("accPractice").classList.toggle("on", accountType === "PRACTICE");
  $("accReal").classList.toggle("on", accountType === "REAL");
  $("userType").textContent = accountType;
}

// Funciones globales invocadas desde onclick en HTML
function uiRefresh(){
  logLine("🔄 Refrescando...");
  refreshBotStatus();
  refreshBalance();
}

function setAccount(type){
  accountType = type;
  setAccountButtons();
  toast(`Cuenta: ${type === "PRACTICE" ? "Demo" : "Real"}`);
  logLine(`💼 Cambiado a cuenta ${type === "PRACTICE" ? "DEMO" : "REAL"}`,
          type === "PRACTICE" ? "neutral" : "warn");
}

function clearLog(){
  $("log").innerHTML = "";
  logLine("📋 Log limpiado", "neutral");
}

async function copyLog(){
  const text = $("log").innerText;
  try{
    await navigator.clipboard.writeText(text);
    toast("Log copiado al portapapeles");
    logLine("📋 Log copiado", "good");
  }catch{
    toast("No se pudo copiar");
  }
}

// ---- Gráfico de velas (LightweightCharts) ----
let chart = null;
let candleSeries = null;

function initChart(){
  const container = $("chartContainer");
  if(!container || chart) return;

  chart = LightweightCharts.createChart(container, {
    layout:{
      background:{ color:"#0b0c10" },
      textColor:"rgba(255,255,255,.65)"
    },
    grid:{
      vertLines:{ color:"rgba(255,255,255,.05)" },
      horzLines:{ color:"rgba(255,255,255,.05)" }
    },
    crosshair:{ mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale:{ borderColor:"rgba(255,255,255,.1)" },
    timeScale:{ borderColor:"rgba(255,255,255,.1)", timeVisible:true },
    width: container.clientWidth,
    height: 260,
  });

  candleSeries = chart.addCandlestickSeries({
    upColor:"#28ff6a",
    downColor:"#ff3b3b",
    borderVisible:false,
    wickUpColor:"#28ff6a",
    wickDownColor:"#ff3b3b",
  });

  new ResizeObserver(()=>{
    if(chart) chart.applyOptions({ width: container.clientWidth });
  }).observe(container);
}

function updateChart(candles){
  if(!candleSeries || !candles || candles.length === 0) return;

  const data = candles
    .filter(c => c.open && c.close)
    .map(c =>({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }))
    .sort((a, b) => a.time - b.time);

  // Dedup por time (LightweightCharts no acepta timestamps duplicados)
  const seen = new Set();
  const clean = data.filter(c =>{ if(seen.has(c.time)) return false; seen.add(c.time); return true; });

  if(clean.length > 0){
    candleSeries.setData(clean);
    chart.timeScale().fitContent();
    const pill = $("pillChart");
    if(pill) setPill(pill, "ok", `${clean.length} velas`);
  }
}

// ---------------- Normalizers ----------------

function normalizeSymbols(payload){
  // backend actual: {symbols:[{symbol,name,type,otc?}...]}
  const arr = Array.isArray(payload) ? payload : (payload?.symbols || payload?.data || []);
  return arr.map(x=>{
    if(typeof x === "string"){
      const isOtc = x.toUpperCase().includes("OTC");
      return { symbol: x, otc: isOtc };
    }
    const sym = x.symbol || x.name || x.ticker || "";
    const otc = Boolean(
      x.otc ?? x.is_otc ?? x.type === "OTC" ?? (String(sym).toUpperCase().includes("OTC"))
    );
    return { symbol: sym, otc };
  }).filter(x=>x.symbol);
}

function normalizeStrategies(payload){
  // backend recomendado: {strategies:[{id:"conservative_rsi", name:"RSI Conservador", ...}]}
  const arr = Array.isArray(payload) ? payload : (payload?.strategies || payload?.data || []);
  return arr.map((x, idx)=>{
    if(typeof x === "string"){
      // sin id real, no sirve para backend → generamos uno, pero mejor que backend devuelva id/key real
      return { id: `strategy_${idx+1}`, name: x, risk: "", description: "" };
    }
    // IMPORTANTE: id debe ser la key real del backend (conservative_rsi, etc)
    const id = x.id ?? x.key ?? x.strategy_id ?? x.slug ?? `strategy_${idx+1}`;
    return {
      id: String(id),
      name: x.name ?? x.strategy ?? `Estrategia ${idx+1}`,
      risk: x.risk ?? x.level ?? x.risk_level ?? "",
      description: x.description ?? x.desc ?? ""
    };
  });
}

// ---------------- Renderers ----------------

function renderSymbols(){
  const market = $("market").value; // ALL | NORMAL | OTC
  const list = symbolsCache.filter(s=>{
    if(market === "ALL") return true;
    if(market === "OTC") return s.otc;
    if(market === "NORMAL") return !s.otc;
    return true;
  });

  const sel = $("symbol");
  const prev = sel.value;
  sel.innerHTML = `<option value="">Selecciona…</option>` + list
    .map(s=> `<option value="${escapeHtml(s.symbol)}">${escapeHtml(s.symbol)}${s.otc ? " • OTC": ""}</option>`)
    .join("");

  if(list.some(s=>s.symbol === prev)) sel.value = prev;
}

function renderStrategies(){
  const sel = $("strategy");
  const prev = sel.value;

  sel.innerHTML = `<option value="">Selecciona…</option>` + strategiesCache
    .map(s=> {
      const extra = [
        s.risk ? `Riesgo: ${s.risk}` : "",
        s.description ? s.description : ""
      ].filter(Boolean).join(" — ");
      // VALUE = ID REAL (key del backend)
      return `<option value="${escapeHtml(String(s.id))}">${escapeHtml(s.name)}${extra ? " • " + escapeHtml(extra) : ""}</option>`;
    })
    .join("");

  if(strategiesCache.some(s=>String(s.id) === prev)) sel.value = prev;
}

// ---------------- Calls ----------------

async function checkStatusQuick(){
  try{
    const st = await apiFetch("/api/bot_status");
    setPill($("pillConn"), "ok", "Conectado");
    setPill($("pillSession"), "neutral", "Sesión: OK");
    $("botStatus").textContent = JSON.stringify(st, null, 2);
    setPill($("pillBot"), st?.running ? "ok" : "neutral", st?.running ? "Running" : "Stopped");
  }catch(e){
    setPill($("pillConn"), "bad", "Desconectado");
    setPill($("pillSession"), "neutral", "Sesión: —");
    $("botStatus").textContent = `Sin sesión / backend no responde.\n${String(e.message || e)}`;
    setPill($("pillBot"), "neutral", "—");
  }
}

function pickUsernameFromLogin(data){
  // Soporta: {user:{name,...}} o {name,...} o {username,...}
  const u = data?.user || {};
  return (
    u.name || u.username || u.email ||
    data?.name || data?.username || data?.email ||
    data?.profile?.name ||
    ""
  );
}

async function login(){
  const email = $("email").value.trim();
  const password = $("password").value;

  if(!email || !password){
    toast("Completa email y password");
    return;
  }

  try{
    logLine("Intentando login…");
    const data = await apiFetch("/api/login", {
      method:"POST",
      body:{ email, password }
    });

    setPill($("pillConn"), "ok", "Conectado");
    setPill($("pillSession"), "ok", "Sesión: activa");
    toast("Login OK");
    logLine("Login exitoso", "good");

    const uname = pickUsernameFromLogin(data);
    $("userName").textContent = uname || "—";
    $("userType").textContent = accountType;

    await refreshBalance();
    await loadStrategies();
    await loadSymbols();
    await refreshBotStatus();

  }catch(e){
    toast(`Login falló: ${e.message}`);
    logLine(`Login falló: ${e.message}`, "bad");
    setPill($("pillSession"), "bad", "Sesión: error");
  }
}

async function logout(){
  try{
    await apiFetch("/api/logout", { method:"POST" });
    toast("Logout OK");
    logLine("Logout", "warn");
  }catch(e){
    toast(`Logout: ${e.message}`);
    logLine(`Logout error: ${e.message}`, "bad");
  }finally{
    $("userName").textContent = "—";
    $("userBalance").textContent = "—";
    setPill($("pillSession"), "neutral", "Sesión: —");
    await checkStatusQuick();
  }
}

async function refreshBalance(){
  try{
    const data = await apiFetch("/api/balance");
    const bal = data?.balance ?? data?.data?.balance ?? data?.amount ?? data?.equity;
    const cur = data?.currency ?? data?.data?.currency ?? "";
    $("userBalance").textContent = (bal !== undefined && bal !== null) ? `${bal} ${cur}`.trim() : JSON.stringify(data);
    setPill($("pillReady"), "neutral", "Config: cargada");
    logLine("Balance actualizado", "good");
  }catch(e){
    toast(`Balance: ${e.message}`);
    logLine(`Balance error: ${e.message}`, "bad");
  }
}

async function loadSymbols(){
  try{
    const data = await apiFetch("/api/symbols");
    symbolsCache = normalizeSymbols(data);
    renderSymbols();
    toast(`Símbolos: ${symbolsCache.length}`);
    logLine(`Símbolos cargados: ${symbolsCache.length}`, "good");
  }catch(e){
    toast(`Símbolos: ${e.message}`);
    logLine(`Símbolos error: ${e.message}`, "bad");
  }
}

async function loadStrategies(){
  try{
    const data = await apiFetch("/api/strategies");
    strategiesCache = normalizeStrategies(data);
    renderStrategies();
    toast(`Estrategias: ${strategiesCache.length}`);
    logLine(`Estrategias cargadas: ${strategiesCache.length}`, "good");
  }catch(e){
    toast(`Estrategias: ${e.message}`);
    logLine(`Estrategias error: ${e.message}`, "bad");
  }
}

async function refreshBotStatus(){
  try{
    const st = await apiFetch("/api/bot_status");
    $("botStatus").textContent = JSON.stringify(st, null, 2);
    setPill($("pillBot"), st?.running ? "ok" : "neutral", st?.running ? "Running" : "Stopped");
    logLine("Estado del bot actualizado");
  }catch(e){
    toast(`Status: ${e.message}`);
    logLine(`Status error: ${e.message}`, "bad");
  }
}

// 🔧 CORRECCIÓN CRÍTICA: startBot()
async function startBot(){
  const symbol = $("symbol").value;
  const strategyKey = $("strategy").value; // ✅ ID REAL del backend
  const amount = Number($("amount").value || 1);
  const duration = Number($("duration").value || 1);

  // Validaciones mejoradas
  if(!symbol){ 
    toast("Selecciona símbolo"); 
    logLine("❌ Error: No se seleccionó símbolo", "bad");
    return; 
  }
  
  if(!strategyKey){ 
    toast("Selecciona estrategia"); 
    logLine("❌ Error: No se seleccionó estrategia", "bad");
    return; 
  }

  const st = strategiesCache.find(x => String(x.id) === String(strategyKey));
  const strategyName = st?.name || strategyKey;

  try{
    logLine(`🚀 Iniciando bot...`);
    logLine(`  📊 Símbolo: ${symbol}`);
    logLine(`  🎯 Estrategia: ${strategyName} (ID: ${strategyKey})`);
    logLine(`  💵 Monto: $${amount}`);
    logLine(`  ⏱️  Duración: ${duration}m`);
    logLine(`  💼 Cuenta: ${accountType}`);

    // ✅ PAYLOAD CORRECTO
    const payload = {
      account_type: accountType,
      symbol: symbol,
      amount: amount,
      duration: duration,
      strategy: strategyKey,  // ✅ Solo esto - ID real de la estrategia
      max_operations: 0,
      max_loss_operations: 5
    };

    console.log("📤 Enviando payload:", payload);

    const data = await apiFetch("/api/start_bot", {
      method: "POST",
      body: payload
    });

    toast(data?.message || "Bot iniciado");
    logLine(`✅ ${data?.message || "Bot iniciado"}`, "good");
    
    if(data?.strategy_info){
      logLine(`  ℹ️  Estrategia: ${data.strategy_info.name}`, "good");
      logLine(`  ⚠️  Riesgo: ${data.strategy_info.risk_level}`, "warn");
    }
    
    await refreshBotStatus();
  }catch(e){
    toast(`Start: ${e.message}`);
    logLine(`❌ Error: ${e.message}`, "bad");
    console.error("Error completo:", e);
  }
}
async function stopBot(){
  try{
    logLine("🛑 Deteniendo bot...");
    const data = await apiFetch("/api/stop_bot", { method:"POST" });
    toast(data?.message || "Bot detenido");
    logLine(`✅ ${data?.message || "Bot detenido"}`, "warn");
    
    if(data?.final_stats){
      logLine(`  📊 Operaciones totales: ${data.final_stats.operations_count}`, "neutral");
      logLine(`  💰 Profit de sesión: $${data.final_stats.session_profit}`, "neutral");
    }
    
    await refreshBotStatus();
  }catch(e){
    toast(`Stop: ${e.message}`);
    logLine(`❌ Error al detener: ${e.message}`, "bad");
  }
}

async function optimalAmount(){
  try{
    const strategyKey = $("strategy").value;
    if(!strategyKey){
      toast("Selecciona estrategia primero");
      logLine("⚠️ Selecciona una estrategia primero", "warn");
      return;
    }

    logLine("💡 Calculando monto óptimo...");

    const data = await apiFetch("/api/optimal_amount", {
      method:"POST",
      body:{
        strategy: strategyKey,  // ✅ ID real de la estrategia
        base_amount: Number($("amount").value || 1)
      }
    });

    const opt = data?.optimal_amount ?? data?.amount ?? data?.data?.optimal_amount ?? data?.data?.amount;
    
    if(opt !== undefined && opt !== null){
      $("amount").value = opt;
      toast(`Monto óptimo: $${opt}`);
      logLine(`✅ Monto óptimo: $${opt} (riesgo: ${data?.risk_level || "?"})`, "good");
    }else{
      toast("Respuesta no reconocida");
      logLine(`⚠️ Respuesta: ${JSON.stringify(data)}`, "warn");
    }
  }catch(e){
    toast(`Optimal: ${e.message}`);
    logLine(`❌ Error calculando monto: ${e.message}`, "bad");
  }
}

// ---------- Live data (resumen para que no se buguee) ----------
let liveTimer = null;


function summarizeLive(data){
  const candles = data?.candles;
  if(!Array.isArray(candles) || candles.length === 0){
    return `Live: sin velas (status=${data?.bot_status?.running ? "running" : "stopped"})`;
  }
  const last = candles[candles.length - 1];
  const t = last?.time ? new Date(last.time * 1000).toLocaleTimeString() : "—";
  const o = last?.open?.toFixed(5), 
        h = last?.high?.toFixed(5), 
        l = last?.low?.toFixed(5), 
        c = last?.close?.toFixed(5);
  
  // Incluir indicadores si existen
  const indicators = data?.indicators;
  let indStr = "";
  if(indicators){
    const rsi = indicators.rsi ? `RSI:${indicators.rsi.toFixed(1)}` : "";
    const trend = indicators.trend ? `Trend:${indicators.trend}` : "";
    indStr = [rsi, trend].filter(Boolean).join(" ");
  }
  
  return `Live ${t} | O:${o} H:${h} L:${l} C:${c}${indStr ? " | " + indStr : ""}`;
}

async function liveDataOnce(){
  try{
    const data = await apiFetch("/api/live_data");
    logLine(summarizeLive(data), "");
    if(data?.candles) updateChart(data.candles);
  }catch(e){
    logLine(`Live error: ${e.message}`, "bad");
  }
}

function toggleLive(){
  if(liveTimer){
    clearInterval(liveTimer);
    liveTimer = null;
    toast("Live OFF");
    logLine("🔴 Live data desactivado", "warn");
    return;
  }
  toast("Live ON");
  logLine("🟢 Live data activado (cada 2.5s)", "good");
  liveDataOnce();
  liveTimer = setInterval(liveDataOnce, 2500);
}

// boot — inicializar gráfico, estado de botones y primer check de conexión
initChart();
logLine("🚀 Aplicación iniciada");
setAccountButtons();
checkStatusQuick();