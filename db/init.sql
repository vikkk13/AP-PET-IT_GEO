-- =========[ опционально ]=========
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================
-- Пользователи
-- =========================
CREATE TABLE IF NOT EXISTS users (
    id       BIGSERIAL PRIMARY KEY,
    name     VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,      -- без хэша (по ТЗ)
    role     VARCHAR(64)  NOT NULL       -- admin | uploader | runner | viewer | exporter
);

-- Администратор по умолчанию
INSERT INTO users (name, password, role)
VALUES ('admin','admin','admin')
ON CONFLICT (name) DO NOTHING;

-- =========================
-- Фото (как ожидает photo-service)
-- =========================
CREATE TABLE IF NOT EXISTS photos (
    id         BIGSERIAL PRIMARY KEY,
    created    TIMESTAMPTZ DEFAULT now(),

    -- базовые поля, которые использует код
    name       VARCHAR(512) NOT NULL,    -- имя сохранённого файла (stored), в коде — saved_name
    uuid       UUID UNIQUE NOT NULL,     -- логический идентификатор файла (используется в URL)

    -- опционально: размер картинки (используется экспортом/отладкой)
    width      INTEGER,
    height     INTEGER,

    -- опционально: сырые exif (сейчас не заполняются, но оставим)
    exif_lat   DOUBLE PRECISION,
    exif_lon   DOUBLE PRECISION,

    -- типы под сценарий
    type       VARCHAR(64),              -- например: "стройка" | "мусор"
    subtype    VARCHAR(64),              -- например: "ИНС" | "КИНС"

    -- координаты точки съёмки (то, что код называет shot_lat / shot_lon)
    shot_lat   DOUBLE PRECISION,
    shot_lon   DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_photos_uuid ON photos (uuid);
CREATE INDEX IF NOT EXISTS idx_photos_shot ON photos (shot_lat, shot_lon);

-- =========================
-- Найденные объекты (bbox + оценка)
-- =========================
CREATE TABLE IF NOT EXISTS detected_objects (
    id           BIGSERIAL PRIMARY KEY,
    photo_id     BIGINT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    label        VARCHAR(64) NOT NULL DEFAULT 'object',
    confidence   DOUBLE PRECISI
