
import os
import io
import csv
import json
import zipfile
import imghdr
import uuid as _uuid
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path
import random


import psycopg
from flask import Flask, request, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import openpyxl
except Exception:
    openpyxl = None

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'db')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads")).resolve()
INSTALL_DIR = Path(os.getenv("INSTALL_DIR", "/app/install")).resolve()
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/app/model")).resolve()
MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
CENTER_LAT = 55.804111
CENTER_LON = 37.749822


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def get_conn():
    return psycopg.connect(DB_DSN)

def ensure_schema():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id BIGSERIAL PRIMARY KEY,
                created TIMESTAMPTZ DEFAULT now(),
                name VARCHAR(512) NOT NULL,
                uuid UUID NOT NULL UNIQUE,
                width INTEGER,
                height INTEGER,
                exif_lat DOUBLE PRECISION,
                exif_lon DOUBLE PRECISION,
                type VARCHAR(64),
                subtype VARCHAR(64),
                shot_lat DOUBLE PRECISION,
                shot_lon DOUBLE PRECISION
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS detected_objects (
                id BIGSERIAL PRIMARY KEY,
                photo_id BIGINT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
                label VARCHAR(64) NOT NULL DEFAULT 'object',
                confidence DOUBLE PRECISION DEFAULT 0.0,
                x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                created TIMESTAMPTZ DEFAULT now()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id BIGSERIAL PRIMARY KEY,
                created TIMESTAMPTZ DEFAULT now(),
                event VARCHAR(64) NOT NULL,
                payload JSONB
            );
        """)
ensure_schema()

def _insert_history(event, payload):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO history(event,payload) VALUES (%s,%s)", (event, json.dumps(payload)))
    except Exception:
        pass

def _img_size(path: Path):
    if not Image:
        return None, None
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None, None

def _to_float(val):
    """Parse float that may have decimal comma."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _read_excel_meta(xlsx_path: Path):
    """Return mapping: filename -> {camera, lat, lon, ...} for Excel with RU headers."""
    meta = {}
    if not xlsx_path.exists():
        return meta
    if openpyxl:
        try:
            wb = openpyxl.load_workbook(xlsx_path, data_only=True)
            ws = wb.active
            # find columns by header names (case-insensitive, ru-friendly)
            headers = {}
            for j, cell in enumerate(ws[1], start=1):
                key = str(cell.value or "").strip().lower()
                headers[key] = j
            # common variants
            fn_col = headers.get("имя файла") or headers.get("filename") or headers.get("файл")
            cam_col = headers.get("camera") or headers.get("камера")
            lat_col = headers.get("latitude") or headers.get("широта")
            lon_col = headers.get("longitude") or headers.get("долгота")
            # iterate rows
            for i in range(2, ws.max_row + 1):
                name = ws.cell(i, fn_col).value if fn_col else None
                if not name:
                    continue
                camera = ws.cell(i, cam_col).value if cam_col else None
                lat = _to_float(ws.cell(i, lat_col).value) if lat_col else None
                lon = _to_float(ws.cell(i, lon_col).value) if lon_col else None
                meta[str(name).strip()] = {"camera": camera, "lat": lat, "lon": lon}
            return meta
        except Exception:
            pass
    # Fallback: try CSV with ; delimiter
    try:
        import csv
        with open(xlsx_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                name = (row.get("Имя файла") or row.get("filename") or row.get("файл") or "").strip()
                if not name:
                    continue
                cam = row.get("camera") or row.get("камера")
                lat = _to_float(row.get("latitude") or row.get("широта"))
                lon = _to_float(row.get("longitude") or row.get("долгота"))
                meta[name] = {"camera": cam, "lat": lat, "lon": lon}
    except Exception:
        pass
    return meta

def _read_json_results(json_path: Path):
    """
    Return mapping by filename (best-effort):
    - key could be by 'id' (e.g., id + '.jpg'), or by last path segment of 'image' + '.jpg'
    Each entry: {
       'shot_lat', 'shot_lon',
       'issues': [ { 'label','score','bbox':{x,y,w,h} } ... ]
    }
    """
    mapping = {}
    if not json_path.exists():
        return mapping
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        results = data.get("results") or []
        for rec in results:
            # filename guesses
            fname_guess = None
            if isinstance(rec.get("id"), str):
                fname_guess = rec["id"] + ".jpg"
            if not fname_guess and isinstance(rec.get("image"), str):
                tail = rec["image"].rstrip("/").split("/")[-1]
                if tail:
                    fname_guess = tail + ".jpg"
            shot_lat = _to_float(rec.get("latitude"))
            shot_lon = _to_float(rec.get("longitude"))
            issues = rec.get("issues") or []
            mapping[fname_guess] = {
                "lat": shot_lat, "lon": shot_lon, "issues": issues
            }
    except Exception:
        pass
    return mapping

def _save_photo_record(saved_name, uid, width, height, ptype, subtype, shot_lat, shot_lon):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO photos (name, uuid, width, height, type, subtype, shot_lat, shot_lon)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (uuid) DO NOTHING
            RETURNING id
        """, (saved_name, uid, width, height, ptype, subtype, shot_lat, shot_lon))
        row = cur.fetchone()
        if row:
            return row[0]
        # if conflict, fetch id
        cur.execute("SELECT id FROM photos WHERE uuid=%s", (uid,))
        row = cur.fetchone()
        return row[0] if row else None

def _import_from_install():
    # Run only if DB empty
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM photos")
        count = cur.fetchone()[0]
    if count > 0:
        return
    if not INSTALL_DIR.exists():
        return

    # model.zip → MODEL_DIR
    model_zip = INSTALL_DIR/"model.zip"
    if model_zip.exists():
        try:
            with zipfile.ZipFile(model_zip, "r") as z:
                z.extractall(MODEL_DIR)
        except Exception:
            pass

    imported = 0
    created_objects = 0

    # For each archive *.zip, find sidecar JSON and Excel by stem
    for arch in INSTALL_DIR.glob("*.zip"):
        stem = arch.stem
        json_path = INSTALL_DIR/f"{stem}.json"
        # handle multiple json variants; pick first that exists
        if not json_path.exists():
            # try other case
            candidates = list(INSTALL_DIR.glob(f"{stem}*.json"))
            json_path = candidates[0] if candidates else json_path
        excel_path = None
        for ext in ("xlsx","xls","csv"):
            p = INSTALL_DIR/f"{stem}.{ext}"
            if p.exists():
                excel_path = p
                break

        json_map = _read_json_results(json_path) if json_path and json_path.exists() else {}
        excel_map = _read_excel_meta(excel_path) if excel_path else {}

        # Extract archive into a temp
        try:
            with zipfile.ZipFile(arch, "r") as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    name = Path(info.filename).name
                    # only images
                    if not name.lower().endswith((".jpg",".jpeg",".png",".bmp",".gif",".tif",".tiff")):
                        continue
                    raw = z.read(info)
                    kind = imghdr.what(None, h=raw)
                    if kind not in {"jpeg","png","gif","tiff","bmp"}:
                        # try save anyway as jpg
                        kind = "jpeg"
                    # Use original name to keep linkage with Excel
                    saved_name = name
                    dest = UPLOAD_DIR / saved_name
                    if not dest.exists():
                        dest.write_bytes(raw)

                    width = height = None
                    if Image:
                        try:
                            from PIL import Image as _Image
                            with _Image.open(io.BytesIO(raw)) as im:
                                width, height = im.size
                        except Exception:
                            pass

                    # prefer coordinates and camera from Excel row; fallback to JSON
                    em = excel_map.get(name) or {}
                    jm = json_map.get(name) or {}
                    shot_lat = em.get("lat") if em.get("lat") is not None else jm.get("lat")
                    shot_lon = em.get("lon") if em.get("lon") is not None else jm.get("lon")
                    ptype = "unknown"
                    subtype = "unknown"

                    # UUID: use filename stem if it looks like UUID, else generate
                    try:
                        uid_val = str(_uuid.UUID(Path(name).stem))
                    except Exception:
                        uid_val = str(_uuid.uuid4())

                    pid = _save_photo_record(saved_name, uid_val, width, height, ptype, subtype, shot_lat, shot_lon)
                    if pid:
                        imported += 1
                        # Create detected_objects from JSON issues if any
                        issues = jm.get("issues") or []
                        for iss in issues:
                            bbox = iss.get("bbox") or {}
                            x = int(bbox.get("x", 10))
                            y = int(bbox.get("y", 10))
                            w = int(bbox.get("w", 100))
                            h = int(bbox.get("h", 100))
                            x1, y1, x2, y2 = x, y, x + w, y + h
                            conf = float(iss.get("score", 0.8))
                            lat = _to_float(iss.get("latitude"))
                            lon = _to_float(iss.get("longitude"))
                            if lat is None or lon is None:
                                lat, lon = shot_lat, shot_lon
                            with get_conn() as conn, conn.cursor() as cur:
                                cur.execute("""
                                    INSERT INTO detected_objects (photo_id,label,confidence,x1,y1,x2,y2,latitude,longitude)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (pid, iss.get("label") or "object", conf, x1,y1,x2,y2, lat, lon))
                                created_objects += 1

        except Exception as e:
            _insert_history("init_import_archive_error", {"archive": arch.name, "error": str(e)})

    _insert_history("init_import", {"imported_photos": imported, "created_objects": created_objects})

