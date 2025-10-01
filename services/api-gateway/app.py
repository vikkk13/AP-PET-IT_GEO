import os
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from flask import Flask, request, redirect, send_from_directory, Response

AUTH_URL   = os.getenv("AUTH_URL",   "http://auth-service:5000")
PHOTO_URL  = os.getenv("PHOTO_URL",  "http://photo-service:5000")
COORDS_URL = os.getenv("COORDS_URL", "http://coords-service:5000")
EXPORT_URL = os.getenv("EXPORT_URL", "http://export-service:5000")
CALC_URL   = os.getenv("CALC_URL", "http://calc-service:5000")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

DROP_HEADERS = {
    "Content-Length","Transfer-Encoding","Connection","Keep-Alive",
    "Proxy-Authenticate","Proxy-Authorization","TE","Trailer","Upgrade",
    "Server","Date"
}
def relay(r: requests.Response) -> Response:
    headers = [(k, v) for k, v in r.headers.items() if k not in DROP_HEADERS]
    return Response(r.content, status=r.status_code, headers=headers)

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

# ---------- auth ----------
@app.post("/api/register")
def api_register():
    r = requests.post(urljoin(AUTH_URL, "/register"), json=request.get_json(silent=True) or {})
    return relay(r)

@app.post("/api/login")
def api_login():
    r = requests.post(urljoin(AUTH_URL, "/login"), json=request.get_json(silent=True) or {})
    return relay(r)


# ---------- users list (admin-only на сервере желательно) ----------
@app.get("/api/users")
def api_users():
    r = requests.get(urljoin(AUTH_URL, "/users"), params=request.args)
    return relay(r)


# ---------- photos / objects ----------
@app.get("/api/photos")
def api_photos():
    r = requests.get(urljoin(PHOTO_URL, "/photos"), params=request.args)
    return relay(r)



@app.post("/api/upload_zip")
def api_upload_zip():
    """
    Прокси массового импорта ZIP в photo-service.
    Поля формы:
      - archive: ZIP-файл (обязателен)
      - type/subtype/shot_lat/shot_lon: дефолты для всех фото (опц.)
    """
    if "archive" not in request.files:
        return {"error": "no file field 'archive'"}, 400

    files = {
        "archive": (
            request.files["archive"].filename,
            request.files["archive"].stream,
            request.files["archive"].mimetype or "application/zip"
        )
    }
    data = {}
    for key in ("type", "subtype", "shot_lat", "shot_lon"):
        v = request.form.get(key)
        if v not in (None, ""):
            data[key] = v

    r = requests.post(urljoin(PHOTO_URL, "/upload_zip"), data=data, files=files)
    return relay(r)


@app.get("/api/photos/<uuid_str>")
def api_photo_file(uuid_str: str):
    # тянем файл с photo-service изнутри (докер-сеть видит photo-service)
    upstream = requests.get(urljoin(PHOTO_URL, f"/photos/{uuid_str}"), stream=True)
    # собираем заголовки, но не отдаём опасные/лишние
    headers = []
    for k, v in upstream.headers.items():
        if k.lower() in {"content-length","transfer-encoding","connection","keep-alive",
                         "proxy-authenticate","proxy-authorization","te","trailer","upgrade",
                         "server","date"}:
            continue
        headers.append((k, v))
    return Response(upstream.content, status=upstream.status_code, headers=headers)

@app.get("/api/objects")
def api_objects():
    r = requests.get(urljoin(PHOTO_URL, "/objects"), params=request.args)
    return relay(r)

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
    data = {}
    for key in ("type", "subtype", "shot_lat", "shot_lon"):
        v = request.form.get(key)
        if v not in (None, ""):
            data[key] = v
    meta = request.files.get("meta")
    if meta and meta.filename:
        files["meta"] = (meta.filename, meta.stream, meta.mimetype or "application/json")
    r = requests.post(urljoin(PHOTO_URL, "/upload"), data=data, files=files)
    return relay(r)

# ---------- поиск по адресу (геокод -> поиск ближайших фото) ----------
@app.get("/api/search_address")
def api_search_addr():
    q = request.args.get("q", "")
    g = requests.post(urljoin(COORDS_URL, "/geocode"), json={"query": q})
    if g.status_code != 200:
        return relay(g)

    latlon = g.json() if g.text else {}
    params = {
        "lat": latlon.get("lat"),
        "lon": latlon.get("lon"),
        "limit": request.args.get("limit", 12),  # только топ-N ближайших
    }
    r = requests.get(urljoin(PHOTO_URL, "/search"), params=params)
    return relay(r)


@app.get("/api/search_coords")
def api_search_coords():
    # ожидает ?lat=..&lon=..&limit=12
    r = requests.get(urljoin(PHOTO_URL, "/search"), params=request.args)
    return relay(r)

@app.get("/api/search_name")
def api_search_name():
    # ожидает ?q=substring&limit=25&offset=0
    r = requests.get(urljoin(PHOTO_URL, "/search_by_name"), params=request.args)
    return relay(r)


