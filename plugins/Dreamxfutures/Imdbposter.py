import re
import asyncio
import aiohttp
import warnings
import logging
from io import BytesIO
from datetime import datetime
from PIL import Image
from info import DREAMXBOTZ_IMAGE_FETCH, TMDB_API_KEY, MAX_LIST_ELM

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

# --- Configuration ---
TMDB_BEARER_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2ZGU3YTIyZGU1YjE5YTFjNmUyZGU5ZWEyMzE2ZmQxMCIsIm5iZiI6MTc0NTMyMjQ2Mi41MzMsInN1YiI6IjY4MDc4MWRlYzVjODAzNWZiMDhhNjExNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.rMMJ2-PBIv8Y7ybxPIEpIlzTEXzuwrm9ruKxAUCAsbw'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w1280' # Optimized for High Quality Posters

_session: aiohttp.ClientSession | None = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session

# --- Image Fetcher (For Telegram Notifications) ---
async def fetch_image(url, size=(860, 1200)):
    if not DREAMXBOTZ_IMAGE_FETCH or not url:
        return url
    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return url
            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG")
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Image Fetch Error: {e}")
        return url

# --- TMDB Logic (Fixing Genres & Image) ---
async def _tmdb_get(path, params=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    _params = params.copy() if params else {}
    _headers = {'Authorization': f'Bearer {TMDB_BEARER_TOKEN}', 'Content-Type': 'application/json'}
    
    session = await get_session()
    async with session.get(url, params=_params, headers=_headers, ssl=False) as resp:
        if resp.status == 200:
            return await resp.json()
    return None

async def _fetch_tmdb_data(query: str):
    # Extract Title/Year
    match = re.search(r'^(.*?)(?:\s+(\d{4}))?$', query.strip())
    title = match.group(1).strip() if match else query.strip()
    year = match.group(2) if match else None

    search_params = {'query': title, 'include_adult': 'false'}
    if year: search_params['year'] = year
    
    search_data = await _tmdb_get('search/multi', params=search_params)
    if not search_data or not search_data.get('results'):
        return None

    # Get the best movie/tv match
    res = next((r for r in search_data['results'] if r.get('media_type') in ['movie', 'tv']), search_data['results'][0])
    m_type, m_id = res.get('media_type', 'movie'), res.get('id')

    # IMPORTANT: Fetch Full Details to get Genres & High Res Poster
    details = await _tmdb_get(f"{m_type}/{m_id}", params={'append_to_response': 'external_ids'})
    if not details: return None

    # Fix Genres
    genres_list = details.get('genres', [])
    genres = ", ".join([g['name'] for g in genres_list]) if genres_list else "N/A"

    return {
        'title': details.get('title') or details.get('name'),
        'year': (details.get('release_date') or details.get('first_air_date', ''))[:4] or "N/A",
        'rating': str(round(details.get('vote_average', 0), 1)) if details.get('vote_average') else "N/A",
        'genres': genres,
        'plot': details.get('overview', 'No plot available.'),
        'poster_url': f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}" if details.get('poster_path') else None,
        'imdb_id': details.get('external_ids', {}).get('imdb_id'),
        'source': 'TMDB'
    }

# --- IMDb Fallback ---
async def get_movie_details(query, bulk=False, id=False):
    from utils import listx_to_str, imdb
    try:
        if not id:
            search = await asyncio.to_thread(imdb.search_movie, query.lower())
            if not search: return None
            if bulk: return search[:MAX_LIST_ELM]
            m_id = search[0].movieID
        else:
            m_id = query.replace("tt", "")

        movie = await asyncio.to_thread(imdb.get_movie, m_id)
        if not movie: return None

        return {
            'title': movie.get('title'),
            'year': movie.get('year') or "N/A",
            'rating': str(movie.get('rating', 'N/A')),
            'genres': listx_to_str(movie.get('genres', [])) or "N/A",
            'plot': movie.get('plot', ['No plot available.'])[0],
            'poster_url': movie.get('full-size cover url'),
            'imdb_id': f"tt{m_id}",
            'source': 'IMDb'
        }
    except Exception:
        return None

# --- Main Logic ---
async def get_movie_detailsx(query, id=False):
    if id or str(query).startswith("tt"):
        return await get_movie_details(query, id=True)

    try:
        # 1. Try TMDB (Upgraded)
        data = await _fetch_tmdb_data(query)
        if data:
            return data
        
        # 2. If TMDB Fails, Try IMDb
        return await get_movie_details(query)
    except Exception:
        return await get_movie_details(query)
