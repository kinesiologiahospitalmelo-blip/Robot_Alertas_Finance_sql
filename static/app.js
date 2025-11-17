const api = (endpoint, method = "GET", data = null) => {
    return fetch(endpoint, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: data ? JSON.stringify(data) : null,
    }).then((r) => r.json());
};

// ================= TABS =================
document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.onclick = () => {
        document
            .querySelectorAll(".tab-btn")
            .forEach((b) => b.classList.remove("active"));
        document
            .querySelectorAll(".tab")
            .forEach((t) => t.classList.remove("active"));

        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
    };
});

// ================= ACCIONES =================
function renderActions(data) {
    const container = document.getElementById("acciones-list");
    if (!data || Object.keys(data).length === 0) {
        container.innerHTML = `<p class="hint">Todavía no hay acciones configuradas.</p>`;
        return;
    }

    let html = "";
    for (let symbol in data) {
        const info = data[symbol];

        html += `
        <div class="card">
            <div class="card-header">
                <h3>${symbol}</h3>
                <span class="badge ${info.active ? "badge-on" : "badge-off"}">
                    ${info.active ? "ACTIVA" : "INACTIVA"}
                </span>
            </div>
            <div class="card-body">
                <p><b>Precio base:</b> ${info.base_price ?? "-"}</p>
                <p><b>Alza (techo):</b> ${info.up}</p>
                <p><b>Baja (piso):</b> ${info.down}</p>
                ${
                    info.anotacion_up
                        ? `<p>📝 <b>Nota alza:</b> ${info.anotacion_up}</p>`
                        : ""
                }
                ${
                    info.anotacion_down
                        ? `<p>📝 <b>Nota baja:</b> ${info.anotacion_down}</p>`
                        : ""
                }
            </div>
            <div class="card-footer">
                <button onclick="toggleAction('${symbol}', ${!info.active})">
                    ${info.active ? "Desactivar" : "Activar"}
                </button>
                <button onclick="prefillAction(
                    '${symbol}',
                    ${info.base_price ?? "null"},
                    ${info.up},
                    ${info.down},
                    ${JSON.stringify(info.anotacion_up || "")},
                    ${JSON.stringify(info.anotacion_down || "")}
                )">
                    Editar
                </button>
                <button class="danger" onclick="deleteAction('${symbol}')">
                    Eliminar
                </button>
            </div>
        </div>`;
    }

    container.innerHTML = html;
}

function loadActions() {
    api("/api/actions").then(renderActions);
}

function toggleAction(symbol, state) {
    api("/api/update", "POST", { symbol: symbol, active: state }).then(loadActions);
}

function deleteAction(symbol) {
    if (!confirm(`¿Eliminar la acción ${symbol}?`)) return;
    api("/api/delete", "POST", { symbol: symbol }).then(loadActions);
}

function prefillAction(symbol, base_price, up, down, anot_up, anot_down) {
    document.getElementById("new-symbol").value = symbol;
    document.getElementById("new-base").value = base_price ?? "";
    document.getElementById("new-up").value = up;
    document.getElementById("new-down").value = down;
    document.getElementById("new-note-up").value = anot_up || "";
    document.getElementById("new-note-down").value = anot_down || "";
}

// ================= GUARDAR / EDITAR ACCIÓN =================
document.getElementById("btn-add").onclick = () => {
    const s = document.getElementById("new-symbol").value.toUpperCase();
    const b = document.getElementById("new-base").value;
    const u = document.getElementById("new-up").value;
    const d = document.getElementById("new-down").value;
    const nu = document.getElementById("new-note-up").value;
    const nd = document.getElementById("new-note-down").value;

    if (!s || !b || !u || !d) {
        alert("Ticker, precio base, precio alza y precio baja son obligatorios.");
        return;
    }

    api("/api/add", "POST", {
        symbol: s,
        base_price: b,
        up: u,
        down: d,
        anotacion_up: nu,
        anotacion_down: nd,
    }).then(() => {
        document.getElementById("new-symbol").value = "";
        document.getElementById("new-base").value = "";
        document.getElementById("new-up").value = "";
        document.getElementById("new-down").value = "";
        document.getElementById("new-note-up").value = "";
        document.getElementById("new-note-down").value = "";
        loadActions();
    });
};

loadActions();

// ================= TELEGRAM =================
function loadSettings() {
    api("/api/settings").then((s) => {
        if (s.token) document.getElementById("tg-token").value = s.token;
        if (s.chat_id) document.getElementById("tg-chat").value = s.chat_id;
    });
}

document.getElementById("btn-save-tg").onclick = () => {
    const token = document.getElementById("tg-token").value;
    const chat = document.getElementById("tg-chat").value;

    api("/api/settings", "POST", { token: token, chat_id: chat }).then(() =>
        alert("Telegram guardado.")
    );
};

document.getElementById("btn-test-tg").onclick = () => {
    api("/api/settings").then((s) => {
        if (!s.token || !s.chat_id) {
            alert("Primero guarda el token y chat_id.");
            return;
        }
        fetch(
            `https://api.telegram.org/bot${s.token}/sendMessage?chat_id=${s.chat_id}&text=Test desde Robot Alertas Finance SQL`
        );
        alert("Mensaje de prueba enviado (si los datos son correctos).");
    });
};

loadSettings();

// ================= LOGS =================
function loadLogs() {
    api("/api/logs").then((logs) => {
        document.getElementById("logs-box").textContent = logs.join("\n");
    });
}

document.getElementById("btn-refresh-logs").onclick = loadLogs;

loadLogs();
