# GeoLocate MVP — Геоплатформа для поиска координат зданий по фотографиям

> **MVP (Minimum Viable Product)** геоаналитической платформы с микросервисной архитектурой: загрузка фото с координатами, обнаружение объектов (домов), экспорт результатов в XLSX.

---

## Быстрый старт

### Требования
- **ОС**: Windows (с WSL2), macOS или Linux  
- **Docker** (включая Docker Compose)  
- **Git**

### Установка и запуск
```bash
git clone https://github.com/vikkk13/AP-PET-IT_GEO.git
cd AP-PET-IT_GEO

docker-compose up --build
```

### Порты по умолчанию
| Сервис           | Порт (локальный) |
|------------------|------------------|
| Frontend         | `8081`           |
| API Gateway      | `8080` → `5000`  |
| PostgreSQL       | `5432`           |

> После запуска откройте [http://localhost:8081](http://localhost:8081)

---

## Что делает платформа?

1. **Загрузка фото** с геокоординатами (через `photo-service`)
2. **Поиск по адресу** → получение координат (`coords-service`)
3. **Обнаружение объектов** (домов, зданий) на фото с привязкой к координатам (`calc-service`)
4. **Экспорт результатов** в XLSX (`export-service`)
5. **Аутентификация** (`auth-service`)
6. Единая точка входа через **API Gateway**

---

## Как отдельно запустить `calc-service`

Сервис `calc-service` — **ядро анализа** - компонент, отвечающий за:
- Детекцию объектов на изображениях
- Генерацию координат объектов на основе исходных координат съёмки
- Отрисовку bounding boxes (bbox) на фото
- Поддержку batch-обработки множества изображений

### Запуск в Docker (из корня проекта)

```bash
# Сборка и запуск только calc-service
docker-compose up --build calc-service
```

### Примеры запросов к `calc-service`

#### 1. Детекция на одном изображении
```bash
curl "http://localhost:5004/detect?image_url=https://cdn.novostroy.su/regions/u/b/g/box_orig/wm_631fa6855a193.jpg&lat=55.805&lon=37.750&method=3"
# Возвращает JPEG с нарисованными bboxes
```

#### 2. Batch-обработка (POST)
```bash
curl -X POST http://localhost:5004/detect_batch \
  -H "Content-Type: application/json" \
  -d '{
    "method": 3,
    "seed": 42,
    "images": [
      {
        "image_url": "https://cdn.novostroy.su/regions/u/b/g/box_orig/wm_631fa6855a193.jpg",
        "lat": 55.805,
        "lon": 37.750
      },
      {
        "image_url": "https://avatars.mds.yandex.net/get-altay/12820607/2a0000019326b58ed2f3451fb75a6fed34f1/XXXL",
        "lat": 55.805,
        "lon": 37.751
      }
    ]
  }'
```

#### 3. Получить сохранённое фото по UUID
```bash
curl "http://localhost:5004/photo?uuid=ваш-uuid-здесь"
```

#### 4. Очистить временное хранилище
```bash
curl http://localhost:5004/clear
```

> **Важно**: `calc-service` **не зависит от БД** — работает полностью stateless (кроме временного хранения изображений в `/tmp`).

---

## Архитектура

```
┌─────────────┐     ┌────────────────┐
│  Frontend   │────▶│  API Gateway   │
└─────────────┘     └────────────────┘
                           │
       ┌───────────────────┼────────────────────┐
       ▼                   ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌────────────────┐
│ auth-service  │  │ photo-service   │  │ coords-service │
└───────────────┘  └─────────────────┘  └────────────────┘
                           │
                           ▼
                   ┌─────────────────┐
                   │  calc-service   │ ←─ Ядро анализа
                   └─────────────────┘
                           │
                           ▼
                   ┌─────────────────┐
                   │ export-service  │
                   └─────────────────┘
                           │
                           ▼
                   ┌─────────────────┐
                   │   PostgreSQL    │
                   └─────────────────┘
```

---

## Стек технологий

- **Язык**: Python
- **Фреймворк**: Flask
- **Контейнеризация**: Docker + Docker Compose
- **База данных**: PostgreSQL 15
- **Frontend**: Статический HTML/JS (раздаётся через Nginx)

---

## Особенности MVP

- **MVP готов к демо**: полный цикл от загрузки фото до экспорта
- **Микросервисная архитектура** — легко масштабировать и заменять компоненты
- **RESTful API** — документирован через Postman или Swagger (можно добавить)
- **Готов к деплою** в облако (Kubernetes, AWS ECS и т.д.)

---

## Контакты

https://github.com/vikkk13

