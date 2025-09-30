import os
import io
from typing import List, Tuple

from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import openpyxl

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

# ------------------ DB & URLs ------------------
DB_DSN = (
    f"dbname={os.getenv('POSTGRES_DB', 'geolocate_db')} "
    f"user={os.getenv('POSTGRES_USER', 'geolocate_user')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'StrongPass123!')} "
    f"host={os.getenv('POSTGRES_HOST', 'db')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')}"
)

# База для линков на файл (через API-gateway)
# конечный URL получится: {PUBLIC_PHOTO_URL_BASE}/{uuid}
PUBLIC_PHOTO_URL_BASE = os.getenv("PUBLIC_PHOTO_URL_BASE", "http://localhost:5000/api/photos")

# ------------------ Поля экспорта ------------------
# key -> (SQL expression, column header)
FIELD_MAP = {
    # фото
    "photo_id":      ("p.id",               "photo_id"),
    "photo_name":    ("p.name",             "photo_name"),
    "uuid":          ("p.uuid::text",       "uuid"),
    "created":       ("p.created",          "photo_created"),
    "width":         ("p.width",            "width"),
    "height":        ("p.height",           "height"),
    "type":          ("p.type",             "type"),
    "subtype":       ("p.subtype",          "subtype"),
    "shot_lat":      ("p.shot_lat",         "shot_lat"),
    "shot_lon":      ("p.shot_lon",         "shot_lon"),

    # объект (детекция)
    "object_id":     ("o.id",               "object_id"),
    "label":         ("o.label",            "label"),
    "confidence":    ("o.confidence",       "confidence"),
    "x1":            ("o.x1",               "x1"),
    "y1":            ("o.y1",               "y1"),
    "x2":            ("o.x2",               "x2"),
    "y2":            ("o.y2",               "y2"),
    "latitude":      ("o.latitude",         "latitude"),
    "longitude":     ("o.longitude",        "longitude"),
    "object_created":("o.created",          "object_created"),

    # виртуальное поле — линк на файл (из uuid строим URL)
    # в SQL выберем uuid как photo_url, а потом подменим значениями с базой URL
    "photo_url":     ("p.uuid::text",       "photo_url"),
}

DEFAULT_FIELDS = ["photo_name", "photo_url", "label", "confidence", "x1","y1","x2","y2", "latitude","longitude"]

# ------------------ Утилиты ------------------
def _ensure_fields(requested: List[str]) -> List[str]:
    if not requested:
        return DEFAULT_FIELDS[:]
    valid = [f for f in requested if f in FIELD_MAP]
    return valid or DEFAULT_FIELDS[:]

def _coerce_ids(ids_raw) -> List[int]:
    if ids_raw is None:
        return []
    if isinstance(ids_raw, (list, tuple)):
        out = []
        for v in ids_raw:
            try:
                out.append(int(v))
            except Exception:
                pass
        return out
    # строка с запятыми
    if isinstance(ids_raw, str):
        out = []
        for part in ids_raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(int(part))
            except Exception:
                pass
        return out
    return []

def _build_sql(fields: List[str], ids: List[int], label: str | None) -> Tuple[str, list]:
    """
    Возвращает (sql, params) для выборки.
    INNER JOIN по детекциям (только фото, у которых есть объекты).
    """
    select_cols = []
    for f in fields:
        expr, _hdr = FIELD_MAP[f]
        alias = f  # имена колонок в итоговом наборе соответствуют ключам
        select_cols.append(f"{expr} AS {alias}")

    sql = f"""
        SELECT {", ".join(select_cols)}
        FROM detected_objects o
        JOIN photos p ON p.id = o.photo_id
    """

    where = []
    params: list = []

    if ids:
        where.append("o.photo_id = ANY(%s)")
        params.append(ids)

    if label:
        where.append("o.label = %s")
        params.append(label)

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += " ORDER BY o.id DESC"

    return sql, params

def _postprocess_row(row: dict, fields: List[str]) -> dict:
    """
    Подменяем виртуальные поля.
    Сейчас — только photo_url из uuid.
    """
    if "photo_url" in fields:
        # row["photo_url"] содержит uuid::text из SQL
        uuid_val = row.get("photo_url")
        if uuid_val:
            row["photo_url"] = f"{PUBLIC_PHOTO_URL_BASE}/{uuid_val}"
        else:
            row["photo_url"] = ""
    return row

# ------------------ Экспорт ------------------
def _export_impl(payload: dict):
    """
    Обработка запроса экспорта: принимает JSON:
    {
      "fields": ["photo_name","photo_url","label", ...],  // необяз., по умолчанию DEFAULT_FIELDS
      "filter": { "label": "house" },                     // необяз.
      "ids": [1,2,3]                                      // необяз., ограничить выборку фото
    }
    Возвращает готовый XLSX бинарно через send_file.
    """
    fields = _ensure_fields(payload.get("fields") or [])
    label = None
    if isinstance(payload.get("filter"), dict):
        label = payload["filter"].get("label") or None

    ids = _coerce_ids(payload.get("ids"))

    sql, params = _build_sql(fields, ids, label)

    # запрашиваем
    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()  # list[dict]

    # пост-обработка виртуальных полей
    out_rows = [_postprocess_row(dict(r), fields) for r in rows]

    # формируем книгу
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "export"

    # заголовки — читаемые подписи
    headers = [FIELD_MAP[f][1] for f in fields]
    ws.append(headers)

    for r in out_rows:
        ws.append([r.get(f, "") for f in fields])

    buff = io.BytesIO()
    wb.save(buff)
    buff.seek(0)

    return send_file(
        buff,
        as_attachment=True,
        download_name="export.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# Оба роута ведут на один и тот же обработчик — для совместимости
@app.post("/export")
def export_xlsx_legacy():
    try:
        payload = request.get_json(silent=True) or {}
        return _export_impl(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/export_xlsx")
def export_xlsx():
    try:
        payload = request.get_json(silent=True) or {}
        return _export_impl(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "export"}, 200

if __name__ == "__main__":
    # Не включаем debug в проде
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
