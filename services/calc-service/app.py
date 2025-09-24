from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"*": {"origins": "*"}})

@app.post("/calc")
def calc():
    # вход может содержать photo_id/uuid, но для MVP возвращаем нули
    _ = request.json or {}
    return {"lat": 0.0, "lon": 0.0, "confidence": 0.5}


if __name__ == "__main__":
    # host=0.0.0.0 обязательно, чтобы слушать снаружи контейнера
    app.run(host="0.0.0.0", port=5000, debug=False)