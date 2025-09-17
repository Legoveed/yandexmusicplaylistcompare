from flask import Flask, render_template, request, jsonify
import logging
import re
from yandex_service import YandexMusicService
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from functools import lru_cache
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=8)

# Кэш для результатов запросов
@lru_cache(maxsize=100)
def parse_playlist_url_cached(url):
    """Парсит URL плейлиста и возвращает тип плейлиста и его параметры (с кэшированием)"""
    # Проверяем формат с UUID
    uuid_match = re.search(r'music\.yandex\.ru/playlists/([^/?]+)', url)
    if uuid_match:
        return {'type': 'uuid', 'uuid': uuid_match.group(1)}
    
    # Проверяем формат с пользователем и ID плейлиста
    user_match = re.search(r'music\.yandex\.ru/users/([^/]+)/playlists/(\d+)', url)
    if user_match:
        return {'type': 'user_kind', 'user': user_match.group(1), 'kind': user_match.group(2)}
    
    raise ValueError("Неверный формат ссылки на плейлист")

def process_playlist(service, playlist_info):
    """Обрабатывает один плейлист и возвращает словарь с треками и их ID"""
    try:
        if playlist_info['type'] == 'uuid':
            tracks = service.get_tracks_by_uuid(playlist_info['uuid'])
        else:
            tracks = service.get_tracks(playlist_info['user'], playlist_info['kind'])
        
        # Создаем словарь с треками и их ID для быстрого поиска
        tracks_dict = {}
        for track in tracks:
            track_id = service.get_track_id(track)
            if track_id:
                tracks_dict[track_id] = track
        
        return tracks_dict
    except Exception as e:
        logger.error(f"Ошибка обработки плейлиста: {e}")
        raise

def process_playlists_async(url1, url2):
    """Асинхронная обработка плейлистов"""
    try:
        service = YandexMusicService()
        
        # Парсим URLs
        playlist1_info = parse_playlist_url_cached(url1)
        playlist2_info = parse_playlist_url_cached(url2)
        
        # Параллельная обработка плейлистов
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(process_playlist, service, playlist1_info),
                executor.submit(process_playlist, service, playlist2_info)
            ]
            
            results = []
            for future in as_completed(futures):
                results.append(future.result())
        
        tracks1_dict, tracks2_dict = results
        
        # Находим общие треки
        common_ids = set(tracks1_dict.keys()) & set(tracks2_dict.keys())
        
        # Получаем информацию об общих треках
        common_tracks = []
        for track_id in common_ids:
            track = tracks1_dict[track_id]
            info = service.get_track_info(track)
            if info:
                common_tracks.append(info)
        
        common_tracks.sort(key=lambda x: x['title'].lower())
        
        return {'common_tracks': common_tracks, 'error': None}
        
    except Exception as e:
        error_msg = f"{e}"
        logger.error(f"Произошла ошибка при обработке: {error_msg}")
        return {'common_tracks': [], 'error': error_msg}

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # AJAX запрос
        url1 = request.json.get('playlist1', '').strip()
        url2 = request.json.get('playlist2', '').strip()
        
        if not url1 or not url2:
            return jsonify({'error': 'Введите обе ссылки на плейлисты'})
        
        try:
            # Парсим URLs для валидации
            parse_playlist_url_cached(url1)
            parse_playlist_url_cached(url2)
        except ValueError as e:
            return jsonify({'error': str(e)})
        
        result = process_playlists_async(url1, url2)
        return jsonify(result)
    
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))