from flask import Flask, request, jsonify, send_file
import logging
import random
import io
import os
import uuid
import requests
from PIL import Image, ImageDraw, ImageFont

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Хранилище для сгенерированных фото
PHOTO_STORAGE = {}
UPLOAD_DIR = "/tmp/calc_service_photos"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Глобальные настройки
BASE_URL = "http://localhost:5004"

def download_image(image_url):
    """Загружает изображение по URL"""
    try:
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        image = Image.open(io.BytesIO(response.content))
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        return image
    except Exception as e:
        logger.error(f"Error downloading image {image_url}: {e}")
        raise

def generate_offset_coordinates(original_lat, original_lon, offset_meters=50):
    """Генерация случайных координат со смещением от оригинальных"""
    offset_deg = offset_meters * 0.000009
    lat_offset = random.uniform(-offset_deg, offset_deg)
    lon_offset = random.uniform(-offset_deg, offset_deg)
    
    obj_lat = float(original_lat) + lat_offset if original_lat else None
    obj_lon = float(original_lon) + lon_offset if original_lon else None
    
    return obj_lat, obj_lon

def detect_objects(image_url, lat, lon, method, seed):
    """
    Имитирует поиск объектов и возвращает список обнаружений
    
    Args:
        image_url: URL изображения
        lat: широта съемки
        lon: долгота съемки  
        method: метод детекции (0 - автоподбор)
        seed: seed для воспроизводимости
    
    Returns:
        list: список обнаружений [id, method, bbox, confidence, lat, lon]
    """
    try:
        # Загружаем изображение для получения размеров
        image = download_image(image_url)
        width, height = image.size
        
        # Устанавливаем seed
        if seed:
            random.seed(int(seed))
        
        # Если method=0 - автоподбор лучшего алгоритма
        if method == 0:
            used_method = random.randint(1, 6)
        else:
            used_method = method
        
        # Генерируем случайные bbox в формате x,y,w,h
        num_detections = random.randint(1, 5)
        detections = []
        
        for i in range(num_detections):
            w = random.randint(int(width * 0.1), int(width * 0.4))  # ширина
            h = random.randint(int(height * 0.1), int(height * 0.3))  # высота
            x = random.randint(10, width - w - 10)  # левый верхний угол x
            y = random.randint(10, height - h - 10)  # левый верхний угол y
            
            # Генерируем координаты объекта
            obj_lat, obj_lon = generate_offset_coordinates(lat, lon, random.randint(50, 100))
            
            # Генерируем confidence
            confidence = round(random.uniform(0.5, 0.999), 3)
            
            detection = [
                f'id{i+1}',           # id
                used_method,           # method
                {'x': x, 'y': y, 'w': w, 'h': h},  # bbox в формате x,y,w,h
                confidence,            # confidence
                obj_lat,               # lat объекта
                obj_lon                # lon объекта
            ]
            detections.append(detection)
        
        return detections
        
    except Exception as e:
        logger.error(f"Error in detect_objects: {e}")
        return []
    
