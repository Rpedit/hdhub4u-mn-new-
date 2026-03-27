import re
import asyncio
import aiohttp
import warnings
import logging
from io import BytesIO
from datetime import datetime
from PIL import Image
from info import DREAMXBOTZ_IMAGE_FETCH, TMDB_API_KEY, MAX_LIST_ELM

# Logger Setup
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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

# --- Image Fetching & Processing ---
async def fetch_image(url, size=(860, 1200)):
    """Fetches image, resizes it for Telegram posters."""
    if not DREAMXBOTZ_IMAGE_FETCH or not url or not str(url).startswith("http"):
        return url
    try:
        session = await get_session()
        async with session.get(url, timeout=15) as response:
            if response.status != 200:
                return url
            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG", quality=95)
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Error in fetch_image: {e}")
        return url

# --- TMDB Internal Helpers ---
async def _tmdb_api_call(path, params=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    headers = {
        'Authorization': f'Bearer {TMDB_BEARER_TOKEN}',
        'Content-Type': 'application/json;charset=utf-8'
    }
    try:
        session = await get_session()
        async with session.get(url, params=params, headers=headers, ssl=False) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.error(f"TMDB API Error: {e}")
    return None

async def _get_tmdb_details(query):
    """Deep search and fetch from TMDB."""
    # Clean query: Remove (2025) or similar
    clean_query = re.sub(r'\(?\d{4}\)?', '', query).strip()
    year_match = re.search(r'\d{4}', query)
    year = year_match.group(0) if year_match else None

    search_params = {'query': clean_query, 'include_adult': 'false'}
    if year: search_params['year'] = year

    search_data = await _tmdb_api_call('search/multi', params=search_params)
    if not search_data or not search_data.get('results'):
        return None

    # Filter for valid media
    results = [r for r in search_data['results'] if r.get('media_type') in ['movie', 'tv']]
    if not results: return None
    
    top = results[0]
    m_type, m_id = top['media_type'], top['id']

    # Get detailed info (Genres, IMDb ID, Poster)
    details = await _tmdb_api_call(f"{m_type}/{m_id}", params={'append_to_response': 'external_ids,images'})
    if not details: return None

    genres = ", ".join([g['name'] for g in details.get('genres', [])]) if details.get('genres') else "N/A"
    poster_path = details.get('poster_path')
    
    return {
        'title': details.get('title') or details.get('name'),
        'year': (details.get('release_date') or details.get('first_air_date', 'N/A'))[:4],
        'rating': str(round(details.get('vote_average', 0), 1)) if details.get('vote_average') else "N/A",
        'genres': genres,
        'poster_url': f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None,
        'imdb_id': details.get('external_ids', {}).get('imdb_id'),
        'plot': details.get('overview', 'N/A'),
        'source': 'TMDB'
    }

# --- IMDb Internal Helpers (Fallback) ---
async def get_movie_details(query, bulk=False, is_id=False):
    """Original IMDb Scraper using Cinemagoer."""
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

        plot = movie.get('plot', ['N/A'])[0] if isinstance(movie.get('plot'), list) else movie.get('plot', 'N/A')
        poster = movie.get('full-size cover url')

        return {
            'title': movie.get('title'),
            'year': movie.get('year') or "N/A",
            'rating': str(movie.get('rating', 'N/A')),
            'genres': listx_to_str(movie.get('genres', [])) if movie.get('genres') else "N/A",
            'poster_url': poster,
            'imdb_id': f"tt{m_id}",
            'plot': (plot[:500] + "...") if len(plot) > 500 else plot,
            'source': 'IMDb'
        }
    except Exception as e:
        logger.error(f"IMDb Scraper Error: {e}")
        return None

# --- Main Logic Controller ---
async def get_movie_detailsx(query, id=False):
    """The Ultimate Movie Data Fetcher."""
    query = str(query).strip()
    
    # Check if direct ID
    if id or query.startswith("tt"):
        return await get_movie_details(query, is_id=True)

    # 1. Try TMDB First
    data = await _get_tmdb_details(query)

    # 2. Validation: Agar Genres N/A hain ya Poster nahi mila, toh IMDb try karo
    if not data or data.get('genres') == "N/A" or not data.get('poster_url'):
        logger.info(f"Incomplete data from TMDB for '{query}'. Switching to IMDb...")
        imdb_data = await get_movie_details(query)
        
        if imdb_data:
            # Agar TMDB ke paas rating thi par IMDb ke paas nahi, toh merge kar sakte hain
            if data and imdb_data.get('rating') == "N/A":
                imdb_data['rating'] = data.get('rating')
            return imdb_data

    return data if data else await get_movie_details(query)

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
