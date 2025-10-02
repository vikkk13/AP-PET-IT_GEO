import os
from urllib.parse import urljoin, urlparse, parse_qs
from typing import Iterable, Tuple, Dict, Any

import requests
from flask import Flask, request, send_from_directory, Response, jsonify, stream_with_context

# -----------------------------------------------------------------------------
# Upstreams (внутрисетевые адреса контейнеров)
# -----------------------------------------------------------------------------
AUTH_URL   = os.getenv("AUTH_URL",   "http://auth-service:5000")
PHOTO_URL  = os.getenv("PHOTO_URL",  "http://photo-service:5000")  # photo-service слушает 5000
COORDS_URL = os.getenv("COORDS_URL", "http://coords-service:5000")
EXPORT_URL = os.getenv("EXPORT_URL", "http://export-service:5000")
CALC_URL   = os.getenv("CALC_URL",   "http://calc-service:5000")

# -----------------------------------------------------------------------------
# Flask
# -----------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

# Заголовки, которые нельзя слать клиенту «как есть» от апстрима
DROP_HEADERS = {
    "content-length", "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer", "upgrade",
    "server", "date"
}

DEFAULT_TIMEOUT = (5, 60)  # (connect, read)

def _filter_headers(h: Dict[str, str]) -> Iterable[Tuple[str, str]]:
    return [(k, v) for k, v in h.items() if k.lower() not in DROP_HEADERS]

def _relay_bytes(r: requests.Response) -> Response:
    """Проксируем небинарный/мелкий ответ (r.content)."""
    return Response(r.content, status=r.status_code, headers=_filter_headers(r.headers))

def _relay_stream(r: requests.Response) -> Response:
    """Проксируем бинарный/крупный ответ стримом."""
    def generate():
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                yield chunk
    return Response(stream_with_context(generate()), status=r.status_code, headers=_filter_headers(r.headers))