# ---------- расчёт через calc-service + запись в photo-service ----------
@app.post("/api/calc_for_photo")
def api_calc_for_photo():
    """
    Вход: { "photo_id": 123, "method": 1, "seed": 42 }
    Вызывает calc-service /detect_batch, пишет детекции в photo-service /detect_bulk,
    и возвращает message + preview-URL через gateway.
    """
    payload = request.get_json(silent=True) or {}
    photo_id = payload.get("photo_id")
    method = int(payload.get("method", 1))
    seed   = payload.get("seed")

    if not photo_id:
        return {"error": "photo_id required"}, 400

    # 1) достаём метаданные фото
    meta = requests.get(urljoin(PHOTO_URL, f"/photo_meta"), params={"id": photo_id})
    if meta.status_code != 200:
        return relay(meta)
    p = meta.json()["photo"]
    uuid = p["uuid"]; shot_lat = p.get("shot_lat"); shot_lon = p.get("shot_lon")

    # 2) прямой URL до файла для calc-service (во внутренней сети)
    image_url = urljoin(PHOTO_URL, f"/photos/{uuid}")

    # 3) считаем на calc-service
    batch_req = {
        "method": method,
        "seed": seed,
        "images": [{"image_url": image_url, "lat": shot_lat, "lon": shot_lon}]
    }
    r = requests.post(urljoin(CALC_URL, "/detect_batch"), json=batch_req, timeout=120)
    if r.status_code != 200:
        return relay(r)
    calc = r.json()
    results = (calc.get("results") or [])
    if not results:
        return {"message": "Проанализирована 1 фото, обнаружено 0 объектов."}, 200

    r0 = results[0]
    dets = r0.get("detections") or []

    # 4) вставляем детекции пачкой в БД
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
    if ins.status_code not in (200,201):
        return {"error":"calc ok, but DB insert failed", "details": ins.text}, 500

    # 5) готовим превью-URL-ы (проксируем через /api/calc/photo)
    def proxify(u: str) -> str:
        # ждём формат .../photo?uuid=xxxx
        try:
            parsed = urlparse(u)
            uuid_vals = parse_qs(parsed.query).get("uuid", [])
            if uuid_vals:
                return f"/api/calc/photo?uuid={uuid_vals[0]}"
        except Exception:
            pass
        # fallback — вернём как есть
        return u

    processed_raw = r0.get("processed_image_url")  # от calc-service
    processed_url = proxify(processed_raw) if processed_raw else None

    single_urls = []
    for d in dets:
        su = d.get("single_photo_url")
        single_urls.append(proxify(su) if su else None)

    # 6) old-compatible message + new preview
    conf_pct = int((items[0].get("confidence", 0) * 100)) if items else 89
    return {
        "message": f"Проанализирована 1 фото, обнаружено {len(items)} дома(ов). Уверенность — {conf_pct}%.",
        "preview": {
            "processed_image_url": processed_url,   # общая картинка со всеми bbox
            "single_photos": single_urls            # по одному bbox на файле (опционально)
        }
    }, 200



@app.get("/api/calc/photo")
def api_calc_photo():
    # Проксируем /photo из calc-service (картинка с bbox по uuid)
    r = requests.get(urljoin(CALC_URL, "/photo"), params=request.args, stream=True)
    return relay(r)



@app.post("/api/calc_batch")
def api_calc_batch():
    data = request.get_json(silent=True) or {}
    ids = data.get("photo_ids") or []
    method = int(data.get("method", 1))
    seed = data.get("seed")
    if not ids:
        return {"error":"photo_ids required"}, 400

    # 1) тянем мета по всем id
    metas = []
    for pid in ids:
        m = requests.get(urljoin(PHOTO_URL, "/photo_meta"), params={"id": pid})
        if m.status_code == 200:
            p = m.json()["photo"]
            metas.append({
                "photo_id": pid,
                "image_url": urljoin(PHOTO_URL, f"/photos/{p['uuid']}"),
                "lat": p.get("shot_lat"), "lon": p.get("shot_lon")
            })

    # 2) calc-service
    images = [{"image_url": m["image_url"], "lat": m["lat"], "lon": m["lon"]} for m in metas]
    r = requests.post(urljoin(CALC_URL, "/detect_batch"), json={"method":method, "seed":seed, "images":images})
    if r.status_code != 200: return relay(r)
    calc = r.json()

    # 3) маппинг image_url -> photo_id
    url2id = {m["image_url"]: m["photo_id"] for m in metas}

    # 4) записываем всё в БД
    total = 0
    for res in calc.get("results") or []:
        pid = url2id.get(res.get("original_image_url"))
        items = []
        for d in res.get("detections") or []:
            bbox = d.get("bbox") or {}
            items.append({
                "photo_id": pid, "label":"house", "confidence": d.get("confidence",0),
                "bbox": {"x":bbox.get("x",10),"y":bbox.get("y",10),"w":bbox.get("w",100),"h":bbox.get("h",100)},
                "lat": d.get("lat"), "lon": d.get("lon")
            })
        if items:
            requests.post(urljoin(PHOTO_URL, "/detect_bulk"), json={"items": items})
            total += len(items)

    return {"message": f"Готово. Обработано {len(metas)} фото, найдено {total} объектов."}, 200


# ---------- экспорт ----------
@app.post("/api/export_xlsx")
def api_export_xlsx():
    payload = request.get_json(silent=True) or {}
    # основная цель — /export_xlsx
    r = requests.post(urljoin(EXPORT_URL, "/export_xlsx"), json=payload)
    # если на export-service такого роутa нет — пробуем старый /export
    if r.status_code == 404:
        r = requests.post(urljoin(EXPORT_URL, "/export"), json=payload)
    return relay(r)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
