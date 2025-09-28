import os
import psycopg
from flask import Flask, request, jsonify

app = Flask(__name__)

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'db')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

def get_conn():
    return psycopg.connect(DB_DSN)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "auth"}, 200

@app.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "viewer").strip()

    if not name or not password:
        return {"error": "name and password required"}, 400

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(name, password, role) VALUES (%s,%s,%s) RETURNING id, name, role",
                (name, password, role)
            )
            uid, uname, urole = cur.fetchone()
        return {"user": {"id": uid, "name": uname, "role": urole}}, 201
    except Exception as e:
        # вероятно дубликат имени
        return {"error": str(e)}, 400

@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    password = (data.get("password") or "").strip()

    if not name or not password:
        return {"error": "name and password required"}, 400

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, role FROM users WHERE name=%s AND password=%s", (name, password))
        row = cur.fetchone()

    if not row:
        return {"error": "invalid credentials"}, 401

    uid, uname, urole = row
    # НИКАКИХ токенов — просто возвращаем пользователя.
    return {"user": {"id": uid, "name": uname, "role": urole}}, 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
