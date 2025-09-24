import os, io
from flask import Flask, request, send_file
from flask_cors import CORS
import psycopg2, openpyxl

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

PUBLIC_UPLOAD_BASE = os.getenv("PUBLIC_UPLOAD_BASE", "http://localhost:5001/uploads")

@app.post("/export")
def export():
    payload = request.json or {}
    ids = payload.get("ids")  # список id (опционально)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Photos"
    ws.append(["Фотография","Здание","Адрес","Координаты"])

    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        if ids:
            cur.execute("""
                SELECT stored_name, building, address, latitude, longitude
                FROM photos
                WHERE id = ANY(%s) AND deleted = FALSE
            """, (ids,))
        else:
            cur.execute("""
                SELECT stored_name, building, address, latitude, longitude
                FROM photos
                WHERE deleted = FALSE
                ORDER BY created DESC
            """)
        for stored_name, building, address, lat, lon in cur.fetchall():
            link = "-" if stored_name == "-" else f"{PUBLIC_UPLOAD_BASE}/{stored_name}"
            coords = "" if (lat is None or lon is None) else f"{lat}, {lon}"
            ws.append([link, building or "-", address or "-", coords])
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}, 500

    buff = io.BytesIO()
    wb.save(buff)
    buff.seek(0)
    return send_file(buff, as_attachment=True,
                     download_name="export.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/healthz")
def healthz():
    return {"status":"ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
