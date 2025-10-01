import os
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from flask import Flask, request, send_from_directory, Response, jsonify

AUTH_URL   = os.getenv("AUTH_URL",   "http://auth-service:5000")
PHOTO_URL  = os.getenv("PHOTO_URL",  "http://photo-service:5002")  # порт photo-service из нового app.py по умолчанию 5002
COORDS_URL = os.getenv("COORDS_URL", "http://coords-service:5000")
EXPORT_URL = os.getenv("EXPORT_URL", "http://export-service:5000")
CALC_URL   = os.getenv("CALC_URL",   "http://calc-service:5000")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

DROP_HEADERS = {
    "content-length","transfer-encoding","connection","keep-alive",
    "proxy-authenticate","proxy-authorization","te","trailer","upgrade",
    "server","date"
}

def relay(r: requests.Response) -> Response:
    """Пробрасываем ответ апстрима с безопасными заголовками."""
    headers = [(k, v) for k, v in r.headers.items() if k.lower() not in DROP_HEADERS]
    return Response(r.content, status=r.status_code, headers=headers)

# -----------------------------------------------------------------------------
# Статика и health
# -----------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "api-gateway"}, 200

@app.get("/")
def root():
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(idx):
        return send_from_directory(STATIC_DIR, "index.html")
    return {"ok": True, "service": "api-gateway"}, 200

@app.get("/favicon.ico")
def favicon():
    p = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(p):
        return send_from_directory(STATIC_DIR, "favicon.ico")
    return ("", 204)

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
@app.post("/api/register")
def api_register():
    r = requests.post(urljoin(AUTH_URL, "/register"), json=request.get_json(silent=True) or {})
    return relay(r)

@app.post("/api/login")
def api_login():
    r = requests.post(urljoin(AUTH_URL, "/login"), json=request.get_json(silent=True) or {})
    return relay(r)

@app.get("/api/users")
def api_users():
    r = requests.get(urljoin(AUTH_URL, "/users"), params=request.args)
    return relay(r)

# -----------------------------------------------------------------------------
# Photos
# -----------------------------------------------------------------------------
@app.get("/api/photos")
def api_photos():
    # Прямо проксируем с параметрами (limit/offset/has_coords/date_from/date_to)
    r = requests.get(urljoin(PHOTO_URL, "/photos"), params=request.args)
    return relay(r)

@app.get("/api/photos/<uuid_str>")
def api_photo_file(uuid_str: str):
    # Проксирование бинарного файла (из внутренней сети) с сохранением Content-Type
    upstream = requests.get(urljoin(PHOTO_URL, f"/photos/{uuid_str}"), stream=True)
    headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in DROP_HEADERS]
    return Response(upstream.content, status=upstream.status_code, headers=headers)

@app.post("/api/upload")
def api_upload():
    if "image" not in request.files:
        return {"error": "no file field 'image'"}, 400

    files = {
        "image": (
            request.files["image"].filename,
            request.files["image"].stream,
            request.files["image"].mimetype
        )
    }
    meta = request.files.get("meta")
    if meta and meta.filename:
        files["meta"] = (meta.filename, meta.stream, meta.mimetype or "application/json")

    data = {}
    for key in ("type", "subtype", "shot_lat", "shot_lon"):
        v = request.form.get(key)
        if v not in (None, ""):
            data[key] = v

    r = requests.post(urljoin(PHOTO_URL, "/upload"), data=data, files=files)
    return relay(r)

@app.post("/api/upload_zip")
def api_upload_zip():
    """
    Массовый импорт в photo-service.
    Поддерживаем поля: 'archive' ИЛИ 'zip' (оба — ок).
    Доп. поля: type, subtype, shot_lat, shot_lon.
    """
    f = request.files.get("archive") or request.files.get("zip")
    if not f:
        return {"error": "no file field 'archive' or 'zip'"}, 400

    field_name = "archive" if "archive" in request.files else "zip"
    files = {
        field_name: (
            f.filename,
            f.stream,
            f.mimetype or "application/zip"
        )
    }
    data = {}
    for key in ("type", "subtype", "shot_lat", "shot_lon"):
        v = request.form.get(key)
        if v not in (None, ""):
            data[key] = v

    r = requests.post(urljoin(PHOTO_URL, "/upload_zip"), data=data, files=files)
    return relay(r)

