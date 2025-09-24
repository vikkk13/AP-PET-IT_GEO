import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

def ensure_users_table():
    """Доводим структуру users до минимально нужной, без потери данных."""
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            -- базовая таблица (если вдруг нет)
            CREATE TABLE IF NOT EXISTS users (
                id   BIGSERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL
            );

            -- служебные поля
            ALTER TABLE users ADD COLUMN IF NOT EXISTS created TIMESTAMPTZ DEFAULT now();
            ALTER TABLE users ADD COLUMN IF NOT EXISTS updated TIMESTAMPTZ DEFAULT now();
            ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted BOOLEAN DEFAULT FALSE;

            -- рабочие поля
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password       VARCHAR(255);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash  VARCHAR(255);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email          VARCHAR(255);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS role           VARCHAR(64);

            -- подчищаем NULL-ы
            UPDATE users SET role='viewer'          WHERE role IS NULL;
            UPDATE users SET email='unknown@local'  WHERE email IS NULL;
            UPDATE users SET password=''            WHERE password IS NULL;

            -- если есть password, но нет password_hash — скопируем (без хеширования, по требованиям)
            UPDATE users SET password_hash = password WHERE password_hash IS NULL;

            -- зафиксируем NOT NULL после заполнения
            ALTER TABLE users ALTER COLUMN role          SET NOT NULL;
            ALTER TABLE users ALTER COLUMN email         SET NOT NULL;
            ALTER TABLE users ALTER COLUMN password      SET NOT NULL;
            ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;

            -- индексы (опционально)
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ ensure_users_table: ok")
    except Exception as e:
        print(f"❌ ensure_users_table: {e}")


def ensure_queries_table():
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id       BIGSERIAL PRIMARY KEY,
                user_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name     VARCHAR(255) NOT NULL,
                filter   JSONB NOT NULL DEFAULT '{}'::jsonb,
                created  TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_queries_user_created ON queries (user_id, created DESC);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ ensure_queries_table: ok")
    except Exception as e:
        print(f"❌ ensure_queries_table: {e}")

def ensure_superadmin():
    """Создаёт суперадмина admin/admin/admin@local, если отсутствует."""
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE name=%s", ("admin",))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO users (name, password, password_hash, role, email) VALUES (%s,%s,%s,%s,%s)",
                ("admin", "admin", "admin", "admin", "admin@local")
            )
            conn.commit()
            print("✅ Superadmin 'admin' создан (login=admin, password=admin)")
        else:
            print("ℹ️ Superadmin уже существует")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка ensure_superadmin: {e}")


# ВАЖНО: порядок вызовов
ensure_users_table()
ensure_queries_table()
ensure_superadmin()

@app.post("/register")
def register():
    data = request.json or {}
    name = data.get("name")
    password = data.get("password")
    role = data.get("role", "viewer")
    email = data.get("email", f"{name or 'user'}@local")

    if not name or not password:
        return {"error":"name/password required"}, 400
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users(name,password,password_hash,role,email) VALUES (%s,%s,%s,%s,%s)",
            (name, password, password, role, email)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status":"ok","name":name,"role":role,"email":email}
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/login")
def login():
    data = request.json or {}
    name = data.get("name")
    password = data.get("password")
    if not name or not password:
        return {"error":"name/password required"}, 400
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        # Поддержим обе колонки: legacy password и password_hash (без хеша)
        cur.execute("""
            SELECT id, role, email
            FROM users
            WHERE name=%s AND (password=%s OR password_hash=%s)
            LIMIT 1
        """, (name, password, password))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"error":"bad creds"}, 403
        return {"user_id": row[0], "role": row[1], "email": row[2]}
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/save_query")
def save_query():
    data = request.json or {}
    user_id = data.get("user_id")
    name = data.get("name") or "Запрос"
    filter_ = data.get("filter", {})
    if not user_id:
        return {"error":"user_id required"}, 400
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("INSERT INTO queries(user_id,name,filter) VALUES (%s,%s,%s)",
                    (user_id, name, json.dumps(filter_)))
        conn.commit()
        cur.close()
        conn.close()
        return {"status":"ok"}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/history/<int:user_id>")
def history(user_id: int):
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("SELECT id,name,created,filter FROM queries WHERE user_id=%s ORDER BY created DESC", (user_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"history":[{"id":r[0],"name":r[1],"created":r[2].isoformat(),"filter":r[3]} for r in rows]}
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/admin/create_user")
def admin_create_user():
    """
    Создание пользователя администратором.
    Вход (JSON): { "admin_user_id": 1, "name":"user1", "password":"pass", "role":"viewer", "email":"user1@local" }
    Условия: admin_user_id должен указывать на пользователя с role='admin'
    """
    data = request.json or {}
    admin_user_id = data.get("admin_user_id")
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "viewer").strip()
    email = (data.get("email") or f"{name}@local").strip()

    if not admin_user_id:
        return {"error": "admin_user_id required"}, 400
    if not name or not password:
        return {"error": "name/password required"}, 400
    if role not in ("admin", "uploader", "runner", "viewer", "exporter"):
        # роли на твой вкус; ниже — краткая расшифровка
        return {"error": "invalid role"}, 400

    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()

        # проверка, что инициатор — админ
        cur.execute("SELECT role FROM users WHERE id=%s", (admin_user_id,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return {"error":"admin user not found"}, 404
        if row[0] != "admin":
            cur.close(); conn.close()
            return {"error":"forbidden: admin role required"}, 403

        # создать пользователя (пароль и password_hash одинаковые по требованиям)
        cur.execute("""
            INSERT INTO users(name,password,password_hash,role,email)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING id
        """, (name, password, password, role, email))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close(); conn.close()

        return {"status":"ok","id":new_id,"name":name,"role":role,"email":email}
    except Exception as e:
        return {"error": str(e)}, 500



@app.get("/admin/users")
def admin_list_users():
    admin_user_id = request.args.get("admin_user_id", type=int)
    if not admin_user_id:
        return {"error":"admin_user_id required"}, 400
    try:
        conn = psycopg2.connect(DB_DSN); cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE id=%s", (admin_user_id,))
        row = cur.fetchone()
        if not row or row[0] != "admin":
            cur.close(); conn.close()
            return {"error":"forbidden"}, 403

        cur.execute("""
            SELECT id, name, email, role, created
            FROM users
            WHERE deleted = FALSE
            ORDER BY id
        """)
        users = [{
            "id": r[0],
            "name": r[1],
            "email": r[2],
            "role": r[3],
            "created": r[4].isoformat() if r[4] else None
        } for r in cur.fetchall()]
        cur.close(); conn.close()
        return {"users": users}
    except Exception as e:
        return {"error": str(e)}, 500




@app.get("/healthz")
def healthz():
    return {"status":"ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
