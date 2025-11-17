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
        base_price NUMERIC,
        up NUMERIC NOT NULL,
        down NUMERIC NOT NULL,
        anotacion_up TEXT,
        anotacion_down TEXT,
        alert_up_sent BOOLEAN NOT NULL DEFAULT FALSE,
        alert_down_sent BOOLEAN NOT NULL DEFAULT FALSE,
        active BOOLEAN NOT NULL DEFAULT TRUE
    );

    -- Por si la tabla ya existía con el esquema viejo:
    ALTER TABLE acciones
        ADD COLUMN IF NOT EXISTS base_price NUMERIC;
    ALTER TABLE acciones
        ADD COLUMN IF NOT EXISTS alert_up_sent BOOLEAN NOT NULL DEFAULT FALSE;
    ALTER TABLE acciones
        ADD COLUMN IF NOT EXISTS alert_down_sent BOOLEAN NOT NULL DEFAULT FALSE;

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


def reset_alerts_for_symbol(symbol):
    """Resetea las banderas de alerta para una acción (por si se ajusta la configuración)."""
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE acciones SET alert_up_sent = FALSE, alert_down_sent = FALSE WHERE symbol = %s",
                (symbol,)
            )
    conn.close()


# ============================================================
# API – ACCIONES
# ============================================================

@app.route("/api/actions", methods=["GET"])
def api_get_actions():
    acciones = get_all_acciones()
    # Respuesta tipo dict por symbol
    data = {}
    for row in acciones:
        data[row["symbol"]] = {
            "base_price": float(row["base_price"]) if row["base_price"] is not None else None,
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
    base_price = req.get("base_price")
    up = req.get("up")
    down = req.get("down")
    anotacion_up = (req.get("anotacion_up") or "").strip()
    anotacion_down = (req.get("anotacion_down") or "").strip()

    if not symbol or base_price is None or up is None or down is None:
        return jsonify({"error": "symbol, base_price, up y down son obligatorios"}), 400

    try:
        base_price = float(base_price)
        up = float(up)
        down = float(down)
    except ValueError:
        return jsonify({"error": "base_price, up y down deben ser numéricos"}), 400

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acciones (symbol, base_price, up, down, anotacion_up, anotacion_down, alert_up_sent, alert_down_sent, active)
                VALUES (%s, %s, %s, %s, %s, %s, FALSE, FALSE, TRUE)
                ON CONFLICT (symbol) DO UPDATE
                SET base_price   = EXCLUDED.base_price,
                    up           = EXCLUDED.up,
                    down         = EXCLUDED.down,
                    anotacion_up = EXCLUDED.anotacion_up,
                    anotacion_down = EXCLUDED.anotacion_down,
                    alert_up_sent   = FALSE,
                    alert_down_sent = FALSE,
                    active       = TRUE;
                """,
                (symbol, base_price, up, down, anotacion_up, anotacion_down)
            )
    conn.close()

    save_log(f"Añadida/Actualizada acción {symbol} (base={base_price}, up={up}, down={down})")
    return jsonify({"ok": True})


@app.route("/api/update", methods=["POST"])
def api_update_action():
    req = request.json or {}
    symbol = (req.get("symbol") or "").upper().strip()
    if not symbol:
        return jsonify({"error": "symbol es obligatorio"}), 400

    fields = []
    values = []

    if "base_price" in req and req["base_price"] is not None:
        fields.append("base_price = %s")
        values.append(float(req["base_price"]))

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

    # Siempre que se actualice algo, reseteamos las alertas
    fields.append("alert_up_sent = FALSE")
    fields.append("alert_down_sent = FALSE")

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

    lines = []
    for row in rows:
        ts = row["created_at"].astimezone(
            pytz.timezone("America/Argentina/Buenos_Aires")
        )
        stamp = ts.strftime("[%Y-%m-%d %H:%M] ")
        lines.append(stamp + row["text"])
    return jsonify(lines)


# ============================================================
# ROBOT 24/7 (LÓGICA NUEVA: RANGO CON MEMORIA)
# ============================================================

def procesar_accion(row, precio_actual):
    """
    Devuelve (tipo_alerta, mensaje) o (None, None)
    tipo_alerta: "ALZA" / "BAJA"
    """
    symbol = row["symbol"]
    base_price = row.get("base_price")
    up_level = float(row["up"])
    down_level = float(row["down"])
    anot_up = row["anotacion_up"] or ""
    anot_down = row["anotacion_down"] or ""
    alert_up_sent = bool(row.get("alert_up_sent"))
    alert_down_sent = bool(row.get("alert_down_sent"))

    # Porcentaje vs precio base (si se cargó)
    cambio_pct = None
    if base_price is not None:
        try:
            base_f = float(base_price)
            if base_f != 0:
                cambio_pct = (precio_actual - base_f) / base_f * 100.0
        except Exception:
            cambio_pct = None

    tipo = None
    msg = None

    # ⚡ ALERTA ALZA: rompe techo y todavía no avisó
    if precio_actual >= up_level and not alert_up_sent:
        tipo = "ALZA"
        msg = f"📈 {symbol} rompió el techo de {up_level:.2f} → {precio_actual:.2f}"
        if base_price is not None and cambio_pct is not None:
            msg += f"\nPrecio base: {base_f:.2f} ({cambio_pct:+.2f}%)"
        if anot_up:
            msg += f"\n📝 Nota alza: {anot_up}"

    # ⚡ ALERTA BAJA: rompe piso y todavía no avisó
    elif precio_actual <= down_level and not alert_down_sent:
        tipo = "BAJA"
        msg = f"📉 {symbol} rompió el piso de {down_level:.2f} → {precio_actual:.2f}"
        if base_price is not None and cambio_pct is not None:
            msg += f"\nPrecio base: {base_f:.2f} ({cambio_pct:+.2f}%)"
        if anot_down:
            msg += f"\n📝 Nota baja: {anot_down}"

    return tipo, msg


def robot_loop():
    global robot_running
    tz_ar = pytz.timezone("America/Argentina/Buenos_Aires")
    last_run = set()

    save_log("Robot iniciado correctamente (PostgreSQL, lógica de rango).")

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

                conn = get_db_connection()
                with conn:
                    with conn.cursor() as cur:
                        for row in acciones:
                            if not row["active"]:
                                continue

                            symbol = row["symbol"]

                            # Obtener precio actual
                            try:
                                data = yf.Ticker(symbol).history(period="1d", interval="1m")
                                precio = float(data["Close"].iloc[-1])
                            except Exception as e:
                                save_log(f"Error obteniendo precio de {symbol}: {e}")
                                continue

                            tipo_alerta, msg = procesar_accion(row, precio)

                            if msg:
                                enviar_telegram(token, chat_id, msg)
                                save_log(msg)

                                # Marcar bandera correspondiente para no repetir alerta
                                if tipo_alerta == "ALZA":
                                    cur.execute(
                                        "UPDATE acciones SET alert_up_sent = TRUE WHERE id = %s",
                                        (row["id"],)
                                    )
                                elif tipo_alerta == "BAJA":
                                    cur.execute(
                                        "UPDATE acciones SET alert_down_sent = TRUE WHERE id = %s",
                                        (row["id"],)
                                    )

                conn.close()

            time.sleep(30)

        except Exception as e:
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