# Import on first boot
try:
    _import_from_install()
except Exception as e:
    _insert_history("init_import_error", {"error": str(e)})

import io, os, uuid, zipfile, json, math
from datetime import datetime
from flask import request, jsonify
from PIL import Image
import psycopg2

# константы/окружение
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ZIP_MAX_FILES = int(os.getenv("ZIP_MAX_FILES", "500"))
ZIP_MAX_UNCOMPRESSED_MB = int(os.getenv("ZIP_MAX_UNCOMPRESSED_MB", "1024"))  # ~1 GB
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'db')} port={os.getenv('POSTGRES_PORT', '5432')}"
)

def _ext(name: str) -> str:
    return os.path.splitext(name.lower())[-1]

def _safe_member_name(name: str) -> str:
    # защита от zip-slip: убираем абсолютные пути и подъемы ".."
    name = name.replace("\\", "/")
    name = name.lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)

def _read_img_dims(buf: bytes):
    with Image.open(io.BytesIO(buf)) as im:
        w, h = im.size
    return w, h

def _insert_photo(cur, stored_name, file_uuid, w, h, meta):
    cur.execute("""
        INSERT INTO photos (name, uuid, width, height, type, subtype, shot_lat, shot_lon)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created
    """, (
        stored_name, file_uuid, w, h,
        meta.get("type"), meta.get("subtype"),
        meta.get("lat"), meta.get("lon"),
    ))
    return cur.fetchone()  # (id, created)

