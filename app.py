import json
import threading
import time
import datetime
import pytz
import yfinance as yf
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

ACTIONS_PATH = "actions.json"
SETTINGS_PATH = "settings.json"
LOGS_PATH = "logs.txt"

CHECK_TIMES = [(9, 0), (13, 0), (16, 0)] # Horas fijas Argentina

robot_running = True


# ============================================================
# UTILIDADES DE ARCHIVO
# ============================================================

def read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def save_log(text):
    stamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M] ")
    with open(LOGS_PATH, "a") as f:
        f.write(stamp + text + "\n")


# ============================================================
# API – ACCIONES
# ============================================================

@app.route("/api/actions", methods=["GET"])
def api_get_actions():
    data = read_json(ACTIONS_PATH)
    return jsonify(data)

@app.route("/api/add", methods=["POST"])
def api_add_action():
    req = request.json
    symbol = req.get("symbol", "").upper()
    up = float(req.get("up"))
    down = float(req.get("down"))

    data = read_json(ACTIONS_PATH)
    data[symbol] = {
        "up": up,
        "down": down,
        "active": True
    }
    write_json(ACTIONS_PATH, data)

    save_log(f"Añadida acción {symbol} (up={up}, down={down})")
    return jsonify({"ok": True})

@app.route("/api/update", methods=["POST"])
def api_update_action():
    req = request.json
    symbol = req.get("symbol")
    up = req.get("up")
    down = req.get("down")
    active = req.get("active")

    data = read_json(ACTIONS_PATH)
    if symbol not in data:
        return jsonify({"error": "No existe"}), 404

    if up is not None:
        data[symbol]["up"] = float(up)
    if down is not None:
        data[symbol]["down"] = float(down)
    if active is not None:
        data[symbol]["active"] = bool(active)

    write_json(ACTIONS_PATH, data)
    save_log(f"Actualizada acción {symbol}")
    return jsonify({"ok": True})

@app.route("/api/delete", methods=["POST"])
def api_delete_action():
    req = request.json
    symbol = req.get("symbol")

    data = read_json(ACTIONS_PATH)
    if symbol in data:
        del data[symbol]
        write_json(ACTIONS_PATH, data)
        save_log(f"Eliminada acción {symbol}")

    return jsonify({"ok": True})


# ============================================================
# API – SETTINGS (TOKEN + CHAT ID)
# ============================================================

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(read_json(SETTINGS_PATH))

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    req = request.json
    token = req.get("token")
    chat_id = req.get("chat_id")

    data = {
        "token": token,
        "chat_id": chat_id
    }
    write_json(SETTINGS_PATH, data)
    save_log("Actualizados Telegram token/chat_id")

    return jsonify({"ok": True})


# ============================================================
# API – LOGS
# ============================================================

@app.route("/api/logs", methods=["GET"])
def api_get_logs():
    try:
        with open(LOGS_PATH, "r") as f:
            return jsonify(f.read().splitlines())
    except:
        return jsonify([])


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(token, chat_id, mensaje):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": mensaje}, timeout=10)
    except:
        pass


# ============================================================
# ROBOT 24/7
# ============================================================

def robot_loop():
    global robot_running
    tz_ar = pytz.timezone("America/Argentina/Buenos_Aires")
    last_run = set()

    save_log("Robot iniciado correctamente.")

    while robot_running:
        now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
        now_ar = now_utc.astimezone(tz_ar)

        hm = (now_ar.hour, now_ar.minute)
        key = (now_ar.date(), now_ar.hour, now_ar.minute)

        if hm in CHECK_TIMES and key not in last_run:
            last_run.add(key)

            settings = read_json(SETTINGS_PATH)
            token = settings.get("token")
            chat_id = settings.get("chat_id")

            acciones = read_json(ACTIONS_PATH)

            save_log(f"Chequeo programado → {now_ar.strftime('%H:%M')}")

            for symbol, info in acciones.items():
                if not info["active"]:
                    continue

                try:
                    data = yf.Ticker(symbol).history(period="1d", interval="1m")
                    precio = float(data["Close"].iloc[-1])
                except:
                    save_log(f"Error obteniendo precio de {symbol}")
                    continue

                up_level = info["up"]
                down_level = info["down"]

                if precio >= up_level:
                    msg = f"📈 {symbol} está por ENCIMA de {up_level} → {precio:.2f}"
                    enviar_telegram(token, chat_id, msg)
                    save_log(msg)

                if precio <= down_level:
                    msg = f"📉 {symbol} está por DEBAJO de {down_level} → {precio:.2f}"
                    enviar_telegram(token, chat_id, msg)
                    save_log(msg)

        time.sleep(30)


# Iniciar robot en thread
threading.Thread(target=robot_loop, daemon=True).start()


# ============================================================
# SERVIDOR FLASK
# ============================================================

@app.route("/")
def index():
    return "<h1>Servidor activo. El frontend está en /static/index.html</h1>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)