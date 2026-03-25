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

async def fetch_image(url, size=(860, 1200)):
    if not DREAMXBOTZ_IMAGE_FETCH:
        logger.info("Image fetching is disabled.")
        return url

    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch image: {response.status} for {url}")
                return None

            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)

            out = BytesIO()
            img.save(out, format="JPEG")
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Unexpected error in fetch_image: {e}")
    return None

async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()

# FIX: Name should be consistent
def list_to_str(lst):
    if lst:
        return ", ".join(map(str, lst))
    return ""

def _list_to_str_tmdb(data_list, limit=10, key=None):
    if not data_list or not isinstance(data_list, list):
        return ""
    items = data_list[:limit]
    if key:
        return ", ".join(str(item.get(key, '')) for item in items if item)
    return ", ".join(str(item) for item in items if item)

def _extract_title_and_year(query: str):
    match = re.search(r'^(.*?)(?:\s+(\d{4}))?$', query.strip())
    if match:
        title, year_str = match.groups()
        year = int(year_str) if year_str and year_str.isdigit() else None
        return title.strip(), year
    return query.strip(), None

async def _tmdb_get(path, params=None, api_key=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    _params = {k: v for k, v in (params or {}).items() if v is not False} # FIX: Boolean False skip logic
    _headers = {}

    if api_key:
        _params['api_key'] = api_key
    elif TMDB_BEARER_TOKEN:
        _headers = {
            'Authorization': f'Bearer {TMDB_BEARER_TOKEN}',
            'Content-Type': 'application/json;charset=utf-8'
        }

    session = await get_session()
    async with session.get(url, params=_params, headers=_headers) as resp:
        resp.raise_for_status()
        return await resp.json()

async def _fetch_media_details(media_type: str, media_id: int, api_key=None):
    params = {'append_to_response': 'credits,external_ids,alternative_titles,release_dates,images'}
    return await _tmdb_get(f"{media_type}/{media_id}", params=params, api_key=api_key)

async def _search_media_id(query: str, api_key=None):
    title, year = _extract_title_and_year(query)
    params = {'query': title, 'language': 'en-US', 'page': 1, 'include_adult': 'false'} # String 'false' instead of bool
    result = await _tmdb_get('search/multi', params=params, api_key=api_key)
    multi_results = result.get('results', [])

    def get_ratio(s1, s2):
        if not s1 or not s2: return 0
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

    scored_results = []
    for r in multi_results:
        ratio = get_ratio(r.get('title') or r.get('name'), title)
        if ratio >= 0.85:
            scored_results.append((r, ratio))
    if not scored_results:
        scored_results = [(r, get_ratio(r.get('title') or r.get('name'), title)) for r in multi_results]

    today = datetime.utcnow().date()
    candidates_past, candidates_upcoming = [], []
    for r, ratio in scored_results:
        mtype = r.get('media_type')
        rd_str = r.get('release_date') or r.get('first_air_date')
        if not (rd_str and mtype in ['movie', 'tv']): continue
        try:
            rd_date = datetime.strptime(rd_str, '%Y-%m-%d').date()
        except: continue
        if year and rd_date.year != year: continue
        candidate = {'type': mtype, 'id': r['id'], 'date': rd_date, 'score': r.get('popularity', 0), 'ratio': ratio}
        (candidates_upcoming if rd_date > today else candidates_past).append(candidate)

    candidates_past.sort(key=lambda x: (x['ratio'], x['date'], x['score']), reverse=True)
    final = candidates_past or candidates_upcoming
    return (final[0]['type'], final[0]['id']) if final else (None, None)

def _process_images(images_data):
    posters_by_lang, backdrops_by_lang = {}, {}
    for img in images_data.get('posters', []):
        lang = img.get('iso_639_1') or 'no_lang'
        posters_by_lang.setdefault(lang, []).append(f"{TMDB_IMAGE_BASE_URL}{img['file_path']}")
    for img in images_data.get('backdrops', []):
        lang = img.get('iso_639_1') or 'no_lang'
        backdrops_by_lang.setdefault(lang, []).append(f"{TMDB_IMAGE_BASE_URL}{img['file_path']}")
    return {'posters': posters_by_lang, 'backdrops': backdrops_by_lang}

async def _fetch_tmdb_data(query: str, api_key=None):
    media_type, media_id = await _search_media_id(query, api_key=api_key)
    if not media_id: return None
    details = await _fetch_media_details(media_type, media_id, api_key=api_key)
    crew = details.get('credits', {}).get('crew', [])
    
    # Simple formatting for common fields
    output = {
        'title': details.get('title') or details.get('name'),
        'year': (details.get('release_date') or details.get('first_air_date', ''))[:4],
        'rating': details.get('vote_average'),
        'plot': details.get('overview'),
        'poster_url': f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}" if details.get('poster_path') else None,
        'url': f"https://www.themoviedb.org/{media_type}/{details.get('id')}",
        'genres': _list_to_str_tmdb(details.get('genres', []), key='name'),
        'cast': _list_to_str_tmdb(details.get('credits', {}).get('cast', []), key='name', limit=15),
        'director': _list_to_str_tmdb([p for p in crew if p.get('job') == 'Director'], key='name'),
        'images': _process_images(details.get('images', {}))
    }
    return output

async def get_movie_details(query, bulk=False, id=False, file=None):
    # FIX: Correct import inside function
    from utils import list_to_str as listx_to_str, imdb 
    
    if not id:
        query = (query.strip()).lower()
        title = query
        year_val = None
        # FIX: Added 'r' for raw string to fix SyntaxWarning
        year_list = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
        if year_list:
            year_val = year_list[0]
            title = (query.replace(year_val, "")).strip()
        
        search_result = await asyncio.to_thread(imdb.search_movie, title.lower())
        if not search_result or not search_result.titles: return None
        
        movie_list = search_result.titles[:MAX_LIST_ELM]
        movie_brief = movie_list[0]
        movieid_str = movie_brief.imdb_id 
    else:
        movieid_str = query

    movie = await asyncio.to_thread(imdb.get_movie, movieid_str)
    if not movie: return None
    
    plot = movie.plot[0] if isinstance(movie.plot, list) else movie.plot or ""
    if len(plot) > 800: plot = plot[:800] + "..."

    return {
        'title': movie.title,
        'rating': str(movie.rating),
        'plot': plot,
        'year': movie.year,
        'poster': movie.cover_url,
        'genres': listx_to_str(movie.genres),
        'cast': listx_to_str(movie.stars),
        'url': movie.url or f"https://www.imdb.com/title/{movieid_str}"
    }

async def get_movie_detailsx(query, id=False, file=None):
    q = str(query).strip()
    try:
        data = await _fetch_tmdb_data(q, api_key=TMDB_API_KEY if TMDB_API_KEY else None)
        if not data:
            return await get_movie_details(q)
        return data
    except Exception as e:
        logger.error(f"Fallback to IMDb: {e}")
        return await get_movie_details(q)