def _merge_meta(defaults, manifest_entry, sidecar):
    """Приоритет: sidecar.json > manifest.json > defaults (из формы)"""
    out = dict(defaults or {})
    if manifest_entry:
        out.update({k: v for k, v in manifest_entry.items() if v not in (None, "")})
    if sidecar:
        out.update({k: v for k, v in sidecar.items() if v not in (None, "")})
    # нормализуем численные
    for k in ("lat", "lon"):
        if k in out:
            try: out[k] = float(out[k])
            except: out.pop(k, None)
    return out

@app.post("/upload_zip")
def upload_zip():
    """
    Массовый импорт ZIP.
    Поддерживаемые варианты метаданных для каждого фото:
      A) sidecar: <basename>.json рядом с картинкой
      B) manifest.json в корне архива:
           {
             "items": [
               {"file": "dir/photo1.jpg", "lat": ..., "lon": ..., "type": "...", "subtype": "..."},
               ...
             ]
           }
      C) defaults: поля формы (type, subtype, shot_lat, shot_lon)
    Приоритет: sidecar > manifest > defaults.
    """
    f = request.files.get("archive")
    if not f:
        return jsonify(error="no file field 'archive'"), 400

    defaults = {}
    if request.form.get("type"):     defaults["type"] = request.form["type"]
    if request.form.get("subtype"):  defaults["subtype"] = request.form["subtype"]
    if request.form.get("shot_lat"): defaults["lat"] = request.form["shot_lat"]
    if request.form.get("shot_lon"): defaults["lon"] = request.form["shot_lon"]

    # читаем zip в память (можно сделать временный файл, если архивы очень большие)
    data = f.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        return jsonify(error=f"bad zip: {e}"), 400

    names = [n for n in zf.namelist() if not n.endswith("/")]
    if len(names) > ZIP_MAX_FILES:
        return jsonify(error=f"too many files in zip (> {ZIP_MAX_FILES})"), 400

    # подсчёт суммарного распакованного размера и защита от zip bomb
    total_uncompressed = 0
    for zi in zf.infolist():
        total_uncompressed += zi.file_size
    if total_uncompressed > ZIP_MAX_UNCOMPRESSED_MB * 1024 * 1024:
        return jsonify(error=f"uncompressed size exceeds {ZIP_MAX_UNCOMPRESSED_MB} MB"), 400

    # читаем manifest.json (опционально)
    manifest_map = {}
    if "manifest.json" in names:
        try:
            raw = zf.read("manifest.json")
            m = json.loads(raw.decode("utf-8", "ignore"))
            for it in (m.get("items") or []):
                fname = _safe_member_name(it.get("file") or "")
                if fname:
                    manifest_map[fname] = it
        except Exception:
            # игнорируем битый манифест
            manifest_map = {}

    results = []
    errors = []

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    try:
        with conn, conn.cursor() as cur:
            for member in names:
                safe_name = _safe_member_name(member)
                ext = _ext(safe_name)
                if ext not in ALLOWED_EXTS:
                    # пробуем как sidecar json — пропускаем, но не ошибка
                    if ext == ".json":
                        continue
                    errors.append({"file": member, "error": "unsupported extension"})
                    continue

                try:
                    # sidecar по базовому имени (file.jpg -> file.json) относительно каталога
                    base, _ = os.path.splitext(safe_name)
                    sidecar_json = None
                    if f"{base}.json" in names:
                        try:
                            sidecar_raw = zf.read(f"{base}.json")
                            sidecar_json = json.loads(sidecar_raw.decode("utf-8", "ignore"))
                        except Exception:
                            sidecar_json = None

                    manifest_entry = manifest_map.get(safe_name)
                    meta = _merge_meta(defaults, manifest_entry, sidecar_json)

                    # читаем картинку
                    img_bytes = zf.read(member)
                    w, h = _read_img_dims(img_bytes)

                    file_uuid = str(uuid.uuid4())
                    stored_name = f"{file_uuid}{ext}"
                    out_path = os.path.join(UPLOAD_DIR, stored_name)

                    # сохраняем файл
                    with open(out_path, "wb") as out:
                        out.write(img_bytes)

                    # insert
                    pid, created = _insert_photo(cur, stored_name, file_uuid, w, h, meta)

                    results.append({
                        "file": member,
                        "id": pid,
                        "uuid": file_uuid,
                        "name": stored_name,
                        "width": w,
                        "height": h,
                        "lat": meta.get("lat"),
                        "lon": meta.get("lon"),
                        "type": meta.get("type"),
                        "subtype": meta.get("subtype"),
                        "created": created.isoformat() if isinstance(created, datetime) else str(created),
                    })

                except Exception as e:
                    errors.append({"file": member, "error": str(e)})
            # если дошли сюда — коммитим
            conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify(error=str(e)), 500
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "imported": len(results),
        "skipped": len(errors),
        "results": results,
        "errors": errors
    })


