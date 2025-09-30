
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5002")))