# -----------------------------------------------------------------------------
# Health & статика
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
    r = requests.post(urljoin(AUTH_URL, "/register"),
                      json=request.get_json(silent=True) or {},
                      timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

@app.post("/api/login")
def api_login():
    r = requests.post(urljoin(AUTH_URL, "/login"),
                      json=request.get_json(silent=True) or {},
                      timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

@app.get("/api/users")
def api_users():
    r = requests.get(urljoin(AUTH_URL, "/users"),
                     params=request.args,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

# -----------------------------------------------------------------------------
# Photos
# -----------------------------------------------------------------------------
@app.get("/api/photos")
def api_photos():
    # NB: проксируем на /photos (без /api)
    r = requests.get(f"{PHOTO_URL}/photos",
                     params=request.args,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

@app.get("/api/photos/<uuid>")
def api_photo_file(uuid: str):
    # Стримом — чтобы не буферизовать большие файлы
    r = requests.get(f"{PHOTO_URL}/photos/{uuid}",
                     params=None,
                     stream=True,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_stream(r)

@app.post("/api/upload")
def api_upload():
    if "image" not in request.files:
        return {"error": "no file field 'image'"}, 400

    files = {
        "image": (
            request.files["image"].filename,
            request.files["image"].stream,
            request.files["image"].mimetype or "application/octet-stream"
        )
    }
    if "meta" in request.files and request.files["meta"].filename:
        meta = request.files["meta"]
        files["meta"] = (meta.filename, meta.stream, meta.mimetype or "application/json")

    data = {}
    for key in ("type", "subtype", "shot_lat", "shot_lon"):
        v = request.form.get(key)
        if v not in (None, ""):
            data[key] = v

    r = requests.post(urljoin(PHOTO_URL, "/upload"),
                      data=data,
                      files=files,
                      timeout=(10, 120))
    return _relay_bytes(r)

@app.post("/api/upload_zip")
def api_upload_zip():
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

    r = requests.post(urljoin(PHOTO_URL, "/upload_zip"),
                      data=data,
                      files=files,
                      timeout=(10, 300))
    return _relay_bytes(r)

@app.get("/api/objects")
def api_objects():
    r = requests.get(urljoin(PHOTO_URL, "/objects"),
                     params=request.args,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------
@app.get("/api/search_address")
def api_search_addr():
    q = request.args.get("q", "")
    g = requests.post(urljoin(COORDS_URL, "/geocode"),
                      json={"query": q},
                      timeout=DEFAULT_TIMEOUT)
    if g.status_code != 200:
        return _relay_bytes(g)

    latlon = g.json() if g.text else {}
    params = {
        "lat": latlon.get("lat"),
        "lon": latlon.get("lon"),
        "limit": request.args.get("limit", 12),
    }
    r = requests.get(urljoin(PHOTO_URL, "/search_coords"),
                     params=params,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

@app.get("/api/search_coords")
def api_search_coords():
    r = requests.get(urljoin(PHOTO_URL, "/search_coords"),
                     params=request.args,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

@app.get("/api/search_name")
def api_search_name():
    r = requests.get(urljoin(PHOTO_URL, "/search_by_name"),
                     params=request.args,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_bytes(r)

# -----------------------------------------------------------------------------
# Calc
# -----------------------------------------------------------------------------
@app.post("/api/calc_for_photo")
def api_calc_for_photo():
    payload = request.get_json(silent=True) or {}
    photo_id = payload.get("photo_id")
    method = int(payload.get("method", 1))
    seed   = payload.get("seed")

    if not photo_id:
        return {"error": "photo_id required"}, 400

    meta = requests.get(urljoin(PHOTO_URL, "/photo_meta"),
                        params={"id": photo_id},
                        timeout=DEFAULT_TIMEOUT)
    if meta.status_code != 200:
        return _relay_bytes(meta)
    p = meta.json()["photo"]
    uuid = p["uuid"]; shot_lat = p.get("shot_lat"); shot_lon = p.get("shot_lon")

    image_url = urljoin(PHOTO_URL, f"/photos/{uuid}")

    try:
        batch_req = {
            "method": method,
            "seed": seed,
            "images": [{"image_url": image_url, "lat": shot_lat, "lon": shot_lon}]
        }
        r = requests.post(urljoin(CALC_URL, "/detect_batch"),
                          json=batch_req,
                          timeout=(10, 180))
        if r.status_code != 200:
            raise RuntimeError(f"calc-service status {r.status_code}: {r.text[:256]}")
        calc = r.json()
        results = (calc.get("results") or [])
        if not results:
            return {"message": "Проанализирована 1 фото, обнаружено 0 объектов."}, 200

        r0 = results[0]
        dets = r0.get("detections") or []

        items = []
        for d in dets:
            bbox = d.get("bbox") or {}
            items.append({
                "photo_id": photo_id,
                "label": "house",
                "confidence": d.get("confidence", 0.0),
                "bbox": {"x": bbox.get("x", 10), "y": bbox.get("y", 10),
                         "w": bbox.get("w", 100), "h": bbox.get("h", 100)},
                "lat": d.get("lat"),
                "lon": d.get("lon")
            })
        ins = requests.post(urljoin(PHOTO_URL, "/detect_bulk"),
                            json={"items": items},
                            timeout=DEFAULT_TIMEOUT)
        if ins.status_code not in (200, 201):
            return {"error": "calc ok, but DB insert failed", "details": ins.text}, 500

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
        sim = requests.post(urljoin(PHOTO_URL, "/calc_for_photo"),
                            json={"photo_id": photo_id},
                            timeout=DEFAULT_TIMEOUT)
        if sim.status_code != 200:
            return _relay_bytes(sim)
        data = sim.json() if sim.text else {}
        return {
            "message": data.get("message", "Готово"),
            "preview": {"processed_image_url": None, "single_photos": []}
        }, 200

@app.get("/api/calc/photo")
def api_calc_photo():
    r = requests.get(urljoin(CALC_URL, "/photo"),
                     params=request.args,
                     stream=True,
                     timeout=DEFAULT_TIMEOUT)
    return _relay_stream(r)

@app.post("/api/calc_batch")
def api_calc_batch():
    data = request.get_json(silent=True) or {}
    ids = data.get("photo_ids") or []
    method = int(data.get("method", 1))
    seed = data.get("seed")
    if not ids:
        return {"error": "photo_ids required"}, 400

    metas = []
    for pid in ids:
        m = requests.get(urljoin(PHOTO_URL, "/photo_meta"),
                         params={"id": pid},
                         timeout=DEFAULT_TIMEOUT)
        if m.status_code == 200 and m.text:
            p = m.json()["photo"]
            metas.append({
                "photo_id": pid,
                "image_url": urljoin(PHOTO_URL, f"/photos/{p['uuid']}"),
                "lat": p.get("shot_lat"),
                "lon": p.get("shot_lon")
            })

    images = [{"image_url": m["image_url"], "lat": m["lat"], "lon": m["lon"]} for m in metas]
    r = requests.post(urljoin(CALC_URL, "/detect_batch"),
                      json={"method": method, "seed": seed, "images": images},
                      timeout=(10, 300))
    if r.status_code != 200:
        return _relay_bytes(r)
    calc = r.json()

    url2id = {m["image_url"]: m["photo_id"] for m in metas}
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
                "bbox": {"x": bbox.get("x", 10), "y": bbox.get("y", 10),
                         "w": bbox.get("w", 100), "h": bbox.get("h", 100)},
                "lat": d.get("lat"),
                "lon": d.get("lon")
            })
        if items:
            requests.post(urljoin(PHOTO_URL, "/detect_bulk"),
                          json={"items": items},
                          timeout=DEFAULT_TIMEOUT)
            total += len(items)

    return {"message": f"Готово. Обработано {len(metas)} фото, найдено {total} объектов."}, 200

# -----------------------------------------------------------------------------
# Export
# -----------------------------------------------------------------------------
@app.post("/api/export_xlsx")
def api_export_xlsx():
    payload = request.get_json(silent=True) or {}
    r = requests.post(urljoin(EXPORT_URL, "/export_xlsx"),
                      json=payload,
                      timeout=(10, 180))
    if r.status_code == 404:  # backward-compat
        r = requests.post(urljoin(EXPORT_URL, "/export"),
                          json=payload,
                          timeout=(10, 180))
    return _relay_bytes(r)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
