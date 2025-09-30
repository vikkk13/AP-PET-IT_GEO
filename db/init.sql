-- =========================
-- Опциональные расширения
-- =========================
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Всегда работаем в public
SET search_path = public;

-- =========================
-- Пользователи (auth-service)
-- =========================
CREATE TABLE IF NOT EXISTS users (
    id       BIGSERIAL PRIMARY KEY,
    name     VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,                -- по ТЗ: без хеша
    role     VARCHAR(64)  NOT NULL                 -- admin | uploader | runner | viewer | exporter
);

-- Добавим столбец created, если его не было
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS created TIMESTAMPTZ NOT NULL DEFAULT now();

-- Необязательная защита значений роли (если нужно, раскомментируй)
-- ALTER TABLE users
--   ADD CONSTRAINT users_role_chk CHECK (role IN ('admin','uploader','runner','viewer','exporter'));

-- Администратор по умолчанию (idempotent)
INSERT INTO users (name, password, role)
VALUES ('admin','admin','admin')
ON CONFLICT (name) DO NOTHING;

-- =========================
-- Фото (photo-service)
-- =========================
CREATE TABLE IF NOT EXISTS photos (
    id         BIGSERIAL PRIMARY KEY,
    created    TIMESTAMPTZ NOT NULL DEFAULT now(),

    name       VARCHAR(512) NOT NULL,              -- сохранённое имя файла
    uuid       UUID UNIQUE NOT NULL,               -- логический идентификатор (в URL)

    width      INTEGER,
    height     INTEGER,

    exif_lat   DOUBLE PRECISION,
    exif_lon   DOUBLE PRECISION,

    type       VARCHAR(64),                        -- "Стройка" | "Мусор" ...
    subtype    VARCHAR(64),                        -- "ИНС" | "КИНС" | "Другое"

    shot_lat   DOUBLE PRECISION,
    shot_lon   DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_photos_uuid ON photos (uuid);
CREATE INDEX IF NOT EXISTS idx_photos_created ON photos (created DESC);
CREATE INDEX IF NOT EXISTS idx_photos_shot ON photos (shot_lat, shot_lon);

-- =========================
-- Найденные объекты (bbox + оценка)
-- =========================
CREATE TABLE IF NOT EXISTS detected_objects (
    id           BIGSERIAL PRIMARY KEY,
    photo_id     BIGINT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    label        VARCHAR(64) NOT NULL DEFAULT 'object',
    confidence   DOUBLE PRECISION DEFAULT 0.0,
    x1           INTEGER,
    y1           INTEGER,
    x2           INTEGER,
    y2           INTEGER,
    latitude     DOUBLE PRECISION,
    longitude    DOUBLE PRECISION,
    created      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_detected_photo_created ON detected_objects (photo_id, created DESC);
CREATE INDEX IF NOT EXISTS idx_detected_label ON detected_objects (label);
CREATE INDEX IF NOT EXISTS idx_detected_geo ON detected_objects (latitude, longitude);

-- =========================
-- История / журнал (опционально)
-- =========================
CREATE TABLE IF NOT EXISTS history (
    id       BIGSERIAL PRIMARY KEY,
    created  TIMESTAMPTZ NOT NULL DEFAULT now(),
    event    VARCHAR(64) NOT NULL,
    payload  JSONB
);

CREATE INDEX IF NOT EXISTS idx_history_event ON history (event, created DESC);
