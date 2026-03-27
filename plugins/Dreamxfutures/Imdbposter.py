import re
import asyncio
import aiohttp
import warnings
import logging
from io import BytesIO
from datetime import datetime
from difflib import SequenceMatcher
from PIL import Image
# Assuming these are coming from your config/info file
from info import DREAMXBOTZ_IMAGE_FETCH, TMDB_API_KEY, MAX_LIST_ELM

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

# --- Configuration ---
TMDB_BEARER_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2ZGU3YTIyZGU1YjE5YTFjNmUyZGU5ZWEyMzE2ZmQxMCIsIm5iZiI6MTc0NTMyMjQ2Mi41MzMsInN1YiI6IjY4MDc4MWRlYzVjODAzNWZiMDhhNjExNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.rMMJ2-PBIv8Y7ybxPIEpIlzTEXzuwrm9ruKxAUCAsbw'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/original'
MIN_RUNTIME = 40

_session: aiohttp.ClientSession | None = None

async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

# --- Utility Helpers ---

def list_to_str(lst):
    if isinstance(lst, list):
        return ", ".join(map(str, lst))
    return str(lst) if lst else ""

def _extract_title_and_year(query: str):
    match = re.search(r'^(.*?)(?:\s+(\d{4}))?$', query.strip())
    if match:
        title, year_str = match.groups()
        year = int(year_str) if year_str and year_str.isdigit() else None
        return title.strip(), year
    return query.strip(), None

# --- TMDB Logic ---

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
    # Search for ID
    title, year = _extract_title_and_year(query)
    search_params = {'query': title, 'include_adult': 'false'}
    if year: search_params['year'] = year
    
    search_data = await _tmdb_get('search/multi', params=search_params, api_key=api_key)
    if not search_data or not search_data.get('results'):
        return None
    
    # Filter for movie/tv
    results = [r for r in search_data['results'] if r.get('media_type') in ['movie', 'tv']]
    if not results: return None
    
    top_res = results[0]
    m_type, m_id = top_res['media_type'], top_res['id']
    
    # Get Full Details
    detail_params = {'append_to_response': 'credits,external_ids,images,release_dates'}
    details = await _tmdb_get(f"{m_type}/{m_id}", params=detail_params, api_key=api_key)
    return details, m_type

# --- IMDb Logic (Fallback) ---

async def get_movie_details(query, bulk=False, id=False):
    """
    Standard IMDb fetcher using Cinemagoer/imdb-python.
    """
    from utils import listx_to_str, imdb # Import your local imdb object
    try:
        if not id:
            search_result = await asyncio.to_thread(imdb.search_movie, query.lower())
            if not search_result: return None
            if bulk: return search_result[:MAX_LIST_ELM]
            movie_id = search_result[0].movieID
        else:
            movie_id = query.replace("tt", "")

        movie = await asyncio.to_thread(imdb.get_movie, movie_id)
        if not movie: return None

        plot = movie.get('plot', [''])[0] if isinstance(movie.get('plot'), list) else movie.get('plot', "")
        
        return {
            'title': movie.get('title'),
            'year': movie.get('year'),
            'rating': movie.get('rating', 'N/A'),
            'genres': listx_to_str(movie.get('genres', [])),
            'plot': (plot[:800] + "...") if len(plot) > 800 else plot,
            'poster_url': movie.get('full-size cover url'),
            'imdb_id': f"tt{movie_id}",
            'source': 'IMDb'
        }
    except Exception as e:
        logger.error(f"IMDb Error: {e}")
        return None

# --- Main Entry Point (The Hybrid Function) ---

async def get_movie_detailsx(query, id=False):
    """
    The main function that tries TMDB first, then IMDb.
    """
    if id or str(query).startswith("tt"):
        # If ID is provided, go straight to IMDb detail
        return await get_movie_details(query, id=True)

    try:
        tmdb_data, m_type = await _fetch_tmdb_data(query, api_key=TMDB_API_KEY)
        if not tmdb_data:
            logger.info(f"TMDB not found for {query}, trying IMDb...")
            return await get_movie_details(query)
        
        # Normalize TMDB data to your bot's format
        res = {
            'title': tmdb_data.get('title') or tmdb_data.get('name'),
            'year': (tmdb_data.get('release_date') or tmdb_data.get('first_air_date', ''))[:4],
            'rating': tmdb_data.get('vote_average', 'N/A'),
            'genres': ", ".join([g['name'] for g in tmdb_data.get('genres', [])]),
            'plot': tmdb_data.get('overview', ''),
            'imdb_id': tmdb_data.get('external_ids', {}).get('imdb_id'),
            'tmdb_id': tmdb_data.get('id'),
            'poster_url': f"{TMDB_IMAGE_BASE_URL}{tmdb_data.get('poster_path')}" if tmdb_data.get('poster_path') else None,
            'source': 'TMDB'
        }
        return res

    except Exception as e:
        logger.error(f"TMDB request failed: {e}. Falling back to IMDb.")
        return await get_movie_details(query)

