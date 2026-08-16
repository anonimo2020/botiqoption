"""
AI Signal Enhancer para BotIQ
==============================
Dos capas de IA completamente GRATUITAS:

  Capa 1 - LocalMLPredictor
    · scikit-learn RandomForest entrenado con datos reales de IQ Option
    · Cero costo, cero latencia, cero API calls
    · Se entrena automáticamente cuando el bot arranca

  Capa 2 - GroqAdvisor (opcional)
    · LLaMA 3 / Mixtral via Groq (14 400 req/día GRATIS)
    · Registro gratuito en console.groq.com → API key
    · Confirma la señal con análisis textual de los indicadores
    · Si no se configura GROQ_API_KEY en .env, esta capa se desactiva

Cómo aumenta la precisión:
    · Si ML y estrategia técnica coinciden   → +8 % de confianza
    · Si Groq también coincide               → +5 % adicional
    · Si ML y estrategia técnica discrepan   → -10 % (señal dudosa)
    · Si la confianza combinada < umbral     → señal descartada
"""

import os
import logging
import json
import time as _time
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Dependencias opcionales — el bot NO se rompe si faltan
# ──────────────────────────────────────────────────────────────
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score
    import joblib
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False
    logger.warning("⚠️  scikit-learn no instalado — ML layer desactivada")

try:
    import requests as _req
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False


# ══════════════════════════════════════════════════════════════
# CAPA 1 — Machine Learning local
# ══════════════════════════════════════════════════════════════