# (оставлен для совместимости; сервер может и не иметь /objects)
@app.get("/api/objects")
def api_objects():
    r = requests.get(urljoin(PHOTO_URL, "/objects"), params=request.args)
    return relay(r)

# -----------------------------------------------------------------------------
# Поиск
# -----------------------------------------------------------------------------
@app.get("/api/search_address")
def api_search_addr():
    """
    Геокодим адрес в coords-service, затем запрашиваем топ-N ближайших фото.
    """
    q = request.args.get("q", "")
    g = requests.post(urljoin(COORDS_URL, "/geocode"), json={"query": q})
    if g.status_code != 200:
        return relay(g)

    latlon = g.json() if g.text else {}
    params = {
        "lat": latlon.get("lat"),
        "lon": latlon.get("lon"),
        "limit": request.args.get("limit", 12),
    }
    r = requests.get(urljoin(PHOTO_URL, "/search_coords"), params=params)
    return relay(r)

@app.get("/api/search_coords")
def api_search_coords():
    # ожидает ?lat=..&lon=..&limit=12
    r = requests.get(urljoin(PHOTO_URL, "/search_coords"), params=request.args)
    return relay(r)

# (не используется фронтом, оставлен на будущее — может вернуть 404 на photo-service)
@app.get("/api/search_name")
def api_search_name():
    r = requests.get(urljoin(PHOTO_URL, "/search_by_name"), params=request.args)
    return relay(r)

# -----------------------------------------------------------------------------
# Calc: основной путь через calc-service + fallback в photo-service
# -----------------------------------------------------------------------------
@app.post("/api/calc_for_photo")
def api_calc_for_photo():
    """
    Вход: { "photo_id": 123, "method": 1, "seed": 42 }
    1) Берём метаданные фото из photo-service.
    2) Шлём batch в calc-service -> получаем bbox'ы и (опц.) превью.
    3) Пишем детекции в photo-service (/detect_bulk).
    4) Возвращаем message + preview (проксированные URL'ы).
    Fallback: если calc-service недоступен — вызываем photo-service /calc_for_photo.
    """
    payload = request.get_json(silent=True) or {}
    photo_id = payload.get("photo_id")
    method = int(payload.get("method", 1))
    seed   = payload.get("seed")

    if not photo_id:
        return {"error": "photo_id required"}, 400

    # 1) мета фото
    meta = requests.get(urljoin(PHOTO_URL, "/photo_meta"), params={"id": photo_id})
    if meta.status_code != 200:
        return relay(meta)
    p = meta.json()["photo"]
    uuid = p["uuid"]; shot_lat = p.get("shot_lat"); shot_lon = p.get("shot_lon")

    # 2) image_url для calc-service
    image_url = urljoin(PHOTO_URL, f"/photos/{uuid}")

    # 3) основной путь — calc-service
    try:
        batch_req = {
            "method": method,
            "seed": seed,
            "images": [{"image_url": image_url, "lat": shot_lat, "lon": shot_lon}]
        }
        r = requests.post(urljoin(CALC_URL, "/detect_batch"), json=batch_req, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"calc-service status {r.status_code}: {r.text[:256]}")
        calc = r.json()
        results = (calc.get("results") or [])
        if not results:
            return {"message": "Проанализирована 1 фото, обнаружено 0 объектов."}, 200

        r0 = results[0]
        dets = r0.get("detections") or []

        # 4) запись детекций в БД
        items = []
        for d in dets:
            bbox = d.get("bbox") or {}
            items.append({
                "photo_id": photo_id,
                "label": "house",
                "confidence": d.get("confidence", 0.0),
                "bbox": {"x": bbox.get("x",10), "y": bbox.get("y",10),
                         "w": bbox.get("w",100), "h": bbox.get("h",100)},
                "lat": d.get("lat"),
                "lon": d.get("lon")
            })
        ins = requests.post(urljoin(PHOTO_URL, "/detect_bulk"), json={"items": items})
        if ins.status_code not in (200, 201):
            return {"error":"calc ok, but DB insert failed", "details": ins.text}, 500

        # 5) превью — проксируемые URL’ы
        def proxify(u: str) -> str:
            try:
                parsed = urlparse(u)
                uuid_vals = parse_qs(parsed.query).get("uuid", [])
                if uuid_vals:
                    return f"/api/calc/photo?uuid={uuid_vals[0]}"
            except Exception:
                pass
            return u

        processed_raw = r0.get("processed_image_url")
        processed_url = proxify(processed_raw) if processed_raw else None

        single_urls = []
        for d in dets:
            su = d.get("single_photo_url")
            single_urls.append(proxify(su) if su else None)

        conf_pct = int((items[0].get("confidence", 0) * 100)) if items else 89
        return {
            "message": f"Проанализирована 1 фото, обнаружено {len(items)} дома(ов). Уверенность — {conf_pct}%.",
            "preview": {
                "processed_image_url": processed_url,
                "single_photos": single_urls
            }
        }, 200

    except Exception:
        # --- Fallback: симуляция в photo-service ---
        sim = requests.post(urljoin(PHOTO_URL, "/calc_for_photo"), json={"photo_id": photo_id})
        if sim.status_code != 200:
            return relay(sim)
        # совместимость с фронтом: вернём message, превью может отсутствовать
        data = sim.json() if sim.text else {}
        return {
            "message": data.get("message", "Готово"),
            "preview": {
                "processed_image_url": None,
                "single_photos": []
            }
        }, 200