@app.errorhandler(RequestEntityTooLarge)
def too_large(e):
    return {"error": f"file too large (> {MAX_CONTENT_LENGTH//1024//1024} MB)"}, 413

@app.get("/healthz")
def healthz():
    return {"status":"ok","service":"photo"}

@app.get("/photos")
def photos_list():
    # pagination: /photos?limit=50&offset=0
    try:
        limit = int(request.args.get("limit", "50"))
    except Exception:
        limit = 50
    try:
        offset = int(request.args.get("offset", "0"))
    except Exception:
        offset = 0
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    with get_conn() as conn, conn.cursor() as cur:
        # 1) Считаем общее количество (для total)
        cur.execute("SELECT COUNT(*) FROM photos")
        total = cur.fetchone()[0]

        # 2) Отдаём текущую страницу
        cur.execute("""
            SELECT id, uuid::text, name, width, height, created, type, subtype, shot_lat, shot_lon
            FROM photos
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        rows = cur.fetchall()

    return {
        "total": total,
        "photos": [
            {"id": r[0], "uuid": r[1], "name": r[2], "width": r[3], "height": r[4],
             "created": r[5].isoformat(), "type": r[6], "subtype": r[7],
             "shot_lat": r[8], "shot_lon": r[9]}
            for r in rows
        ]
    }

@app.get("/photos/<uuid_str>")
def photo_file(uuid_str: str):
    try:
        _ = _uuid.UUID(uuid_str)
    except Exception:
        abort(404)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM photos WHERE uuid=%s", (uuid_str,))
        row = cur.fetchone()
        if not row:
            abort(404)
        fname = row[0]
    return send_from_directory(UPLOAD_DIR, fname, as_attachment=False)

@app.post("/upload")
def upload():
    """
    multipart/form-data:
      image: файл изображения (обязательно)
      type: строка (опц.)
      subtype: строка (опц.)
      meta: json-файл с {"lat": ..., "lon": ...} (опц.)
      shot_lat / shot_lon: числа (если meta не приложен)
    """
    if "image" not in request.files:
        return {"error":"no file field 'image'"}, 400
    f = request.files["image"]
    if f.filename == "":
        return {"error":"empty filename"}, 400

    ptype = (request.form.get("type") or "unknown")[:64]
    subtype = (request.form.get("subtype") or "unknown")[:64]

    shot_lat = request.form.get("shot_lat")
    shot_lon = request.form.get("shot_lon")
    if "meta" in request.files and request.files["meta"].filename:
        try:
            meta_data = json.load(io.TextIOWrapper(request.files["meta"].stream, encoding="utf-8"))
            shot_lat = meta_data.get("lat", shot_lat)
            shot_lon = meta_data.get("lon", shot_lon)
        except Exception:
            pass

    try:
        shot_lat = _to_float(shot_lat) if shot_lat is not None else None
        shot_lon = _to_float(shot_lon) if shot_lon is not None else None
    except Exception:
        shot_lat = shot_lon = None

    raw = f.read()
    if not raw:
        return {"error":"empty file"}, 400
    kind = imghdr.what(None, h=raw)
    if kind not in {"jpeg","png","gif","tiff","bmp"}:
        return {"error":"unsupported image"}, 415

    # сохраняем с оригинальным именем (чтобы коррелировало с excel/json), если уникально
    orig_name = secure_filename(f.filename)
    saved_name = orig_name
    dest = UPLOAD_DIR / saved_name
    i = 1
    while dest.exists():
        # уникализируем
        stem = Path(orig_name).stem
        ext = Path(orig_name).suffix or (".jpg" if kind=="jpeg" else f".{kind}")
        saved_name = f"{stem}_{i}{ext}"
        dest = UPLOAD_DIR / saved_name
        i += 1
    with open(dest, "wb") as out:
        out.write(raw)

    width = height = None
    if Image:
        try:
            from PIL import Image as _Image
            with _Image.open(io.BytesIO(raw)) as im:
                width, height = im.size
        except Exception:
            pass

    # UUID — из имени, если возможно
    try:
        uid_val = str(_uuid.UUID(Path(saved_name).stem))
    except Exception:
        uid_val = str(_uuid.uuid4())

    pid = _save_photo_record(saved_name, uid_val, width, height, ptype, subtype, shot_lat, shot_lon)

    return {"photo": {"id": pid, "uuid": uid_val, "name": saved_name, "width": width, "height": height,
                      "type": ptype, "subtype": subtype, "shot_lat": shot_lat, "shot_lon": shot_lon}}, 201

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dl/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

@app.get("/search")
def search_by_coords():
    """GET /search?lat=..&lon=..&limit=12  -> топ-N ближайших фото (по dist_m)"""
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except Exception:
        return {"error":"lat/lon required"}, 400

    try:
        limit = int(request.args.get("limit", "12"))
    except Exception:
        limit = 12
    limit = max(1, min(limit, 200))

    # тянем все фото с координатами
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, uuid::text, name, shot_lat, shot_lon
            FROM photos
            WHERE shot_lat IS NOT NULL AND shot_lon IS NOT NULL
        """)
        rows = cur.fetchall()

    # считаем расстояние до каждой точки и берём топ-N
    items = []
    for pid, uid, name, slat, slon in rows:
        dist = haversine_m(lat, lon, float(slat), float(slon))
        items.append({
            "id": pid, "uuid": uid, "name": name,
            "dist_m": dist, "shot_lat": slat, "shot_lon": slon
        })

    items.sort(key=lambda x: x["dist_m"])
    res = items[:limit]

    _insert_history("search_knn", {"lat": lat, "lon": lon, "limit": limit, "returned": len(res)})
    return {"results": res}


