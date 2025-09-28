# GeoLocate (demo, microservices)

Прототип геоплатформы: загрузка фото/координат, поиск по адресу, имитация расчёта «обнаруженных домов», экспорт в XLSX.  
Микросервисная архитектура: `frontend` · `api-gateway` · `auth-service` · `photo-service` · `coords-service` · `calc-service` · `export-service` · `PostgreSQL`.

---

## 0) Требования

- Windows/macOS/Linux с Docker Desktop (WSL2 на Windows)  
- Git  
- Порталы: `8081` (frontend), `8080` (gateway), `5432` (Postgres)

---

## 1) Клонирование

```bash
git clone https://github.com/имя_пользователя/имя_репозитория.git
cd имя_репозитория