@app.get("/api/calc/photo")
def api_calc_photo():
    # Проксируем картинку превью из calc-service по uuid
    r = requests.get(urljoin(CALC_URL, "/photo"), params=request.args, stream=True)
    headers = [(k, v) for k, v in r.headers.items() if k.lower() not in DROP_HEADERS]
    return Response(r.content, status=r.status_code, headers=headers)

@app.post("/api/calc_batch")
def api_calc_batch():
    data = request.get_json(silent=True) or {}
    ids = data.get("photo_ids") or []
    method = int(data.get("method", 1))
    seed = data.get("seed")
    if not ids:
        return {"error": "photo_ids required"}, 400

    # 1) мета
    metas = []
    for pid in ids:
        m = requests.get(urljoin(PHOTO_URL, "/photo_meta"), params={"id": pid})
        if m.status_code == 200:
            p = m.json()["photo"]
            metas.append({
                "photo_id": pid,
                "image_url": urljoin(PHOTO_URL, f"/photos/{p['uuid']}"),
                "lat": p.get("shot_lat"),
                "lon": p.get("shot_lon")
            })

    # 2) calc-service
    images = [{"image_url": m["image_url"], "lat": m["lat"], "lon": m["lon"]} for m in metas]
    r = requests.post(urljoin(CALC_URL, "/detect_batch"), json={"method": method, "seed": seed, "images": images})
    if r.status_code != 200:
        return relay(r)
    calc = r.json()

    # 3) маппинг url -> id
    url2id = {m["image_url"]: m["photo_id"] for m in metas}

    # 4) запись в БД
    total = 0
    for res in calc.get("results") or []:
        pid = url2id.get(res.get("original_image_url"))
        if not pid:
            continue
        items = []
        for d in res.get("detections") or []:
            bbox = d.get("bbox") or {}
            items.append({
                "photo_id": pid,
                "label": "house",
                "confidence": d.get("confidence", 0.0),
                "bbox": {"x": bbox.get("x",10), "y": bbox.get("y",10),
                         "w": bbox.get("w",100), "h": bbox.get("h",100)},
                "lat": d.get("lat"),
                "lon": d.get("lon")
            })
        if items:
            requests.post(urljoin(PHOTO_URL, "/detect_bulk"), json={"items": items})
            total += len(items)

    return {"message": f"Готово. Обработано {len(metas)} фото, найдено {total} объектов."}, 200

# -----------------------------------------------------------------------------
# Export
# -----------------------------------------------------------------------------
@app.post("/api/export_xlsx")
def api_export_xlsx():
    payload = request.get_json(silent=True) or {}
    r = requests.post(urljoin(EXPORT_URL, "/export_xlsx"), json=payload)
    if r.status_code == 404:  # backward-compat
        r = requests.post(urljoin(EXPORT_URL, "/export"), json=payload)
    return relay(r)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
