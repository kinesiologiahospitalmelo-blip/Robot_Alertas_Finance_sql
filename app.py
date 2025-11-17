import os
import threading
import time
import datetime
import pytz
import yfinance as yf
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask, request, jsonify, send_from_directory

# ============================================================
# CONFIG FLASK
# ============================================================

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static"
)

CHECK_TIMES = [(9, 0), (13, 0), (16, 0)]  # Horas fijas Argentina
robot_running = True


# ============================================================
# CONEXIÓN A POSTGRES
# ============================================================

def get_db_connection():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no está definida en las variables de entorno")

    # Render a veces da postgres:// y psycopg2 prefiere postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(url)
    return conn


def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS acciones (
        id SERIAL PRIMARY KEY,
        symbol TEXT UNIQUE NOT NULL,
        up NUMERIC NOT NULL,
        down NUMERIC NOT NULL,
        anotacion_up TEXT,
        anotacion_down TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS settings (
        id BOOLEAN PRIMARY KEY DEFAULT TRUE,
        token TEXT,
        chat_id TEXT
    );

    CREATE TABLE IF NOT EXISTS logs (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        text TEXT NOT NULL
    );
    """
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(schema)
    conn.close()


# ============================================================
# LOGS
# ============================================================

def save_log(text):
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO logs (text) VALUES (%s)",
                (text,)
            )
    conn.close()


# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(token, chat_id, mensaje):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": mensaje}, timeout=10)
    except Exception as e:
        save_log(f"Error enviando Telegram: {e}")


# ============================================================
# HELPERS DB
# ============================================================

def get_all_acciones():
    conn = get_db_connection()
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM acciones ORDER BY symbol ASC")
            rows = cur.fetchall()
    conn.close()
    return rows


def get_settings():
    conn = get_db_connection()
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM settings WHERE id = TRUE")
            row = cur.fetchone()
    conn.close()
    if not row:
        return {"token": "", "chat_id": ""}
    return {"token": row["token"] or "", "chat_id": row["chat_id"] or ""}


# ============================================================
# API – ACCIONES
# ============================================================

@app.route("/api/actions", methods=["GET"])
def api_get_actions():
    acciones = get_all_acciones()
    # Respuesta tipo dict por symbol, similar a tu JSON original
    data = {}
    for row in acciones:
        data[row["symbol"]] = {
            "up": float(row["up"]),
            "down": float(row["down"]),
            "anotacion_up": row["anotacion_up"] or "",
            "anotacion_down": row["anotacion_down"] or "",
            "active": bool(row["active"])
        }
    return jsonify(data)


@app.route("/api/add", methods=["POST"])
def api_add_action():
    req = request.json or {}
    symbol = req.get("symbol", "").upper().strip()
    up = req.get("up")
    down = req.get("down")
    anotacion_up = (req.get("anotacion_up") or "").strip()
    anotacion_down = (req.get("anotacion_down") or "").strip()

    if not symbol or up is None or down is None:
        return jsonify({"error": "symbol, up y down son obligatorios"}), 400

    try:
        up = float(up)
        down = float(down)
    except ValueError:
        return jsonify({"error": "up y down deben ser numéricos"}), 400

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acciones (symbol, up, down, anotacion_up, anotacion_down, active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (symbol) DO UPDATE
                SET up = EXCLUDED.up,
                    down = EXCLUDED.down,
                    anotacion_up = EXCLUDED.anotacion_up,
                    anotacion_down = EXCLUDED.anotacion_down,
                    active = TRUE;
                """,
                (symbol, up, down, anotacion_up, anotacion_down)
            )
    conn.close()

    save_log(f"Añadida/Actualizada acción {symbol} (up={up}, down={down})")
    return jsonify({"ok": True})


@app.route("/api/update", methods=["POST"])
def api_update_action():
    req = request.json or {}
    symbol = (req.get("symbol") or "").upper().strip()
    if not symbol:
        return jsonify({"error": "symbol es obligatorio"}), 400

    fields = []
    values = []

    if "up" in req and req["up"] is not None:
        fields.append("up = %s")
        values.append(float(req["up"]))

    if "down" in req and req["down"] is not None:
        fields.append("down = %s")
        values.append(float(req["down"]))

    if "anotacion_up" in req:
        fields.append("anotacion_up = %s")
        values.append((req["anotacion_up"] or "").strip())

    if "anotacion_down" in req:
        fields.append("anotacion_down = %s")
        values.append((req["anotacion_down"] or "").strip())

    if "active" in req and req["active"] is not None:
        fields.append("active = %s")
        values.append(bool(req["active"]))

    if not fields:
        return jsonify({"error": "Nada para actualizar"}), 400

    values.append(symbol)

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE acciones SET {', '.join(fields)} WHERE symbol = %s",
                tuple(values)
            )
            if cur.rowcount == 0:
                conn.close()
                return jsonify({"error": "No existe la acción"}), 404

    conn.close()
    save_log(f"Actualizada acción {symbol}")
    return jsonify({"ok": True})