def draw_detections(image_url, detections, method, seed, single_detection_index=None):
    """
    Отрисовывает обнаружения на изображении
    
    Args:
        image_url: URL изображения
        detections: список обнаружений [id, method, bbox, confidence, lat, lon]
        method: метод детекции
        seed: seed
        single_detection_index: индекс одиночного bbox (None - все bbox)
    
    Returns:
        tuple: (img_buffer, photo_urls)
    """
    try:
        # Палитра цветов для bbox (циклическое использование)
        COLOR_PALETTE = [
            (255, 105, 180),  # розовый
            (119, 11, 32),    # бордовый
            (0, 0, 142),      # темно-синий
            (0, 0, 230),      # синий
            (106, 0, 228),    # фиолетовый
            (0, 60, 100),     # темно-бирюзовый
            (0, 80, 100),     # бирюзовый
            (0, 0, 70),       # очень темно-синий
            (0, 0, 192),      # ярко-синий
            (250, 170, 30)    # оранжевый
        ]
        
        # Загружаем изображение
        image = download_image(image_url)
        width, height = image.size
        
        # Создаем контекст для рисования
        draw = ImageDraw.Draw(image)
        
        # Шрифт
        font = None
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            try:
                font = ImageFont.load_default()
            except:
                pass
        
        photo_urls = []
        
        # Определяем режим отрисовки
        draw_single = single_detection_index is not None
        
        if not draw_single:
            # Режим "все bbox"
            for i, detection in enumerate(detections):
                id_val, method_val, bbox, confidence, obj_lat, obj_lon = detection
                
                # Получаем цвет по id (циклически из палитры)
                color = COLOR_PALETTE[i % len(COLOR_PALETTE)]
                
                # Конвертируем x,y,w,h в x1,y1,x2,y2 для отрисовки
                x1 = bbox['x']
                y1 = bbox['y']
                x2 = bbox['x'] + bbox['w']
                y2 = bbox['y'] + bbox['h']
                
                # Рисуем bbox (тоньше - width=1)
                draw.rectangle([x1, y1, x2, y2], 
                             outline=color, width=1)
                
                # Подписываем bbox с confidence (формат: "id1 .87")
                label = f"{id_val} .{int(confidence * 100):02d}"
                label_bg_width = 45
                label_bg_height = 14
                
                # Фон для подписи (полупрозрачный)
                label_bg = Image.new('RGBA', (label_bg_width, label_bg_height), color + (180,))
                image.paste(label_bg, (x1 + 1, y1 + 1), label_bg)
                
                # Текст подписи
                draw.text((x1 + 3, y1 + 1), 
                         label, fill=(255, 255, 255), font=font)
                
                # Координаты объекта
                if obj_lat and obj_lon:
                    coord_text1 = f"{obj_lat:.6f}"
                    coord_text2 = f"{obj_lon:.6f}"
                    
                    coord_bg_x = x1 + 1
                    coord_bg_y = y1 + label_bg_height + 1
                    # ШИРЕ фон для координат - учитываем полную длину чисел
                    coord_bg_width = max(len(coord_text1), len(coord_text2)) * 6 + 8
                    coord_bg_height = 24
                    
                    if (coord_bg_y + coord_bg_height < y2 and 
                        coord_bg_x + coord_bg_width < x2):
                        # Полупрозрачный белый фон для координат
                        coord_bg = Image.new('RGBA', (coord_bg_width, coord_bg_height), (255, 255, 255, 180))
                        image.paste(coord_bg, (coord_bg_x, coord_bg_y), coord_bg)
                        
                        # Текст координат
                        draw.text((coord_bg_x + 4, coord_bg_y + 2), coord_text1, 
                                 fill=(0, 0, 0), font=font)
                        draw.text((coord_bg_x + 4, coord_bg_y + 12), coord_text2, 
                                 fill=(0, 0, 0), font=font)
            
            # Информационная строка с seed (полупрозрачный фон) - ТОЛЬКО ДЛЯ РЕЖИМА ВСЕХ BBOX
            info_bg_height = 20
            info_bg = Image.new('RGBA', (width, info_bg_height), (0, 0, 0, 180))
            image.paste(info_bg, (0, height - info_bg_height), info_bg)
            
            info_text = f"Detections: {len(detections)} | Method: {method} | Seed: {seed}"
            draw.text((10, height - info_bg_height + 3), info_text, fill=(255, 255, 255), font=font)
            
        else:
            # Режим "один bbox" - БЕЗ СТАТУСНОЙ СТРОКИ
            if single_detection_index < len(detections):
                detection = detections[single_detection_index]
                id_val, method_val, bbox, confidence, obj_lat, obj_lon = detection
                
                # Для одиночного bbox всегда используем розовый цвет
                pink_color = (255, 105, 180)
                
                # Конвертируем x,y,w,h в x1,y1,x2,y2 для отрисовки
                x1 = bbox['x']
                y1 = bbox['y']
                x2 = bbox['x'] + bbox['w']
                y2 = bbox['y'] + bbox['h']
                
                # Рисуем bbox (тоньше - width=2)
                draw.rectangle([x1, y1, x2, y2], 
                             outline=pink_color, width=2)
                
                # Подписываем bbox с confidence (формат: "id1 .87")
                label = f"{id_val} .{int(confidence * 100):02d}"
                label_bg_width = 45
                label_bg_height = 14
                
                # Полупрозрачный розовый фон для подписи
                label_bg = Image.new('RGBA', (label_bg_width, label_bg_height), pink_color + (180,))
                image.paste(label_bg, (x1 + 1, y1 + 1), label_bg)
                
                draw.text((x1 + 3, y1 + 1), 
                         label, fill=(255, 255, 255), font=font)
                
                # Координаты объекта
                if obj_lat and obj_lon:
                    coord_text1 = f"{obj_lat:.6f}"
                    coord_text2 = f"{obj_lon:.6f}"
                    
                    coord_bg_x = x1 + 1
                    coord_bg_y = y1 + label_bg_height + 1
                    # ШИРЕ фон для координат - учитываем полную длину чисел
                    coord_bg_width = max(len(coord_text1), len(coord_text2)) * 7 + 10  # Было *5+6
                    coord_bg_height = 22
                    
                    if (coord_bg_y + coord_bg_height < y2 and 
                        coord_bg_x + coord_bg_width < x2):
                        # Полупрозрачный белый фон для координат
                        coord_bg = Image.new('RGBA', (coord_bg_width, coord_bg_height), (255, 255, 255, 180))
                        image.paste(coord_bg, (coord_bg_x, coord_bg_y), coord_bg)
                        
                        # Текст координат
                        draw.text((coord_bg_x + 4, coord_bg_y + 2), coord_text1, 
                                 fill=(0, 0, 0), font=font)
                        draw.text((coord_bg_x + 4, coord_bg_y + 12), coord_text2, 
                                 fill=(0, 0, 0), font=font)
        
        # Конвертируем обратно в RGB для сохранения как JPEG
        if image.mode == 'RGBA':
            image = image.convert('RGB')
            
        img_buffer = io.BytesIO()
        image.save(img_buffer, 'JPEG', quality=90)
        img_buffer.seek(0)
        
        return img_buffer, photo_urls
        
    except Exception as e:
        logger.error(f"Error in draw_detections: {e}")
        width, height = 800, 600
        image = Image.new('RGB', (width, height), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        draw.text((50, 50), f"Error: {str(e)}", fill=(255, 0, 0))
        
        img_buffer = io.BytesIO()
        image.save(img_buffer, 'JPEG', quality=85)
        img_buffer.seek(0)
        
        return img_buffer, []
        
def save_photo(img_buffer, image_url, detections=None, detection_index=None):
    """Сохраняет фото в хранилище и возвращает UUID"""
    photo_uuid = str(uuid.uuid4())
    filename = f"{photo_uuid}.jpg"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, 'wb') as f:
        f.write(img_buffer.getvalue())
    
    PHOTO_STORAGE[photo_uuid] = {
        'filepath': filepath,
        'image_url': image_url,
        'detections': detections,
        'detection_index': detection_index
    }
    
    return photo_uuid

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "calc-service"})

