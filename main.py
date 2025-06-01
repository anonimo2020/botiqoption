from flask import Flask, request, jsonify
import threading
import time
import logging
from iqoptionapi.stable_api import IQ_Option

IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"

app = Flask(__name__)

def bot_logic():
    logging.basicConfig(level=logging.INFO)
    Iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
    check, reason = Iq.connect()
    if not check:
        print(f"Error de conexión: {reason}")
        return
    Iq.change_balance("PRACTICE")
    Iq.buy(1, "EURUSD", "call", 1)
    print("Operación enviada.")

@app.route('/start_bot', methods=['POST'])
def start_bot():
    try:
        threading.Thread(target=bot_logic, daemon=True).start()
        return jsonify({"message": "🤖 Bot iniciado correctamente"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
