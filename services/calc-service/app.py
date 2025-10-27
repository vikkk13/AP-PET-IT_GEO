import io
import logging
import math
import os
import random
import uuid

import cv2
import numpy as np
import torch
from transformers import OneFormerProcessor, OneFormerForUniversalSegmentation

import requests
from flask import Flask, request, jsonify, send_file
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

class AdvancedUrbanSegmentator:
    def __init__(self, model_name="shi-labs/oneformer_ade20k_swin_tiny", cache_dir=None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        
        local_model_path = self._get_local_model_path()
        
        if local_model_path and os.path.exists(local_model_path):
            self.processor = OneFormerProcessor.from_pretrained(local_model_path)
            self.model = OneFormerForUniversalSegmentation.from_pretrained(local_model_path)
        else:
            self.processor = OneFormerProcessor.from_pretrained(model_name, cache_dir=cache_dir)
            self.model = OneFormerForUniversalSegmentation.from_pretrained(model_name, cache_dir=cache_dir)
            
            if cache_dir and local_model_path:
                self.processor.save_pretrained(local_model_path)
                self.model.save_pretrained(local_model_path)
        
        self.class_names = self.model.config.id2label
        self.building_class_ids = self._find_building_class_ids()
        self.road_class_ids = self._find_road_class_ids()
    
    def _get_local_model_path(self):
        if not self.cache_dir:
            return None
        safe_name = self.model_name.replace("/", "_") if "/" in self.model_name else self.model_name
        return os.path.join(self.cache_dir, safe_name)
    
    def _find_building_class_ids(self):
        building_keywords = ['building', 'house', 'skyscraper', 'edifice', 'tower']
        building_ids = []
        for class_id, class_name in self.class_names.items():
            if any(keyword in class_name.lower() for keyword in building_keywords):
                building_ids.append(class_id)
        return building_ids or [1, 25, 48, 84]
    
    def _find_road_class_ids(self):
        road_keywords = ['road', 'street', 'highway', 'pavement', 'roadway', 'lane']
        road_ids = []
        for class_id, class_name in self.class_names.items():
            if any(keyword in class_name.lower() for keyword in road_keywords):
                road_ids.append(class_id)
        return road_ids or [11, 12, 13]
    
    def semantic_segmentation_detailed(self, image, min_area=500, building_confidence=0.6):
        if isinstance(image, str):
            image = Image.open(image).convert('RGB')
        elif isinstance(image, np.ndarray):
            image = Image.fromarray(image).convert('RGB')
        else:
            image = image.convert('RGB')
        
        inputs = self.processor(images=image, task_inputs=["semantic"], return_tensors="pt")
        
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        semantic_map = self.processor.post_process_semantic_segmentation(
            outputs, target_sizes=[image.size[::-1]]
        )[0]
        
        semantic_map_np = semantic_map.cpu().numpy()
        
        # Создаем маски для разных типов объектов
        building_mask = np.zeros_like(semantic_map_np, dtype=np.uint8)
        road_mask = np.zeros_like(semantic_map_np, dtype=np.uint8)
        other_mask = np.zeros_like(semantic_map_np, dtype=np.uint8)
        
        # Заполняем маску зданий
        for class_id in self.building_class_ids:
            building_mask[semantic_map_np == class_id] = 1
        
        # Заполняем маску дорог
        for class_id in self.road_class_ids:
            road_mask[semantic_map_np == class_id] = 1
        
        # Маска для всех остальных объектов (кроме фона)
        background_class = 0  # обычно 0 - это фон
        for class_id in range(1, len(self.class_names)):  # начинаем с 1, чтобы исключить фон
            if class_id not in self.building_class_ids and class_id not in self.road_class_ids:
                other_mask[semantic_map_np == class_id] = 1
        
        building_mask_refined = self._refine_mask_soft(building_mask)
        road_mask_refined = self._refine_mask_soft(road_mask)
        other_mask_refined = self._refine_mask_soft(other_mask)
        
        buildings_dict = self._extract_components_soft(building_mask_refined, min_area, "building", 
                                                     semantic_map_np, building_confidence)
        
        return {
            "buildings": buildings_dict,
            "road_mask": road_mask_refined,
            "other_mask": other_mask_refined,
            "semantic_map": semantic_map_np
        }
    
    def _refine_mask_soft(self, mask):
        if np.sum(mask) == 0:
            return mask
        
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_CLOSE, kernel)
        
        return cleaned_mask
    
    def _extract_components_soft(self, mask, min_area, object_type, semantic_map, min_confidence=0.3):
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        
        objects_dict = {}
        
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            
            if area >= min_area:
                component_mask = (labels == i).astype(np.uint8)
                
                component_pixels = semantic_map[component_mask > 0]
                if len(component_pixels) > 0:
                    unique_classes, counts = np.unique(component_pixels, return_counts=True)
                    dominant_class = unique_classes[np.argmax(counts)]
                    class_name = self.class_names.get(dominant_class, f"Class {dominant_class}")
                    confidence = counts.max() / len(component_pixels)
                    
                    if confidence >= min_confidence:
                        bbox, area, centroid = self._analyze_mask(component_mask)
                        
                        objects_dict[i] = {
                            "mask": component_mask,
                            "class_id": int(dominant_class),
                            "class_name": class_name,
                            "confidence": float(confidence),
                            "bbox": bbox,
                            "area": area,
                            "centroid": centroid,
                            "object_id": i,
                            "type": object_type,
                            "pixel_count": int(area)
                        }
                else:
                    bbox, area, centroid = self._analyze_mask(component_mask)
                    dominant_class = 1
                    
                    objects_dict[i] = {
                        "mask": component_mask,
                        "class_id": int(dominant_class),
                        "class_name": object_type,
                        "confidence": 1.0,
                        "bbox": bbox,
                        "area": area,
                        "centroid": centroid,
                        "object_id": i,
                        "type": object_type,
                        "pixel_count": int(area)
                    }
        
        return objects_dict
    
    def _analyze_mask(self, mask):
        y_indices, x_indices = np.where(mask > 0)
        if len(y_indices) == 0 or len(x_indices) == 0:
            return [0, 0, 0, 0], 0, [0, 0]
        x_min, x_max = np.min(x_indices), np.max(x_indices)
        y_min, y_max = np.min(y_indices), np.max(y_indices)
        area = len(y_indices)
        centroid = [np.mean(x_indices), np.mean(y_indices)]
        return [x_min, y_min, x_max, y_max], area, centroid

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

