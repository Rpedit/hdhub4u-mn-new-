import re
import asyncio
import aiohttp
import warnings
import logging
from io import BytesIO
from datetime import datetime
from difflib import SequenceMatcher
from PIL import Image
from info import DREAMXBOTZ_IMAGE_FETCH, TMDB_API_KEY, MAX_LIST_ELM

# Logger setup
logger = logging.getLogger(__name__)
LONG_IMDB_DESCRIPTION = False

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

# --- TMDB Configuration ---
TMDB_BEARER_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2ZGU3YTIyZGU1YjE5YTFjNmUyZGU5ZWEyMzE2ZmQxMCIsIm5iZiI6MTc0NTMyMjQ2Mi41MzMsInN1YiI6IjY4MDc4MWRlYzVjODAzNWZiMDhhNjExNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.rMMJ2-PBIv8Y7ybxPIEpIlzTEXzuwrm9ruKxAUCAsbw'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/original'
MIN_RUNTIME = 40

_session: aiohttp.ClientSession | None = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
    return _session

# --- CRITICAL: fetch_image function (Fixed for Import) ---
async def fetch_image(url, size=(860, 1200)):
    """Fetches and resizes images. Required by plugins/channel.py"""
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
        logger.error(f"Error in fetch_image: {e}")
        return url

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

def list_to_str(lst):
    if isinstance(lst, list):
        return ", ".join(map(str, lst))
    return str(lst) if lst else ""

# --- TMDB Helpers ---

async def _tmdb_get(path, params=None, api_key=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    _params = params.copy() if params else {}
    _headers = {}
    if api_key:
        _params['api_key'] = api_key
    elif TMDB_BEARER_TOKEN:
        _headers = {'Authorization': f'Bearer {TMDB_BEARER_TOKEN}', 'Content-Type': 'application/json'}
    
    session = await get_session()
    async with session.get(url, params=_params, headers=_headers, ssl=False) as resp:
        if resp.status == 200:
            return await resp.json()
        return None

async def _fetch_tmdb_data(query: str, api_key=None):
    # Search logic
    match = re.search(r'^(.*?)(?:\s+(\d{4}))?$', query.strip())
    title = match.group(1).strip() if match else query.strip()
    year = match.group(2) if match else None

    params = {'query': title, 'include_adult': 'false'}
    if year: params['year'] = year
    
    data = await _tmdb_get('search/multi', params=params, api_key=api_key)
    if not data or not data.get('results'): return None

    res = data['results'][0]
    m_type, m_id = res.get('media_type'), res.get('id')
    if m_type not in ['movie', 'tv']: return None

    details = await _tmdb_get(f"{m_type}/{m_id}", params={'append_to_response': 'credits,external_ids,images'}, api_key=api_key)
    return details, m_type

# --- IMDb Detail Fetcher ---

async def get_movie_details(query, bulk=False, id=False):
    """IMDb Scraper Fallback"""
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

        plot = movie.get('plot', [''])[0]
        return {
            'title': movie.get('title'),
            'year': movie.get('year'),
            'rating': movie.get('rating', 'N/A'),
            'genres': listx_to_str(movie.get('genres', [])),
            'plot': (plot[:800] + "...") if len(plot) > 800 else plot,
            'poster_url': movie.get('full-size cover url'),
            'imdb_id': f"tt{m_id}",
            'source': 'IMDb'
        }
    except Exception as e:
        logger.error(f"IMDb Error: {e}")
        return None

# --- Main Logic (TMDB with Fallback) ---

async def get_movie_detailsx(query, id=False):
    """Try TMDB first, then IMDb"""
    if id or str(query).startswith("tt"):
        return await get_movie_details(query, id=True)

    try:
        data = await _fetch_tmdb_data(query, api_key=TMDB_API_KEY)
        if not data:
            return await get_movie_details(query)
        
        details, m_type = data
        return {
            'title': details.get('title') or details.get('name'),
            'year': (details.get('release_date') or details.get('first_air_date', ''))[:4],
            'rating': details.get('vote_average', 'N/A'),
            'genres': ", ".join([g['name'] for g in details.get('genres', [])]),
            'plot': details.get('overview', ''),
            'imdb_id': details.get('external_ids', {}).get('imdb_id'),
            'tmdb_id': details.get('id'),
            'poster_url': f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}" if details.get('poster_path') else None,
            'source': 'TMDB'
        }
    except Exception:
        return await get_movie_details(query)
