import os
import uuid as _uuid
import mimetypes
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename
from flask_cors import CORS
import psycopg2

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

# -------- Settings --------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/uploads")  # в docker-compose смонтирован volume
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'db')} "          # локально можно поставить 'localhost'
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


# -------- DB migrate (idempotent) --------
def ensure_photos_table():
    """Создаёт/добавляет недостающие колонки, безопасно вызывать при каждом старте."""
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id BIGSERIAL PRIMARY KEY,
            created     TIMESTAMPTZ DEFAULT now(),
            updated     TIMESTAMPTZ DEFAULT now(),
            deleted     BOOLEAN     DEFAULT FALSE,

            uuid        UUID UNIQUE NOT NULL,
            orig_name   VARCHAR(512) NOT NULL,
            stored_name VARCHAR(512) NOT NULL,
            mime_type   VARCHAR(128),
            size_bytes  BIGINT,

            type1       VARCHAR(32),
            type2       VARCHAR(32),

            latitude    DOUBLE PRECISION,
            longitude   DOUBLE PRECISION
        );
    """)
    # Добавим недостающие поля, если база старая
    cur.execute("""
        ALTER TABLE photos ADD COLUMN IF NOT EXISTS building VARCHAR(255);
        ALTER TABLE photos ADD COLUMN IF NOT EXISTS address  VARCHAR(512);
        ALTER TABLE photos ADD COLUMN IF NOT EXISTS source   VARCHAR(64);
        CREATE INDEX IF NOT EXISTS idx_photos_uuid ON photos (uuid);
        CREATE INDEX IF NOT EXISTS idx_photos_geo  ON photos (latitude, longitude);
    """)
    conn.commit()
    cur.close()
    conn.close()


ensure_photos_table()


# -------- Helpers --------
def _bad_type(ext: str) -> bool:
    return ext.lower() not in ALLOWED


# -------- Routes --------
@app.get("/healthz")
def healthz():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.post("/upload_photo")
def upload_photo():
    """Загрузка одного фото."""
    if "file" not in request.files:
        return {"error": "file required"}, 400

    type1 = request.form.get("type1")
    type2 = request.form.get("type2")
    building = request.form.get("building") or None
    address = request.form.get("address") or None
    source = request.form.get("source") or "manual"

    if type1 not in ("мусор", "стройка"):
        return {"error": "type1 must be 'мусор' or 'стройка'"}, 400
    if type2 not in ("ИНС", "КИНС", "Другое"):
        return {"error": "type2 must be 'ИНС'|'КИНС'|'Другое'"}, 400

    f = request.files["file"]
    orig = secure_filename(f.filename or "")
    if not orig:
        return {"error": "empty filename"}, 400
    ext = os.path.splitext(orig)[1].lower()
    if _bad_type(ext):
        return {"error": f"unsupported file type {ext}"}, 400

    uid = _uuid.uuid4()
    stored = f"{uid}{ext}"
    out_path = os.path.join(UPLOAD_DIR, stored)
    f.save(out_path)

    size_bytes = os.path.getsize(out_path)
    mime = f.mimetype or mimetypes.guess_type(out_path)[0] or "application/octet-stream"

    # координаты — заглушка, расчёт в отдельном сервисе
    latitude, longitude = 0.0, 0.0

    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO photos (uuid, orig_name, stored_name, mime_type, size_bytes,
                                type1, type2, building, address, latitude, longitude, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, created
        """, (str(uid), orig, stored, mime, size_bytes,
              type1, type2, building, address, latitude, longitude, source))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    return {
        "status": "ok",
        "id": row[0],
        "uuid": str(uid),
        "created": row[1].isoformat(),
        "stored_name": stored,
        "url": f"/uploads/{stored}",
        "type1": type1, "type2": type2,
        "building": building, "address": address,
        "lat": latitude, "lon": longitude
    }


@app.post("/upload_photos")
def upload_photos():
    """
    Мультизагрузка фото.
    form-data:
      files[] (несколько файлов), type1, type2, building?, address?, source?
    """
    files = request.files.getlist("files")
    if not files:
        return {"error": "files[] required"}, 400

    type1 = request.form.get("type1")
    type2 = request.form.get("type2")
    building = request.form.get("building") or None
    address = request.form.get("address") or None
    source = request.form.get("source") or "manual"

    if type1 not in ("мусор", "стройка"):
        return {"error": "type1 must be 'мусор' or 'стройка'"}, 400
    if type2 not in ("ИНС", "КИНС", "Другое"):
        return {"error": "type2 must be 'ИНС'|'КИНС'|'Другое'"}, 400

    results = []
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()

        for f in files[:50]:  # простой лимит партии
            orig = secure_filename(f.filename or "")
            if not orig:
                results.append({"error": "empty filename"})
                continue
            ext = os.path.splitext(orig)[1].lower()
            if _bad_type(ext):
                results.append({"filename": orig, "error": f"unsupported type {ext}"})
                continue

            uid = _uuid.uuid4()
            stored = f"{uid}{ext}"
            out_path = os.path.join(UPLOAD_DIR, stored)
            f.save(out_path)

            size_bytes = os.path.getsize(out_path)
            mime = f.mimetype or mimetypes.guess_type(out_path)[0] or "application/octet-stream"
            latitude, longitude = 0.0, 0.0  # заглушка

            cur.execute("""
                INSERT INTO photos (uuid, orig_name, stored_name, mime_type, size_bytes,
                                    type1, type2, building, address, latitude, longitude, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, created
            """, (str(uid), orig, stored, mime, size_bytes,
                  type1, type2, building, address, latitude, longitude, source))
            row = cur.fetchone()

            results.append({
                "status": "ok",
                "id": row[0],
                "uuid": str(uid),
                "created": row[1].isoformat(),
                "stored_name": stored,
                "url": f"/uploads/{stored}",
                "type1": type1, "type2": type2,
                "building": building, "address": address
            })

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    return jsonify({"items": results})


@app.get("/list")
def list_items():
    limit = int(request.args.get("limit", 50))
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, uuid::text, stored_name, type1, type2, building, address, latitude, longitude, created
            FROM photos
            WHERE deleted = FALSE
            ORDER BY created DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    return {"items": [{
        "id": r[0],
        "uuid": r[1],
        "stored_name": r[2],
        "url": (None if r[2] == "-" else f"/uploads/{r[2]}"),
        "type1": r[3], "type2": r[4],
        "building": r[5], "address": r[6],
        "lat": r[7], "lon": r[8],
        "created": r[9].isoformat() if r[9] else None
    } for r in rows]}


@app.get("/uploads/<path:name>")
def get_upload(name):
    return send_from_directory(UPLOAD_DIR, name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PHOTO_PORT", 5000)), debug=False)
