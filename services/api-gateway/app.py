import os
import requests
from flask import Flask, request, Response
from flask_cors import CORS

app = Flask(__name__)
# Разрешим фронту с 8081 ходить к нам на 8080
CORS(app, resources={r"/*": {"origins": ["http://localhost:8081", "http://127.0.0.1:8081"]}})

AUTH_URL   = os.getenv("AUTH_URL",   "http://auth-service:5000")
PHOTO_URL  = os.getenv("PHOTO_URL",  "http://photo-service:5000")
COORDS_URL = os.getenv("COORDS_URL", "http://coords-service:5000")
CALC_URL   = os.getenv("CALC_URL",   "http://calc-service:5000")
EXPORT_URL = os.getenv("EXPORT_URL", "http://export-service:5000")

TIMEOUT = (10, 300)  # (connect, read)

def _pipe(resp):
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, resp.status_code, headers)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

# ---------------- PHOTO ----------------
@app.get("/photo/healthz")
def photo_health():
    r = requests.get(f"{PHOTO_URL}/healthz", timeout=10)
    return _pipe(r)

@app.post("/photo/upload_photo")
def gw_upload_photo():
    files = None
    if "file" in request.files:
        f = request.files["file"]
        files = {"file": (f.filename, f.stream, f.mimetype)}
    data = request.form.to_dict(flat=True)
    r = requests.post(f"{PHOTO_URL}/upload_photo", files=files, data=data, timeout=TIMEOUT)
    return _pipe(r)

@app.post("/photo/upload_photos")
def gw_upload_photos():
    files = [("files", (f.filename, f.stream, f.mimetype)) for f in request.files.getlist("files")]
    data = request.form.to_dict(flat=True)
    r = requests.post(f"{PHOTO_URL}/upload_photos", files=files, data=data, timeout=TIMEOUT)
    return _pipe(r)

@app.get("/photo/list")
def gw_list_photos():
    r = requests.get(f"{PHOTO_URL}/list", params=request.args, timeout=TIMEOUT)
    return _pipe(r)

@app.get("/photo/uploads/<path:name>")
def gw_get_upload(name):
    # проксируем бинарник (картинку) стримом
    upstream = requests.get(f"{PHOTO_URL}/uploads/{name}", stream=True, timeout=TIMEOUT)
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}
    return Response(upstream.iter_content(8192), status=upstream.status_code, headers=headers)

# ---------------- COORDS ----------------
@app.post("/coords/upload_coords")
def gw_upload_coords():
    r = requests.post(f"{COORDS_URL}/upload_coords", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

@app.get("/coords/search_by_addr")
def gw_search_by_addr():
    r = requests.get(f"{COORDS_URL}/search_by_addr", params=request.args, timeout=TIMEOUT)
    return _pipe(r)

# ---------------- AUTH ----------------
@app.post("/auth/register")
def gw_register():
    r = requests.post(f"{AUTH_URL}/register", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

@app.post("/auth/login")
def gw_login():
    r = requests.post(f"{AUTH_URL}/login", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

@app.post("/auth/save_query")
def gw_save_query():
    r = requests.post(f"{AUTH_URL}/save_query", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

@app.get("/auth/history/<int:user_id>")
def gw_history(user_id):
    r = requests.get(f"{AUTH_URL}/history/{user_id}", timeout=TIMEOUT)
    return _pipe(r)

# ---------------- CALC ----------------
@app.post("/calc/calc")
def gw_calc():
    r = requests.post(f"{CALC_URL}/calc", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

# ---------------- EXPORT ----------------
@app.post("/export/export")
def gw_export():
    r = requests.post(f"{EXPORT_URL}/export", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)


@app.post("/auth/admin/create_user")
def gw_admin_create_user():
    r = requests.post(f"{AUTH_URL}/admin/create_user", json=request.get_json(silent=True), timeout=TIMEOUT)
    return _pipe(r)

@app.get("/auth/admin/users")
def gw_admin_users():
    r = requests.get(f"{AUTH_URL}/admin/users", params=request.args, timeout=TIMEOUT)
    return _pipe(r)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
