FROM pytorch/pytorch:2.8.0-cuda12.9-cudnn9-devel

# Устанавливаем системные зависимости
RUN echo 'tzdata tzdata/zone Europe/Moscow' | debconf-set-selections && \
    echo 'tzdata tzdata/Areas Europe' | debconf-set-selections && \
    apt-get update -y -q && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tzdata \
        gdal-bin \
        libgdal-dev \
        python3-opencv \
        git && \
    rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app
COPY requirements.txt .

# Устанавливаем Python-пакеты
RUN pip install --no-cache-dir --root-user-action=ignore --upgrade  pip && \
    pip install --no-cache-dir --root-user-action=ignore -r requirements.txt
ENV PYTHONUNBUFFERED=1
COPY app.py .

# Создаем директорию для кэша моделей
RUN mkdir -p /app/model_cache

CMD ["python", "app.py"]
