# IQ Option Trading Bot Backend

Backend profesional para bot de trading de opciones binarias con IQ Option.

## Características

- ✅ Autenticación segura con IQ Option
- ✅ 5 estrategias de trading con diferentes niveles de riesgo
- ✅ Gestión automática de capital (máximo 50% por operación)
- ✅ Sistema Martingala modificado según nivel de riesgo
- ✅ Límites configurables de operaciones y pérdidas consecutivas
- ✅ Notificaciones por Telegram
- ✅ Soporte para mercados OTC en fin de semana
- ✅ Panel de control en tiempo real
- ✅ Análisis técnico con múltiples indicadores

## Estrategias Implementadas

1. **RSI Conservador** (Riesgo: Muy Bajo)
   - RSI + EMA confirmación
   - Confianza mínima: 75%

2. **Cruce MACD** (Riesgo: Bajo)
   - Señales de cruce MACD
   - Confianza mínima: 70%

3. **Rebote Bollinger** (Riesgo: Medio)
   - Rebotes en bandas de Bollinger
   - Confianza mínima: 65%

4. **Multi-Indicador** (Riesgo: Medio)
   - Combina RSI, MACD, Stochastic
   - Confianza mínima: 60%

5. **Scalping Momentum** (Riesgo: Alto)
   - Operaciones rápidas con CCI y ATR
   - Confianza mínima: 55%

## Instalación

### Requisitos
- Python 3.11+
- Redis
- Cuenta de IQ Option

### Pasos

1. Clonar el repositorio:
```bash
git clone https://github.com/tu-usuario/iqoption-bot-backend.git
cd iqoption-bot-backend
```

2. Crear entorno virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows
```

3. Instalar dependencias:
```bash
pip install -r requirements.txt
```

4. Configurar variables de entorno:
```bash
cp .env.example .env
# Editar .env con tus valores
```

5. Ejecutar:
```bash
python app.py
```

## Deployment en Render

1. Fork este repositorio
2. Conecta tu cuenta de GitHub con Render
3. Crea un nuevo Web Service
4. Selecciona este repositorio
5. Render detectará automáticamente la configuración
6. Añade las variables de entorno necesarias
7. Deploy!

## API Endpoints

### Autenticación
- `POST /api/login` - Iniciar sesión con IQ Option
- `POST /api/logout` - Cerrar sesión

### Trading
- `GET /api/strategies` - Obtener estrategias disponibles
- `GET /api/symbols` - Obtener símbolos de trading
- `POST /api/start_bot` - Iniciar bot
- `POST /api/stop_bot` - Detener bot
- `GET /api/bot_status` - Estado del bot

### Información
- `GET /api/balance` - Balance actual
- `POST /api/optimal_amount` - Calcular monto óptimo
- `GET /api/live_data` - Datos en tiempo real

## Seguridad

- Sesiones seguras con Redis
- CORS configurado para dominio específico
- Cookies HTTPOnly y Secure
- Sin almacenamiento de contraseñas
- Límites de operación configurables

## Estructura del Proyecto

```
├── app.py                 # Aplicación principal Flask
├── session_manager.py     # Gestión de sesiones IQ Option
├── requirements.txt       # Dependencias Python
├── runtime.txt           # Versión de Python
├── render.yaml           # Configuración de Render
├── Dockerfile            # Configuración Docker
├── .env.example          # Variables de entorno ejemplo
├── .gitignore           # Archivos ignorados
└── README.md            # Este archivo
```

## Variables de Entorno

```env
# Flask
SECRET_KEY=tu-clave-secreta
FLASK_ENV=production

# Redis
REDIS_URL=redis://...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Frontend
FRONTEND_URL=https://iqoptionbot.ct.ws
```

## Monitoreo

El bot envía notificaciones a Telegram sobre:
- Logins exitosos
- Inicio/parada del bot
- Cada operación ejecutada
- Límites alcanzados
- Errores importantes

## Limitaciones

- Las sesiones de IQ Option expiran después de cierto tiempo
- En fin de semana solo están disponibles activos OTC
- El rendimiento depende de la volatilidad del mercado
- Las estrategias no garantizan ganancias

## Soporte

Para soporte o preguntas, contactar mediante Telegram.

## Licencia

Este proyecto es privado y confidencial.