@app.post("/calc_for_photo")
def calc_for_photo():
    """
    Имитация модели: для указанного photo_id создать 2 "house"
    с bbox-ами и координатами вокруг (CENTER_LAT, CENTER_LON) ±50 м.
    """
    data = request.get_json(silent=True) or {}
    try:
        photo_id = int(data.get("photo_id"))
    except Exception:
        return {"error": "photo_id required"}, 400

    # Убедимся, что фото существует (ширина/высота не обязательны)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM photos WHERE id=%s", (photo_id,))
        row = cur.fetchone()
        if not row:
            return {"error": "photo not found"}, 404

        # Функция «дрожания» координат на ±meters
        def jitter(lat, lon, meters=50.0):
            dlat = (random.uniform(-meters, meters)) / 111320.0
            dlng = (random.uniform(-meters, meters)) / (111320.0 * max(cos(radians(lat)), 1e-6))
            return lat + dlat, lon + dlng

        # Два произвольных bbox'а и координаты вокруг центра
        dets = []
        for bx in [(10,10,120,120), (140,20,260,180)]:
            lat, lon = jitter(CENTER_LAT, CENTER_LON, 50.0)
            dets.append({"label":"house","confidence":0.89,"bbox":bx,"lat":lat,"lon":lon})

        # Сохраняем в БД
        for d in dets:
            x1,y1,x2,y2 = d["bbox"]
            cur.execute("""
                INSERT INTO detected_objects
                    (photo_id,label,confidence,x1,y1,x2,y2,latitude,longitude)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (photo_id, d["label"], d["confidence"], x1,y1,x2,y2, d["lat"], d["lon"]))

    _insert_history("calc", {"photo_id": photo_id, "created": 2})
    return {"message": "Проанализирована 1 фото, обнаружено 2 дома. Уверенность — 89%."}, 200


# --- NEW: metadata for a single photo by id
@app.get("/photo_meta")
def photo_meta():
    try:
        photo_id = int(request.args.get("id", "0"))
    except Exception:
        return {"error": "id required"}, 400
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, uuid::text, name, width, height, shot_lat, shot_lon, created
            FROM photos WHERE id=%s
        """, (photo_id,))
        row = cur.fetchone()
        if not row:
            return {"error":"photo not found"}, 404
        return {
            "photo": {
                "id": row[0], "uuid": row[1], "name": row[2],
                "width": row[3], "height": row[4],
                "shot_lat": row[5], "shot_lon": row[6],
                "created": row[7].isoformat() if row[7] else None
            }
        }