@app.route('/detect', methods=['GET'])
def detect_objects_endpoint():
    try:
        image_url = request.args.get('image_url')
        lat = request.args.get('lat')
        lon = request.args.get('lon')
        method = request.args.get('method', '1')
        seed = request.args.get('seed')
        
        if not image_url:
            return jsonify({"success": False, "error": "image_url is required"}), 400
        
        # Детектируем объекты
        detections = detect_objects(image_url, lat, lon, int(method), seed)
        
        # Отрисовываем изображение со всеми bbox
        img_buffer, _ = draw_detections(image_url, detections, method, seed)
        
        # Возвращаем ТОЛЬКО изображение
        return send_file(
            img_buffer,
            mimetype='image/jpeg',
            as_attachment=False,
            download_name='detection_result.jpg'
        )
        
    except Exception as e:
        logger.error(f"Error in detect_objects: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/detect_batch', methods=['POST'])
def detect_batch():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        method = data.get('method', 1)
        seed = data.get('seed')
        images = data.get('images', [])
        
        if not images:
            return jsonify({"success": False, "error": "No images provided"}), 400
        
        results = []
        
        for img_data in images:
            image_url = img_data.get('image_url')
            lat = img_data.get('lat')
            lon = img_data.get('lon')
            
            if not image_url:
                continue
            
            try:
                # Детектируем объекты
                detections = detect_objects(image_url, lat, lon, method, seed)
                
                # Отрисовываем основное изображение со всеми bbox
                img_buffer_all, _ = draw_detections(image_url, detections, method, seed)
                main_uuid = save_photo(img_buffer_all, image_url, detections)
                
                # Отрисовываем отдельные фото для каждого bbox
                single_photos = []
                for j, detection in enumerate(detections):
                    single_buffer, _ = draw_detections(image_url, [detection], method, seed, single_detection_index=0)
                    single_uuid = save_photo(single_buffer, image_url, [detection], j)
                    
                    id_val, method_val, bbox, confidence, obj_lat, obj_lon = detection
                    single_photos.append({
                        'photo_url': f"{BASE_URL}/photo?uuid={single_uuid}",
                        'bbox': bbox,
                        'lat': obj_lat,        # Плоская структура
                        'lon': obj_lon,        # Плоская структура
                        'confidence': confidence
                    })
                
                # Формируем результат (плоская структура)
                result_detections = []
                for j, detection in enumerate(detections):
                    id_val, method_val, bbox, confidence, obj_lat, obj_lon = detection
                    result_detections.append({
                        'id': id_val,
                        'method': method_val,
                        'bbox': bbox,
                        'confidence': confidence,
                        'lat': obj_lat,        # Прямо здесь
                        'lon': obj_lon,        # Прямо здесь
                        'single_photo_url': single_photos[j]['photo_url']
                    })
                
                result = {
                    'original_image_url': image_url,
                    'processed_image_url': f"{BASE_URL}/photo?uuid={main_uuid}",
                    'detection_count': len(detections),
                    'method': method,
                    'detections': result_detections
                }
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error processing image {image_url}: {e}")
                results.append({
                    'original_image_url': image_url,
                    'error': str(e),
                    'detection_count': 0,
                    'detections': []
                })
        
        return jsonify({
            'success': True,
            'total_processed': len(results),
            'method': method,
            'seed': seed,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error in detect_batch: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/show', methods=['GET'])
def show_detection():
    """Отрисовывает изображение с заданными параметрами без расчета"""
    try:
        image_url = request.args.get('image_url')
        id_val = request.args.get('id')
        method = request.args.get('method')
        bbox_str = request.args.get('bbox')
        confidence = request.args.get('confidence')
        lat = request.args.get('lat')
        lon = request.args.get('lon')
        
        if not all([image_url, id_val, method, bbox_str, confidence, lat, lon]):
            return jsonify({"success": False, "error": "All parameters are required"}), 400
        
        # Парсим bbox в формате "x,y,w,h"
        try:
            bbox_parts = bbox_str.split(',')
            if len(bbox_parts) != 4:
                raise ValueError("Bbox must have 4 values: x,y,w,h")
            
            x, y, w, h = map(int, bbox_parts)
            bbox = {
                'x': x,
                'y': y, 
                'w': w,
                'h': h
            }
        except Exception as e:
            return jsonify({
                "success": False, 
                "error": f"Invalid bbox format: {str(e)}. Use: x,y,w,h"
            }), 400
        
        # Создаем обнаружение
        detection = [
            id_val,                    # id
            int(method),               # method
            bbox,                      # bbox в формате x,y,w,h
            float(confidence),         # confidence
            float(lat),                # lat объекта
            float(lon)                 # lon объекта
        ]
        
        # Отрисовываем изображение без статусной строки
        img_buffer, _ = draw_detections(
            image_url, [detection], method, None, single_detection_index=0
        )        
        
        # Сохраняем фото
        photo_uuid = save_photo(img_buffer, image_url, [detection])
        
        # Возвращаем изображение
        return send_file(
            os.path.join(UPLOAD_DIR, f"{photo_uuid}.jpg"),
            mimetype='image/jpeg',
            as_attachment=False,
            download_name=f'show_{id_val}.jpg'
        )
        
    except Exception as e:
        logger.error(f"Error in show_detection: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/photo', methods=['GET'])
def get_photo():
    try:
        photo_uuid = request.args.get('uuid')
        
        if not photo_uuid:
            return jsonify({"success": False, "error": "uuid parameter is required"}), 400
        
        if photo_uuid not in PHOTO_STORAGE:
            return jsonify({"success": False, "error": "Photo not found"}), 404
        
        photo_info = PHOTO_STORAGE[photo_uuid]
        filepath = photo_info['filepath']
        
        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Photo file not found"}), 404
        
        return send_file(
            filepath,
            mimetype='image/jpeg',
            as_attachment=False,
            download_name=f'photo_{photo_uuid}.jpg'
        )
        
    except Exception as e:
        logger.error(f"Error in get_photo: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/clear', methods=['GET'])
def clear_storage():
    try:
        deleted_count = 0
        
        for photo_uuid, photo_info in list(PHOTO_STORAGE.items()):
            filepath = photo_info['filepath']
            if os.path.exists(filepath):
                os.remove(filepath)
                deleted_count += 1
        
        PHOTO_STORAGE.clear()
        
        return jsonify({
            'success': True,
            'message': f'Storage cleared. Deleted {deleted_count} files.',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        logger.error(f"Error in clear_storage: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)