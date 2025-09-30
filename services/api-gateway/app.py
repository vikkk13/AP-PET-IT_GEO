import os
from urllib.parse import urljoin
import requests
from flask import Flask, request, redirect, send_from_directory, Response

AUTH_URL   = os.getenv("AUTH_URL",   "http://auth-service:5000")
PHOTO_URL  = os.getenv("PHOTO_URL",  "http://photo-service:5000")
COORDS_URL = os.getenv("COORDS_URL", "http://coords-service:5000")
EXPORT_URL = os.getenv("EXPORT_URL", "http://export-service:5000")

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


# ---------- «расчёт координат» (имитация) ----------
@app.post("/api/calc_for_photo")
def api_calc_for_photo():
    r = requests.post(urljoin(PHOTO_URL, "/calc_for_photo"), json=request.get_json(silent=True) or {})
    return relay(r)

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
