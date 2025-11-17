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