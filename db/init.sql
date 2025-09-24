CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,          -- без хеша, по требованию ТЗ
    role VARCHAR(64) NOT NULL                -- admin | uploader | runner | viewer | exporter
);

CREATE TABLE IF NOT EXISTS photos (
    id BIGSERIAL PRIMARY KEY,
    created     TIMESTAMPTZ DEFAULT now(),
    updated     TIMESTAMPTZ DEFAULT now(),
    deleted     BOOLEAN     DEFAULT FALSE,

    uuid        UUID UNIQUE NOT NULL,
    orig_name   VARCHAR(512) NOT NULL,
    stored_name VARCHAR(512) NOT NULL,   -- <uuid>.<ext>
    mime_type   VARCHAR(128),
    size_bytes  BIGINT,

    type1       VARCHAR(32),             -- "мусор" | "стройка"
    type2       VARCHAR(32),             -- "КИНС" | "ИНС" | "Другое"

    building    VARCHAR(255),            -- краткое описание здания
    address     VARCHAR(512),            -- почтовый адрес
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,

    source      VARCHAR(64)              -- источник изображения (для фильтра)
);

CREATE INDEX IF NOT EXISTS idx_photos_uuid ON photos (uuid);
CREATE INDEX IF NOT EXISTS idx_photos_geo  ON photos (latitude, longitude);

-- История запросов (пространства запросов)
CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    name VARCHAR(255),
    created TIMESTAMPTZ DEFAULT now(),
    filter JSONB
);

-- история запросов пользователей
CREATE TABLE IF NOT EXISTS queries (
    id       BIGSERIAL PRIMARY KEY,
    user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name     VARCHAR(255) NOT NULL,
    filter   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_queries_user_created ON queries (user_id, created DESC);
