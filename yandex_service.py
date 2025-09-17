# yandex_service.py
from typing import List, Dict, Any, Optional
from yandex_music import Client
import logging
import time
from functools import wraps, lru_cache
import requests
import json
import os
from dotenv import load_dotenv
load_dotenv()  # Загружает переменные из .env файла

def retry_on_error(max_retries=3, delay=2):
    """Декоратор для повторных попыток при ошибках API"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logging.warning(f"Попытка {attempt + 1} не удалась: {e}")
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

logger = logging.getLogger(__name__)

class YandexMusicService:
    def __init__(self, token: Optional[str] = None):
        try:
            # Инициализация клиента
            self.client = Client(token).init() if token else Client().init()
            logger.info("Yandex Music client успешно инициализирован")
        except Exception as e:
            logger.error(f"Ошибка инициализации Yandex Music client: {e}")
            raise

    @retry_on_error(max_retries=3, delay=1)
    def get_tracks(self, user: str, playlist_id: str) -> List[Any]:
        """Получение треков плейлиста по нику пользователя и идентификатору плейлиста"""
        try:
            # Получаем плейлист
            playlist = self.client.users_playlists(playlist_id, user)
            if isinstance(playlist, list):
                playlist = playlist[0]
            if not playlist or not hasattr(playlist, 'tracks'):
                raise ValueError("Плейлист не найден или не содержит треков")
            
            # Загружаем треки
            if hasattr(playlist, 'fetch_tracks'):
                playlist.fetch_tracks()
            
            return playlist.tracks
        except Exception as e:
            logger.error(f"Ошибка получения треков: {e}")
            raise ValueError(f"Не удалось получить треки: {str(e)}")

    @lru_cache(maxsize=50)
    def get_tracks_by_uuid(self, playlist_uuid: str) -> List[Any]:
        """Получение треков плейлиста по UUID (с кэшированием)"""
        try:
            oauth_token = ""
            oauth_token = os.environ.get('YANDEX_OAUTH_TOKEN')
            if not oauth_token:
                raise ValueError("YANDEX_OAUTH_TOKEN environment variable is not set!")
            track_ids = []

            # Формирование запроса
            url = f"https://api.music.yandex.net/playlist/{playlist_uuid}"
            headers = {
                "Authorization": f"OAuth {oauth_token}",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "Yandex-Music-API",
                "Accept": "application/json"
            }

            # Выполнение запроса
            response = requests.get(url, headers=headers, timeout=10)

            # Обработка ответа
            if response.status_code == 200:
                playlist_data = response.json()
                playlist_info = playlist_data.get('result', {})
                tracks_data = playlist_info.get('tracks', [])
                
                for track_info in tracks_data:
                    track_data = track_info.get('track', {})
                    track_id = track_data.get('id')
                    if track_id:
                        track_ids.append(track_id)
            else:
                raise ValueError(f"Ошибка при запросе: {response.status_code}")
            
            # Получаем треки по их ID
            if track_ids:
                return self.client.tracks(track_ids)
            return []
        except Exception as e:
            logger.error(f"Ошибка получения треков по UUID: {e}")
            raise ValueError(f"Не удалось получить треки по UUID: {str(e)}")

    def get_track_id(self, track: Any) -> Optional[str]:
        """Быстрое извлечение ID трека без полной информации"""
        try:
            if hasattr(track, 'id') and track.id:
                return str(track.id)
            elif hasattr(track, 'track_id') and track.track_id:
                return str(track.track_id)
            return None
        except Exception as e:
            logger.warning(f"Ошибка извлечения ID трека: {e}")
            return None

    @retry_on_error(max_retries=3, delay=0.5)
    def get_track_info(self, track: Any) -> Optional[Dict[str, Any]]:
        """Извлечение информации о треке с повторными попытками"""
        try:
            # ID трека
            track_id = self.get_track_id(track)
            if not track_id:
                return None
            
            # Если это короткая версия трека, получаем полную
            if hasattr(track, 'fetch_track'):
                try:
                    track = track.fetch_track()
                except:
                    pass  # Если не удалось получить полную версию, работаем с тем что есть
            
            # Название трека
            title = getattr(track, 'title', 'Неизвестный трек')
            if title == 'Неизвестный трек' and hasattr(track, 'track') and track.track:
                title = getattr(track.track, 'title', 'Неизвестный трек')
            
            # Исполнители
            artists = []
            if hasattr(track, 'artists') and track.artists:
                artists = [artist.name for artist in track.artists if hasattr(artist, 'name')]
            elif hasattr(track, 'artists_name') and track.artists_name:
                artists = track.artists_name
            elif hasattr(track, 'track') and track.track and hasattr(track.track, 'artists'):
                artists = [artist.name for artist in track.track.artists if hasattr(artist, 'name')]
            
            artists_str = ', '.join(artists) if artists else 'Неизвестный исполнитель'
            
            # ID альбома (для формирования ссылки)
            album_id = None
            if hasattr(track, 'albums') and track.albums:
                album = track.albums[0]
                album_id = getattr(album, 'id', None)
            elif hasattr(track, 'album_id') and track.album_id:
                album_id = track.album_id
            elif hasattr(track, 'track') and track.track and hasattr(track.track, 'albums') and track.track.albums:
                album = track.track.albums[0]
                album_id = getattr(album, 'id', None)
            
            # Формируем URL трека
            if album_id:
                url = f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
            else:
                url = f"https://music.yandex.ru/track/{track_id}"
            
            return {
                'id': track_id,
                'title': title,
                'artists': artists_str,
                'url': url
            }
        except Exception as e:
            logger.warning(f"Ошибка извлечения информации о треке: {e}")
            return None