@app.route("/api/delete", methods=["POST"])
def api_delete_action():
    req = request.json or {}
    symbol = (req.get("symbol") or "").upper().strip()
    if not symbol:
        return jsonify({"error": "symbol es obligatorio"}), 400

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM acciones WHERE symbol = %s", (symbol,))
    conn.close()

    save_log(f"Eliminada acción {symbol}")
    return jsonify({"ok": True})


# ============================================================
# API – SETTINGS (TOKEN + CHAT ID)
# ============================================================

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(get_settings())


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    req = request.json or {}
    token = (req.get("token") or "").strip()
    chat_id = (req.get("chat_id") or "").strip()

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO settings (id, token, chat_id)
                VALUES (TRUE, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET token = EXCLUDED.token,
                        chat_id = EXCLUDED.chat_id;
                """,
                (token, chat_id)
            )
    conn.close()

    save_log("Actualizados Telegram token/chat_id")
    return jsonify({"ok": True})


# ============================================================
# API – LOGS
# ============================================================

@app.route("/api/logs", methods=["GET"])
def api_get_logs():
    conn = get_db_connection()
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT created_at, text FROM logs ORDER BY created_at DESC LIMIT 200"
            )
            rows = cur.fetchall()
    conn.close()

    # Formato parecido al que tenías en texto
    lines = []
    for row in rows:
        ts = row["created_at"].astimezone(
            pytz.timezone("America/Argentina/Buenos_Aires")
        )
        stamp = ts.strftime("[%Y-%m-%d %H:%M] ")
        lines.append(stamp + row["text"])
    return jsonify(lines)


# ============================================================
# ROBOT 24/7
# ============================================================

def robot_loop():
    global robot_running
    tz_ar = pytz.timezone("America/Argentina/Buenos_Aires")
    last_run = set()

    save_log("Robot iniciado correctamente (PostgreSQL).")

    while robot_running:
        try:
            now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            now_ar = now_utc.astimezone(tz_ar)

            hm = (now_ar.hour, now_ar.minute)
            key = (now_ar.date(), now_ar.hour, now_ar.minute)

            if hm in CHECK_TIMES and key not in last_run:
                last_run.add(key)

                settings = get_settings()
                token = settings.get("token")
                chat_id = settings.get("chat_id")

                acciones = get_all_acciones()
                save_log(f"Chequeo programado → {now_ar.strftime('%H:%M')}")

                for row in acciones:
                    if not row["active"]:
                        continue

                    symbol = row["symbol"]
                    up_level = float(row["up"])
                    down_level = float(row["down"])
                    anot_up = row["anotacion_up"] or ""
                    anot_down = row["anotacion_down"] or ""

                    try:
                        data = yf.Ticker(symbol).history(period="1d", interval="1m")
                        precio = float(data["Close"].iloc[-1])
                    except Exception as e:
                        save_log(f"Error obteniendo precio de {symbol}: {e}")
                        continue

                    # Alza
                    if precio >= up_level:
                        msg = f"📈 {symbol} está por ENCIMA de {up_level:.2f} → {precio:.2f}"
                        if anot_up:
                            msg += f"\n📝 Nota: {anot_up}"
                        enviar_telegram(token, chat_id, msg)
                        save_log(msg)

                    # Baja
                    if precio <= down_level:
                        msg = f"📉 {symbol} está por DEBAJO de {down_level:.2f} → {precio:.2f}"
                        if anot_down:
                            msg += f"\n📝 Nota: {anot_down}"
                        enviar_telegram(token, chat_id, msg)
                        save_log(msg)

            time.sleep(30)

        except Exception as e:
            # Nunca matamos el hilo, sólo logueamos
            save_log(f"Error en robot_loop: {e}")
            time.sleep(30)


# Iniciar robot en thread
init_db()
threading.Thread(target=robot_loop, daemon=True).start()


# ============================================================
# RUTAS FLASK
# ============================================================

@app.route("/")
def index():
    # Sirve el dashboard mejorado
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