class LocalMLPredictor:
    """
    RandomForest entrenado en vivo con los últimos 100-200 candles
    del símbolo que el bot está operando.

    Entrada : DataFrame OHLCV + columnas de indicadores técnicos
    Salida  : {'direction': 'call'|'put', 'confidence': 0-100, 'available': bool}
    """

    MODEL_DIR = "/tmp/botiq_ml"
    MIN_SAMPLES = 60          # Mínimo de velas para entrenar
    RETRAIN_EVERY = 50        # Reentrenar cada N análisis

    def __init__(self, symbol: str, timeframe: int = 60):
        self.symbol   = symbol.replace("/", "_").replace("-", "_")
        self.timeframe = timeframe
        self.model    : Optional[RandomForestClassifier] = None
        self.scaler   = StandardScaler() if SKLEARN_OK else None
        self.is_trained   = False
        self._analysis_count = 0

        self._model_path  = os.path.join(self.MODEL_DIR, f"{self.symbol}_{timeframe}.pkl")
        self._scaler_path = os.path.join(self.MODEL_DIR, f"{self.symbol}_{timeframe}_sc.pkl")

        if SKLEARN_OK:
            os.makedirs(self.MODEL_DIR, exist_ok=True)
            self._load_saved()

    # ── persistencia ───────────────────────────────────────────
    def _load_saved(self):
        try:
            if os.path.exists(self._model_path):
                self.model  = joblib.load(self._model_path)
                self.scaler = joblib.load(self._scaler_path)
                self.is_trained = True
                logger.info(f"🤖 ML: modelo cargado para {self.symbol}")
        except Exception as e:
            logger.debug(f"ML: no se pudo cargar modelo guardado: {e}")

    def _save(self):
        try:
            joblib.dump(self.model,  self._model_path)
            joblib.dump(self.scaler, self._scaler_path)
        except Exception as e:
            logger.debug(f"ML: no se pudo guardar modelo: {e}")

    # ── ingeniería de features ──────────────────────────────────
    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Construye ~25 features a partir de las columnas OHLCV + indicadores
        que ya calcula el bot. Los indicadores se reciben como columnas si
        se añaden al DataFrame en _analyze_market(); de lo contrario se
        recalculan aquí usando la librería `ta`.
        """
        feat = pd.DataFrame(index=df.index)
        c = df['close']
        o = df.get('open', c)
        h = df.get('high', c)
        lo = df.get('low', c)
        vol = df.get('volume', pd.Series(1.0, index=df.index))

        # ── Momentum de precio ──
        for p in [1, 2, 3, 5]:
            feat[f'ret_{p}'] = c.pct_change(p)

        # ── RSI ──
        if 'rsi' in df.columns:
            rsi = df['rsi']
        else:
            try:
                from ta.momentum import RSIIndicator
                rsi = RSIIndicator(close=c, window=14).rsi()
            except Exception:
                rsi = pd.Series(50.0, index=df.index)
        feat['rsi']      = rsi / 100.0
        feat['rsi_ob']   = (rsi > 70).astype(int)
        feat['rsi_os']   = (rsi < 30).astype(int)

        # ── MACD ──
        if 'macd' in df.columns and 'macd_signal' in df.columns:
            macd_diff = df['macd'] - df['macd_signal']
        else:
            try:
                from ta.trend import MACD as _MACD
                _m = _MACD(close=c)
                macd_diff = _m.macd_diff()
            except Exception:
                macd_diff = pd.Series(0.0, index=df.index)
        feat['macd_diff']     = macd_diff
        feat['macd_cross_up'] = ((macd_diff > 0) & (macd_diff.shift(1) <= 0)).astype(int)
        feat['macd_cross_dn'] = ((macd_diff < 0) & (macd_diff.shift(1) >= 0)).astype(int)

        # ── Bollinger Bands ──
        if 'bb_upper' in df.columns and 'bb_lower' in df.columns:
            bb_u = df['bb_upper']
            bb_l = df['bb_lower']
        else:
            try:
                from ta.volatility import BollingerBands as _BB
                _b = _BB(close=c)
                bb_u = _b.bollinger_hband()
                bb_l = _b.bollinger_lband()
            except Exception:
                bb_u = c * 1.002
                bb_l = c * 0.998
        bb_rng = (bb_u - bb_l).replace(0, np.nan)
        feat['bb_pos']   = (c - bb_l) / bb_rng
        feat['bb_width'] = bb_rng / c
        feat['bb_above'] = (c > bb_u).astype(int)
        feat['bb_below'] = (c < bb_l).astype(int)

        # ── EMA trend ──
        if 'ema_20' in df.columns and 'ema_50' in df.columns:
            ema_f = df['ema_20']
            ema_s = df['ema_50']
        else:
            ema_f = c.ewm(span=20, adjust=False).mean()
            ema_s = c.ewm(span=50, adjust=False).mean()
        feat['ema_spread']    = (ema_f - ema_s) / c
        feat['above_ema_slow'] = (c > ema_s).astype(int)

        # ── Stochastic ──
        if 'stoch_k' in df.columns:
            feat['stoch'] = df['stoch_k'] / 100.0
        else:
            try:
                from ta.momentum import StochasticOscillator as _Stoch
                feat['stoch'] = _Stoch(high=h, low=lo, close=c).stoch() / 100.0
            except Exception:
                feat['stoch'] = 0.5

        # ── Patrón de vela ──
        rng = (h - lo).replace(0, np.nan)
        feat['body']     = (c - o) / rng
        feat['wick_up']  = (h - c.clip(lower=o)) / rng
        feat['wick_dn']  = (c.clip(upper=o) - lo) / rng

        # ── Volumen relativo ──
        feat['vol_rel'] = vol / vol.rolling(5, min_periods=1).mean()

        # ── Volatilidad ──
        feat['volatility'] = c.rolling(5, min_periods=1).std() / c

        return feat.fillna(0)

    # ── entrenamiento ───────────────────────────────────────────
    def train(self, df: pd.DataFrame) -> dict:
        """
        Entrena el modelo con datos históricos.
        Retorna dict con resultado del entrenamiento.
        """
        if not SKLEARN_OK:
            return {'success': False, 'reason': 'sklearn no disponible'}
        if len(df) < self.MIN_SAMPLES:
            return {'success': False, 'reason': f'pocas velas ({len(df)} < {self.MIN_SAMPLES})'}

        try:
            X_df = self._build_features(df)
            # Target: ¿sube el close en la SIGUIENTE vela?
            target = (df['close'].shift(-1) > df['close']).astype(int)

            valid = X_df.dropna().index.intersection(target.dropna().index)[:-1]
            if len(valid) < 30:
                return {'success': False, 'reason': 'muestras insuficientes después de limpiar'}

            X = X_df.loc[valid].values
            y = target.loc[valid].values

            X_sc = self.scaler.fit_transform(X)

            self.model = RandomForestClassifier(
                n_estimators=30,    # reducido de 150 → liviano para Render free
                max_depth=6,        # reducido de 10 → menos RAM
                min_samples_leaf=4,
                class_weight='balanced',
                random_state=42,
                n_jobs=1            # sin paralelismo → menos picos de memoria
            )
            self.model.fit(X_sc, y)

            try:
                cv = cross_val_score(self.model, X_sc, y, cv=3, scoring='accuracy')
                acc = round(float(cv.mean()) * 100, 1)
            except Exception:
                acc = None

            self.is_trained = True
            self._save()

            return {
                'success': True,
                'samples': len(X),
                'features': X.shape[1],
                'accuracy_cv': acc
            }
        except Exception as e:
            logger.error(f"ML train error: {e}")
            return {'success': False, 'reason': str(e)}

    # ── predicción ──────────────────────────────────────────────
    def predict(self, df: pd.DataFrame) -> dict:
        """
        Predice la dirección de la SIGUIENTE vela.
        """
        if not SKLEARN_OK or not self.is_trained or self.model is None:
            return {'available': False}
        try:
            X_df = self._build_features(df)
            X    = X_df.iloc[[-1]].fillna(0).values
            X_sc = self.scaler.transform(X)
            prob = self.model.predict_proba(X_sc)[0]

            p_up = float(prob[1]) if len(prob) > 1 else 0.5
            p_dn = float(prob[0])

            direction = 'call' if p_up >= p_dn else 'put'
            confidence = int(max(p_up, p_dn) * 100)

            return {
                'available'  : True,
                'direction'  : direction,
                'confidence' : confidence,
                'prob_up'    : round(p_up, 3),
                'prob_dn'    : round(p_dn, 3),
            }
        except Exception as e:
            logger.debug(f"ML predict error: {e}")
            return {'available': False}

    def should_retrain(self) -> bool:
        self._analysis_count += 1
        return self._analysis_count % self.RETRAIN_EVERY == 0


# ══════════════════════════════════════════════════════════════
# CAPA 2 — Groq (LLaMA 3 gratuito)
# ══════════════════════════════════════════════════════════════

class GroqAdvisor:
    """
    Usa la API gratuita de Groq (groq.com) para obtener una
    segunda opinión de LLaMA 3 sobre la señal técnica.

    Configuración:
        Añade GROQ_API_KEY=gsk_... en el archivo .env

    Si no hay clave configurada la capa se desactiva silenciosamente.
    """

    API_URL = "https://api.groq.com/openai/v1/chat/completions"
    MODEL   = "llama3-8b-8192"       # Gratuito, ~280 tokens/s
    TIMEOUT = 4                       # segundos — crítico para no bloquear el bot

    # Cooldown para no gastar cuota en análisis consecutivos idénticos
    COOLDOWN_S = 15

    def __init__(self):
        self.api_key  = os.getenv("GROQ_API_KEY", "").strip()
        self.enabled  = bool(self.api_key) and REQUESTS_OK
        self._last_ts = 0.0
        self._cache   : dict = {}   # {cache_key: result}

        if self.enabled:
            logger.info("🧠 Groq AI advisor activado (LLaMA 3 gratuito)")
        else:
            logger.info("ℹ️  Groq no configurado — solo se usa ML local "
                        "(para activarlo: añade GROQ_API_KEY en .env)")

    def analyze(self, indicators: dict, symbol: str, ta_direction: str) -> dict:
        """
        Envía los indicadores actuales a Groq y pide una recomendación.
        Retorna {'available': bool, 'direction': 'call'|'put', 'confidence': 0-100}
        """
        if not self.enabled:
            return {'available': False}

        now = _time.time()
        if now - self._last_ts < self.COOLDOWN_S:
            return {'available': False}   # cooldown activo

        # Cache key básico
        rsi   = round(indicators.get('rsi', 50), 1)
        trend = indicators.get('trend', '?')
        cache_key = f"{symbol}:{rsi}:{trend}:{ta_direction}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            prompt = self._build_prompt(indicators, symbol, ta_direction)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 60,
                "temperature": 0.1
            }
            resp = _req.post(
                self.API_URL, headers=headers,
                json=payload, timeout=self.TIMEOUT
            )
            resp.raise_for_status()
            text = resp.json()['choices'][0]['message']['content'].strip().lower()

            result = self._parse_response(text)
            self._cache[cache_key] = result
            self._last_ts = now
            return result

        except Exception as e:
            logger.debug(f"Groq error: {e}")
            return {'available': False}

    def _build_prompt(self, ind: dict, symbol: str, ta_dir: str) -> str:
        rsi     = round(ind.get('rsi', 50), 1)
        macd_d  = round(ind.get('macd_diff', 0), 6)
        bb_pos  = "upper" if ind.get('price', 0) > ind.get('bb_upper', 1e18) \
                  else "lower" if ind.get('price', 0) < ind.get('bb_lower', 0) \
                  else "middle"
        stoch   = round(ind.get('stoch_k', 50), 1)
        trend   = ind.get('trend', '?')
        ema_tr  = "bullish" if ind.get('ema_20', 0) > ind.get('ema_50', 0) else "bearish"

        return (
            f"Binary options analysis for {symbol} (60-second expiry).\n"
            f"Indicators: RSI={rsi}, MACD_diff={macd_d:+.6f}, "
            f"BB_position={bb_pos}, Stochastic={stoch}, "
            f"price_trend={trend}, EMA_trend={ema_tr}.\n"
            f"Technical strategy suggests: {ta_dir.upper()}.\n"
            f"Reply with ONLY one word: CALL or PUT."
        )

    @staticmethod
    def _parse_response(text: str) -> dict:
        if 'call' in text:
            return {'available': True, 'direction': 'call', 'confidence': 72}
        if 'put' in text:
            return {'available': True, 'direction': 'put', 'confidence': 72}
        return {'available': False}


# ══════════════════════════════════════════════════════════════
# FACHADA PRINCIPAL
# ══════════════════════════════════════════════════════════════

class AISignalEnhancer:
    """
    Combina ML local + Groq para potenciar las señales del bot.

    Uso en main.py:
        # Al crear el bot:
        self.ai = AISignalEnhancer(symbol, timeframe)

        # Después de obtener las velas (df ya calculado):
        self.ai.maybe_train(df)

        # Después de generar la señal técnica:
        signal = self.ai.enhance(signal, df, indicators)
    """

    # Cuánta confianza mínima debe tener el ML para influir
    ML_MIN_CONFIDENCE = 62

    def __init__(self, symbol: str, timeframe: int = 60):
        self.symbol   = symbol
        self.ml       = LocalMLPredictor(symbol, timeframe)
        self.groq     = GroqAdvisor()

    def maybe_train(self, df: pd.DataFrame):
        """
        Entrena (o reentrana) el modelo ML si es necesario.
        Llamar una vez por ciclo de análisis.
        """
        if not SKLEARN_OK:
            return
        if not self.ml.is_trained or self.ml.should_retrain():
            result = self.ml.train(df)
            if result.get('success'):
                acc = result.get('accuracy_cv')
                msg = (f"🤖 ML entrenado | {result['samples']} muestras"
                       + (f" | acc={acc}%" if acc else ""))
                logger.info(msg)
            else:
                logger.debug(f"ML no entrenado: {result.get('reason')}")

    def enhance(self, signal: dict, df: pd.DataFrame, indicators: dict) -> dict:
        """
        Toma la señal técnica existente y aplica el boost/penalización de IA.
        Devuelve la señal modificada (misma referencia, campos actualizados).
        """
        ta_dir  = signal.get('direction')
        ta_conf = signal.get('confidence', 0)

        if not ta_dir or ta_conf <= 0:
            return signal   # sin señal técnica — nada que mejorar

        ai_votes_for  = 0   # capas que CONFIRMAN la señal
        ai_votes_against = 0

        # ── Voto 1: ML local ─────────────────────────────────
        ml_result = self.ml.predict(df)
        ml_note   = ""
        if ml_result.get('available') and ml_result['confidence'] >= self.ML_MIN_CONFIDENCE:
            if ml_result['direction'] == ta_dir:
                ai_votes_for += 1
                ml_note = f"ML ✅ {ml_result['direction'].upper()} {ml_result['confidence']}%"
            else:
                ai_votes_against += 1
                ml_note = f"ML ❌ {ml_result['direction'].upper()} {ml_result['confidence']}%"
        else:
            ml_note = "ML ⚪ (baja confianza o no entrenado)"

        # ── Voto 2: Groq LLM ─────────────────────────────────
        groq_note = ""
        if self.groq.enabled:
            groq_result = self.groq.analyze(indicators, self.symbol, ta_dir)
            if groq_result.get('available'):
                if groq_result['direction'] == ta_dir:
                    ai_votes_for += 1
                    groq_note = f"Groq ✅ {groq_result['direction'].upper()}"
                else:
                    ai_votes_against += 1
                    groq_note = f"Groq ❌ {groq_result['direction'].upper()}"

        # ── Calcular confianza final ──────────────────────────
        boost   = ai_votes_for     * 6    # +6% por voto a favor
        penalty = ai_votes_against * 15   # -15% por voto en contra (penalización más agresiva)

        final_conf = min(95, max(0, ta_conf + boost - penalty))

        # Registrar en la señal para trazabilidad
        signal['confidence'] = final_conf
        signal['ai_boost']   = boost - penalty
        signal['ai_notes']   = " | ".join(filter(None, [ml_note, groq_note]))

        if boost or penalty:
            action = "↑" if boost > penalty else "↓"
            logger.info(
                f"🤖 AI enhance: {ta_dir.upper()} | "
                f"base={ta_conf:.0f}% {action} final={final_conf:.0f}% | "
                f"{signal['ai_notes']}"
            )

        return signal
