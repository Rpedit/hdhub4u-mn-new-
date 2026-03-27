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
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w1280' 

_session: aiohttp.ClientSession | None = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    return _session

async def fetch_image(url, size=(860, 1200)):
    if not DREAMXBOTZ_IMAGE_FETCH or not url or not str(url).startswith("http"):
        return url
    try:
        session = await get_session()
        async with session.get(url, timeout=15) as response:
            if response.status != 200: return url
            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG", quality=95)
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Image Fetch Error: {e}")
        return url

async def _tmdb_api_call(path, params=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    headers = {'Authorization': f'Bearer {TMDB_BEARER_TOKEN}', 'Content-Type': 'application/json'}
    try:
        session = await get_session()
        async with session.get(url, params=params, headers=headers, ssl=False) as resp:
            if resp.status == 200: return await resp.json()
    except Exception: pass
    return None

async def get_movie_details(query, bulk=False, is_id=False):
    """IMDb Scraper Fallback"""
    from utils import listx_to_str, imdb
    try:
        if not is_id:
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
            'poster_url': movie.get('full-size cover url'),
            'imdb_id': f"tt{m_id}",
            'source': 'IMDb'
        }
    except Exception: return None

async def get_movie_detailsx(query, id=False):
    """Ultimate Multi-Source Fetcher"""
    if id or str(query).startswith("tt"):
        return await get_movie_details(query, is_id=True)
    
    clean_query = re.sub(r'\(?\d{4}\)?', '', str(query)).strip()
    year_match = re.search(r'\d{4}', str(query))
    year = year_match.group(0) if year_match else None

    # Step 1: TMDB Search
    params = {'query': clean_query, 'include_adult': 'false'}
    if year: params['year'] = year
    search_data = await _tmdb_api_call('search/multi', params=params)
    
    if search_data and search_data.get('results'):
        res = next((r for r in search_data['results'] if r.get('media_type') in ['movie', 'tv']), search_data['results'][0])
        details = await _tmdb_api_call(f"{res['media_type']}/{res['id']}", params={'append_to_response': 'external_ids'})
        
        if details:
            poster = f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}" if details.get('poster_path') else None
            genres = ", ".join([g['name'] for g in details.get('genres', [])]) if details.get('genres') else "N/A"
            
            # Step 2: Validation (If TMDB is poor, use IMDb)
            if genres == "N/A" or not poster:
                imdb_data = await get_movie_details(query)
                if imdb_data: return imdb_data
            
            return {
                'title': details.get('title') or details.get('name'),
                'year': (details.get('release_date') or details.get('first_air_date', 'N/A'))[:4],
                'rating': str(round(details.get('vote_average', 0), 1)) if details.get('vote_average') else "N/A",
                'genres': genres,
                'poster_url': poster,
                'imdb_id': details.get('external_ids', {}).get('imdb_id'),
                'tmdb_url': f"https://www.themoviedb.org/{res['media_type']}/{res['id']}",
                'source': 'TMDB'
            }
    
    # Step 3: Final Fallback to IMDb
    return await get_movie_details(query)