# --- NEW: insert one detection
@app.post("/detect")
def detect_insert():
    data = request.get_json(silent=True) or {}
    try:
        photo_id = int(data.get("photo_id"))
    except Exception:
        return {"error": "photo_id required"}, 400

    label = (data.get("label") or "house")[:64]
    conf = float(data.get("confidence") or 0.0)

    # Поддержка форматов bbox: либо массив [x1,y1,x2,y2], либо поля x1..y2, либо JSON {x,y,w,h}
    x1 = data.get("x1"); y1 = data.get("y1"); x2 = data.get("x2"); y2 = data.get("y2")
    bbox = data.get("bbox")
    if isinstance(bbox, dict) and all(k in bbox for k in ("x","y","w","h")):
        x1 = int(bbox["x"]); y1 = int(bbox["y"])
        x2 = x1 + int(bbox["w"]); y2 = y1 + int(bbox["h"])

    try:
        x1 = int(x1); y1 = int(y1); x2 = int(x2); y2 = int(y2)
    except Exception:
        return {"error":"invalid bbox"}, 400

    lat = data.get("lat") or data.get("latitude")
    lon = data.get("lon") or data.get("longitude")
    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
    except Exception:
        lat = lon = None

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO detected_objects (photo_id,label,confidence,x1,y1,x2,y2,latitude,longitude)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (photo_id, label, conf, x1,y1,x2,y2, lat, lon))
        new_id = cur.fetchone()[0]
    return {"id": new_id}, 201

# --- NEW: bulk insert
@app.post("/detect_bulk")
def detect_bulk():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    inserted = 0
    with get_conn() as conn, conn.cursor() as cur:
        for it in items:
            try:
                photo_id = int(it.get("photo_id"))
                label = (it.get("label") or "house")[:64]
                conf = float(it.get("confidence") or 0.0)
                bbox = it.get("bbox")
                x1 = it.get("x1"); y1 = it.get("y1"); x2 = it.get("x2"); y2 = it.get("y2")
                if isinstance(bbox, dict) and all(k in bbox for k in ("x","y","w","h")):
                    x1 = int(bbox["x"]); y1 = int(bbox["y"])
                    x2 = x1 + int(bbox["w"]); y2 = y1 + int(bbox["h"])
                x1 = int(x1); y1 = int(y1); x2 = int(x2); y2 = int(y2)
                lat = it.get("lat") or it.get("latitude")
                lon = it.get("lon") or it.get("longitude")
                lat = float(lat) if lat is not None else None
                lon = float(lon) if lon is not None else None
            except Exception:
                continue

            cur.execute("""
                INSERT INTO detected_objects (photo_id,label,confidence,x1,y1,x2,y2,latitude,longitude)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (photo_id, label, conf, x1,y1,x2,y2, lat, lon))
            inserted += 1
    return {"inserted": inserted}, 200



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5002")))
