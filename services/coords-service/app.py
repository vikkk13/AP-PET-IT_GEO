import os, uuid as _uuid
from datetime import datetime, timedelta
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

@app.get("/healthz")
def healthz():
    return {"status":"ok","ts":datetime.utcnow().isoformat()}

@app.post("/upload_coords")
def upload_coords():
    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")
    type1 = data.get("type1")
    type2 = data.get("type2")
    building = data.get("building") or None
    address = data.get("address") or None
    source = data.get("source") or "manual"

    if lat is None or lon is None:
        return {"error":"lat/lon required"}, 400
    if type1 not in ("мусор", "стройка"):
        return {"error":"type1 must be 'мусор' or 'стройка'"}, 400
    if type2 not in ("ИНС","КИНС","Другое"):
        return {"error":"type2 must be 'ИНС'|'КИНС'|'Другое'"}, 400

    uid = _uuid.uuid4()
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO photos (uuid, orig_name, stored_name, mime_type, size_bytes,
                                type1, type2, building, address, latitude, longitude, source)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, created
        """, (uid, "coords.json", "-", "application/json", 0,
              type1, type2, building, address, float(lat), float(lon), source))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    return {"status":"ok","id":row[0],"uuid":str(uid),"created":row[1].isoformat(),
            "type1":type1,"type2":type2,"lat":lat,"lon":lon}

@app.get("/search_by_addr")
def search_by_addr():
    q = request.args.get("q","").strip()
    years = int(request.args.get("years", "3"))
    since = datetime.utcnow() - timedelta(days=365*years)
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute("""
            SELECT id,stored_name,address,latitude,longitude,created
            FROM photos
            WHERE deleted=FALSE
              AND (address ILIKE %s)
              AND created >= %s
            ORDER BY created DESC
            LIMIT 200
        """, (f"%{q}%", since))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    photo_port = os.getenv('PHOTO_PORT', '5001')
    return {"items":[{
        "id":r[0],
        "url": (None if r[1]=="-" else f"http://localhost:{photo_port}/uploads/{r[1]}"),
        "address": r[2],
        "lat": r[3],
        "lon": r[4],
        "created": r[5].isoformat()
    } for r in rows]}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
