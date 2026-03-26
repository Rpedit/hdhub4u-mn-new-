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
        return url
    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG")
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Error in fetch_image: {e}")
    return None

def list_to_str(lst):
    if lst:
        return ", ".join(map(str, lst))
    return ""

# Fix 1: listx_to_str typo fix (Alias created for compatibility)
listx_to_str = list_to_str

def _list_to_str_tmdb(data_list, limit=10, key=None):
    if not data_list or not isinstance(data_list, list):
        return None
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
    _params = params.copy() if params else {}
    _headers = {}

    # Fix 2: TMDB API Key Boolean Check
    if api_key and isinstance(api_key, str):
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
    params = {'query': title, 'language': 'en-US', 'page': 1, 'include_adult': 'false'}
    try:
        result = await _tmdb_get('search/multi', params=params, api_key=api_key)
    except Exception:
        return None, None
        
    multi_results = result.get('results', [])
    if not multi_results: return None, None

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
        except ValueError: continue
        if year and rd_date.year != year: continue
        candidate = {'type': mtype, 'id': r['id'], 'date': rd_date, 'score': r.get('popularity', 0), 'ratio': ratio}
        (candidates_upcoming if rd_date > today else candidates_past).append(candidate)

    final = candidates_past or candidates_upcoming
    if not final: return None, None
    top = sorted(final, key=lambda x: (x['ratio'], x['date']), reverse=True)[0]
    return top['type'], top['id']

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
    images_structured = _process_images(details.get('images', {}))
    
    return {
        'title': details.get('title') or details.get('name'),
        'year': (details.get('release_date') or details.get('first_air_date', ''))[:4],
        'rating': details.get('vote_average'),
        'votes': details.get('vote_count'),
        'plot': details.get('overview'),
        'poster_url': f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}" if details.get('poster_path') else None,
        'url': f"https://www.themoviedb.org/{media_type}/{details.get('id')}",
        'images': images_structured,
        'genres': _list_to_str_tmdb(details.get('genres', []), key='name'),
        'cast': _list_to_str_tmdb(details.get('credits', {}).get('cast', []), key='name', limit=15),
    }

async def get_movie_details(query, bulk=False, id=False, file=None):
    from utils import list_to_str, imdb
    if not id:
        query = query.strip().lower()
        # Fix 3: SyntaxWarning fix using raw string
        year_list = re.findall(r'[1-2]\d{3}$', query)
        title = query.replace(year_list[0], "").strip() if year_list else query
        search_result = await asyncio.to_thread(imdb.search_movie, title)
        if not search_result or not search_result.titles: return None
        movieid_str = search_result.titles[0].imdb_id
    else:
        movieid_str = query

    movie = await asyncio.to_thread(imdb.get_movie, movieid_str)
    if not movie: return None
    return {
        'title': movie.title,
        'rating': str(movie.rating),
        'plot': movie.plot[0] if isinstance(movie.plot, list) else movie.plot,
        'poster_url': movie.cover_url,
        'url': f"https://www.imdb.com/title/{movie.imdb_id}"
    }

async def get_movie_detailsx(query, id=False, file=None):
    q = str(query).strip()
    try:
        # Check if TMDB_API_KEY is usable string
        t_key = TMDB_API_KEY if isinstance(TMDB_API_KEY, str) and TMDB_API_KEY.lower() != "false" else None
        data = await _fetch_tmdb_data(q, api_key=t_key)
        if not data:
            return await get_movie_details(q)
        return data
    except Exception:
        return await get_movie_details(q)