def generate_offset_coordinates(lat, lon, offset=50):
    """Генерирует случайные координаты в радиусе от указанной точки"""
    if not lat and not lon: return None, None
    lat, lon = float(lat), float(lon)
    a, d = random.uniform(0, 2 * math.pi), random.uniform(0, offset ** 2) ** 0.5
    return (lat + d * math.cos(a) / 111000, 
            lon + d * math.sin(a) / (111000 * math.cos(math.radians(lat))))
    
def detect_objects(image_url, lat, lon, method, seed):
    """
    Выполняет реальную детекцию зданий используя семантическую сегментацию с разными моделями
    
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
        # Загружаем изображение
        image = download_image(image_url)
        
        # Если method=0 - автоподбор лучшего алгоритма
        if method == 0:
            return _auto_select_best_model(image, lat, lon, seed)
        
        # Определяем модель на основе method
        model_config = _get_model_config(method)
        used_method = model_config["method"]
        model_name = model_config["model_name"]
        
        # Инициализируем сегментатор с выбранной моделью
        cache_dir = "./model_cache"
        os.makedirs(cache_dir, exist_ok=True)
        
        segmentator = AdvancedUrbanSegmentator(
            model_name=model_name,
            cache_dir=cache_dir
        )
        
        # Выполняем реальную семантическую сегментацию
        results = segmentator.semantic_segmentation_detailed(
            image, 
            min_area=500,
            building_confidence=0.6
        )
        
        # Преобразуем результаты в требуемый формат (ТОЛЬКО ЗДАНИЯ)
        detections = _format_detections(results["buildings"], used_method, lat, lon, image.size)
        
        # Сохраняем маски для использования в отрисовке
        results["detections"] = detections
        results["image_size"] = image.size
        
        logger.info(f"Детекция моделью {model_name}: найдено {len(detections)} зданий")
        return results
        
    except Exception as e:
        logger.error(f"Ошибка детекции: {e}")
        return {"buildings": {}, "detections": [], "road_mask": None, "other_mask": None}

def _auto_select_best_model(image, lat, lon, seed):
    """Запускает все модели и выбирает ту, которая нашла больше всего зданий"""
    logger.info("Автоподбор модели: запуск всех моделей...")
    
    cache_dir = "./model_cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    models_to_test = [1, 2, 3, 4, 5]
    best_results = None
    best_model_method = 1
    best_model_name = "shi-labs/oneformer_ade20k_swin_tiny"
    max_buildings = 0
    
    for model_method in models_to_test:
        try:
            model_config = _get_model_config(model_method)
            model_name = model_config["model_name"]
            
            logger.info(f"Тестируем модель {model_method}: {model_name}")
            
            segmentator = AdvancedUrbanSegmentator(
                model_name=model_name,
                cache_dir=cache_dir
            )
            
            results = segmentator.semantic_segmentation_detailed(
                image, 
                min_area=500,
                building_confidence=0.6
            )
            
            buildings_count = len(results["buildings"])
            logger.info(f"  Модель {model_method} нашла {buildings_count} зданий")
            
            if buildings_count > max_buildings:
                max_buildings = buildings_count
                best_model_method = model_method
                best_model_name = model_name
                best_results = results
                best_results["detections"] = _format_detections(
                    results["buildings"], model_method, lat, lon, image.size
                )
                best_results["image_size"] = image.size
                
        except Exception as e:
            logger.error(f"  Ошибка в модели {model_method}: {e}")
            continue
    
    logger.info(f"Выбрана модель {best_model_method} ({best_model_name}): {max_buildings} зданий")
    return best_results if best_results else {"buildings": {}, "detections": [], "road_mask": None, "other_mask": None}

def _format_detections(buildings_dict, method, lat, lon, image_size):
    """Форматирует обнаружения зданий в требуемый формат"""
    detections = []
    
    for obj_id, building in buildings_dict.items():
        bbox_dict = _convert_bbox_format(building["bbox"])
        obj_lat, obj_lon = _calculate_object_coordinates(
            lat, lon, building["centroid"], image_size, building["area"]
        )
        
        detection = [
            f'id{obj_id}',
            method,
            bbox_dict,
            round(building["confidence"], 3),
            obj_lat,
            obj_lon
        ]
        detections.append(detection)
    
    return detections

def _get_model_config(method):
    """Возвращает конфигурацию модели на основе method"""
    models = {
        1: {"method": 1, "model_name": "shi-labs/oneformer_ade20k_swin_tiny", "description": "Tiny модель"},
        2: {"method": 2, "model_name": "shi-labs/oneformer_ade20k_swin_base", "description": "Small модель"},
        3: {"method": 3, "model_name": "shi-labs/oneformer_coco_swin_large", "description": "COCO модель"},
        4: {"method": 4, "model_name": "shi-labs/oneformer_ade20k_swin_large", "description": "ADE20K модель"},
        5: {"method": 5, "model_name": "shi-labs/oneformer_cityscapes_swin_large", "description": "Cityscapes модель"}
    }
    
    return models.get(method, models[1])

def _convert_bbox_format(bbox):
    """Конвертирует bbox из [x_min, y_min, x_max, y_max] в {x, y, w, h}"""
    x_min, y_min, x_max, y_max = bbox
    return {
        'x': int(x_min),
        'y': int(y_min), 
        'w': int(x_max - x_min),
        'h': int(y_max - y_min)
    }

def _calculate_object_coordinates(center_lat, center_lon, centroid, image_size, area):
    """Рассчитывает координаты объекта на основе его положения в изображении"""
    centroid_x, centroid_y = centroid
    img_width, img_height = image_size
    
    if center_lat is None or center_lon is None:
        return None, None
    
    # Нормализуем позицию относительно центра изображения
    norm_x = (centroid_x - img_width/2) / img_width
    norm_y = (centroid_y - img_height/2) / img_height
    
    # Масштабируем смещение в зависимости от площади объекта
    area_factor = min(area / 10000, 1.0)
    
    # Рассчитываем смещение в градусах
    offset_deg = 0.001 * area_factor
    
    obj_lat = float(center_lat) + norm_y * offset_deg
    obj_lon = float(center_lon) + norm_x * offset_deg
    
    return round(obj_lat, 6), round(obj_lon, 6)

def apply_masks(image, road_mask, other_mask):
    """Накладывает маски на изображение"""
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    
    # Создаем изображение для масок
    mask_overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    
    if road_mask is not None and np.sum(road_mask) > 0:
        # Синяя маска для дорог (альфа = 90)
        road_mask_img = Image.fromarray((road_mask * 255).astype(np.uint8), mode='L')
        red_overlay = Image.new('RGBA', image.size, (0, 0, 255, 90))
        mask_overlay = Image.composite(red_overlay, mask_overlay, road_mask_img)
    
    if other_mask is not None and np.sum(other_mask) > 0:
        # Осветляющая маска для остальных объектов (альфа = 250)
        other_mask_img = Image.fromarray((other_mask * 255).astype(np.uint8), mode='L')
        gray_overlay = Image.new('RGBA', image.size, (255, 255, 255, 192))
        mask_overlay = Image.composite(gray_overlay, mask_overlay, other_mask_img)
    
    # Накладываем маски на исходное изображение
    result = Image.alpha_composite(image, mask_overlay)
    return result
    
def draw_detections(image_url, detections, method, seed, single_detection_index=None, road_mask=None, other_mask=None):
    """
    Отрисовывает обнаружения на изображении
    
    Args:
        image_url: URL изображения
        detections: список обнаружений [id, method, bbox, confidence, lat, lon]
        method: метод детекции
        seed: seed
        single_detection_index: индекс одиночного bbox (None - все bbox)
        road_mask: маска дорог
        other_mask: маска других объектов
    
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
        
        # Накладываем маски если они предоставлены
        if road_mask is not None or other_mask is not None:
            image = apply_masks(image, road_mask, other_mask)
        
        # Создаем контекст для рисования
        draw = ImageDraw.Draw(image)
        
        # Шрифт
        font = None
        try:
            font = ImageFont.truetype("arial.ttf", 11)
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
                
                # Рисуем bbox (УВЕЛИЧИЛ толщину рамки с 1 до 3)
                draw.rectangle([x1, y1, x2, y2], 
                             outline=color, width=3)  # Было width=1
                
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
                    coord_text1 = f"{obj_lat:.5f}"
                    coord_text2 = f"{obj_lon:.5f}"
                    
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
                
                # Рисуем bbox (УВЕЛИЧИЛ толщину рамки с 2 до 4)
                draw.rectangle([x1, y1, x2, y2], 
                             outline=pink_color, width=4)  # Было width=2
                
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
                    coord_text1 = f"{obj_lat:.5f}"
                    coord_text2 = f"{obj_lon:.5f}"
                    
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
        results = detect_objects(image_url, lat, lon, int(method), seed)
        detections = results.get("detections", [])
        
        # Отрисовываем изображение со всеми bbox и масками
        img_buffer, _ = draw_detections(
            image_url, 
            detections, 
            method, 
            seed,
            road_mask=results.get("road_mask"),
            other_mask=results.get("other_mask")
        )
        
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
                detection_results = detect_objects(image_url, lat, lon, method, seed)
                detections = detection_results.get("detections", [])
                
                # Отрисовываем основное изображение со всеми bbox и масками
                img_buffer_all, _ = draw_detections(
                    image_url, 
                    detections, 
                    method, 
                    seed,
                    road_mask=detection_results.get("road_mask"),
                    other_mask=detection_results.get("other_mask")
                )
                main_uuid = save_photo(img_buffer_all, image_url, detections)
                
                # Отрисовываем отдельные фото для каждого bbox (без масок)
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