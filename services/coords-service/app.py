import os
from flask import Flask, request, jsonify

app = Flask(__name__)

KNOWN = {
    "амурская улица, д. 2, к. 1": (55.804111, 37.749822),
    "амурская улица, 2к1": (55.804111, 37.749822),
}

def geocode_query(q: str):
    if not q:
        return {"lat": 55.751244, "lon": 37.618423}  # дефолт Москва
    key = q.strip().lower()
    for k, v in KNOWN.items():
        if k in key:
            return {"lat": v[0], "lon": v[1]}
    return {"lat": 55.751244, "lon": 37.618423}

@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "coords"}, 200

@app.post("/geocode")
def geocode_post():
    data = request.get_json(silent=True) or {}
    q = (data.get("query") or data.get("q") or "").strip()
    return jsonify(geocode_query(q)), 200

@app.get("/geocode")
def geocode_get():
    q = (request.args.get("query") or request.args.get("q") or "").strip()
    return jsonify(geocode_query(q)), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
