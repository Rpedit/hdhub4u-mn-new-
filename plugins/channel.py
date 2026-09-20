import re
import logging
import asyncio
import aiohttp
import inspect
from datetime import datetime
from bs4 import BeautifulSoup
from collections import defaultdict
from plugins.Dreamxfutures.Imdbposter import get_movie_detailsx, fetch_image, get_movie_details
from database.users_chats_db import db
from pyrogram import Client, filters, enums
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, LINK_PREVIEW, ABOVE_PREVIEW, BAD_WORDS, LANDSCAPE_POSTER, TMDB_POSTER
from Script import script
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp
from pymongo.errors import PyMongoError, DuplicateKeyError
from pyrogram.errors import MessageIdInvalid, MessageNotModified, FloodWait
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_BASE_IGNORE_WORDS = {
    "rarbg", "dub", "sub", "sample", "mkv", "mp4", "avi", "aac", "ac3", "eac3", "ddp", "ddp5", "atmos", "dts",
    "combined", "esub", "msub", "proper", "repack", "unrated", "extended", "imax", "remux", "10bit", "10-bit",
    "x264", "x265", "h264", "h265", "hevc", "avc", "dovi", "hdr", "hdr10",
    "web", "dl", "bonus", "special",
    "action", "adventure", "animation", "biography", "comedy", "crime",
    "documentary", "drama", "fantasy", "film-noir", "history",
    "horror", "music", "musical", "mystery", "romance", "sci-fi", "sport",
    "thriller", "war", "western", "hdcam", "hdtc", "camrip", "cam", "ts", "tc", "hdts",
    "telesync", "dvdscr", "dvdrip", "predvd", "webrip", "web-dl", "tvrip",
    "hdtv", "web dl", "webdl", "bluray", "brrip", "bdrip", "360p", "480p",
    "720p", "1080p", "2160p", "4k", "1440p", "540p", "240p", "140p",
    "hdrip", "hq-hdrip", "hq-hdtc", "hq-cam", "hq-ts", "hq-predvd",
    "dual", "multi", "audio",
    "v1", "v2", "v3", "v4", "v5", "v6", "version", "ver", "cleaned", "clean",
    "nf", "netflix", "sonyliv", "sony", "sliv", "amzn", "prime",
    "primevideo", "hotstar", "zee5", "jio", "jhs", "aha", "hbo", "paramount",
    "apple", "atv", "atvp", "appletv", "hoichoi", "sunnxt", "viki", "cr", "crunchyroll", "hulu",
    "disney", "dnp", "lionsgate", "lionsgateplay", "peacock", "max", "alt",
    "altbalaji", "altt", "shemaroo", "shemaroome", "chaupal", "stage",
    "planetmarathi", "manorama", "manoramamax", "tubi"
}

IGNORE_WORDS = _BASE_IGNORE_WORDS | set(BAD_WORDS if isinstance(BAD_WORDS, (list, tuple, set)) else [])

CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi",
    "tam": "Tamil", "tamil": "Tamil",
    "kan": "Kannada", "kannada": "Kannada",
    "tel": "Telugu", "telugu": "Telugu",
    "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English",
    "pun": "Punjabi", "punjabi": "Punjabi",
    "ben": "Bengali", "bengali": "Bengali",
    "mar": "Marathi", "marathi": "Marathi",
    "guj": "Gujarati", "gujarati": "Gujarati",
    "urd": "Urdu", "urdu": "Urdu",
    "kor": "Korean", "korean": "Korean",
    "jpn": "Japanese", "japanese": "Japanese",
    "bho": "Bhojpuri", "bhojpuri": "Bhojpuri",
    "ori": "Odia", "odia": "Odia", "oriya": "Odia",
    "asm": "Assamese", "assamese": "Assamese",
    "spa": "Spanish", "spanish": "Spanish",
    "fre": "French", "french": "French", "fra": "French",
    "ger": "German", "german": "German", "deu": "German",
    "ita": "Italian", "italian": "Italian",
    "rus": "Russian", "russian": "Russian",
    "chi": "Chinese", "chinese": "Chinese", "zho": "Chinese",
    "tha": "Thai", "thai": "Thai",
    "ind": "Indonesian", "indonesian": "Indonesian",
    "dual": "Dual Audio", "multi": "Multi Audio",
    "hq dub": "HQ Dub", "hq-dub": "HQ Dub",
    "hq audio": "HQ Audio", "hq-audio": "HQ Audio",
    "line audio": "Line Audio", "hq line": "HQ Line", "hq-line": "HQ Line",
    "mic audio": "Mic Audio", "clean audio": "Clean Audio"
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix",
    "sonyliv": "SonyLiv", "sony": "SonyLiv", "sliv": "SonyLiv",
    "amzn": "Amazon Prime Video", "prime": "Amazon Prime Video", "primevideo": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "disney": "Disney+", "dnp": "Disney+",
    "zee5": "Zee5",
    "jio": "JioHotstar", "jhs": "JioHotstar",
    "aha": "Aha", "hbo": "HBO Max", "max": "Max",
    "paramount": "Paramount+",
    "apple": "Apple TV+", "atv": "Apple TV+", "atvp": "Apple TV+", "appletv": "Apple TV+",
    "hoichoi": "Hoichoi", "sunnxt": "Sun NXT", "viki": "Viki",
    "cr": "Crunchyroll", "crunchyroll": "Crunchyroll",
    "hulu": "Hulu",
    "peacock": "Peacock",
    "lionsgate": "Lionsgate Play", "lionsgateplay": "Lionsgate Play",
    "altbalaji": "ALTT", "alt": "ALTT", "altt": "ALTT",
    "shemaroo": "ShemarooMe", "shemaroome": "ShemarooMe",
    "chaupal": "Chaupal",
    "stage": "Stage",
    "planetmarathi": "Planet Marathi",
    "manorama": "ManoramaMAX", "manoramamax": "ManoramaMAX",
    "tubi": "Tubi"
}

STANDARD_FORMATS = {
    "hdtc": "HDTC", "hd-tc": "HDTC", "hq-hdtc": "HQ-HDTC",
    "hdcam": "HDCam", "hd-cam": "HDCam", "hq-hdcam": "HQ-HDCam",
    "cam": "CAM", "camrip": "CamRip", "hq-cam": "HQ-CAM",
    "ts": "TS", "hdts": "HDTS", "hq-ts": "HQ-TS", "tc": "TC",
    "telesync": "TeleSync", "predvd": "PreDVD", "hq-predvd": "HQ-PreDVD",
    "dvdrip": "DVDRip", "dvdscr": "DVDScr",
    "webrip": "WEBRip", "web-dl": "WEB-DL", "webdl": "WEB-DL", "web dl": "WEB-DL",
    "bluray": "BluRay", "brrip": "BRRip", "bdrip": "BDRip",
    "remux": "Remux", "imax": "IMAX",
    "hdrip": "HDRip", "hq-hdrip": "HQ-HDRip",
    "hdtv": "HDTV", "tvrip": "TVRip",
    "hevc": "HEVC", "10bit": "10-Bit", "10-bit": "10-Bit",
    "hdr": "HDR", "hdr10": "HDR10", "hdr10+": "HDR10+",
    "dv": "Dolby Vision", "dovi": "Dolby Vision"
}

RES_ORDER = {
    "140p": 140, "240p": 240, "360p": 360, "480p": 480,
    "540p": 540, "720p": 720, "1080p": 1080, "1440p": 1440,
    "2160p": 2160, "4k": 2160
}

CLEAN_PATTERN = re.compile(r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+|\([\@^]+\)|\[[\@^]+\]')
NORMALIZE_PATTERN = re.compile(r"[._]+|[()\[\]{}:;'–!,.?_]")

RESOLUTION_PATTERN = re.compile(r"\b(?:2160p|4K|1440p|1080p|720p|540p|480p|360p|240p|140p)\b", re.IGNORECASE)
SOURCE_PATTERN = re.compile(
    r"\b(?:HDCam|HD-Cam|HQ-HDCam|HDTC|HD-TC|HQ-HDTC|CamRip|CAM|HQ-CAM|TS|HDTS|HQ-TS|TC|TeleSync|DVDScr|DVDRip|PreDVD|HQ-PreDVD|"
    r"WEBRip|WEB-DL|TVRip|HDTV|WEB DL|WebDl|BluRay|BRRip|BDRip|Remux|IMAX|"
    r"HEVC|10Bit|10-Bit|HDRip|HQ-HDRip|HDR10\+|HDR10|HDR|DV|DoVi)\b",
    re.IGNORECASE
)
VERSION_STANDALONE = re.compile(r"\b(?:[vV]\d+|ver\.?\s*\d+|version\s*\d+)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")

# Season & Episode Patterns (Bonus & Special Safe)
BONUS_RANGE_REGEX = re.compile(r'\bS(\d{1,2})[\s._-]*(?:Bonus|Special)[\s._-]*E(?:p(?:isode)?)?0*(\d{1,3})\s*(?:to|-)\s*(?:E(?:p(?:isode)?)?)?0*(\d{1,3})\b', re.IGNORECASE)
BONUS_REGEX = re.compile(r'\bS(\d{1,2})[\s._-]*(?:Bonus|Special)[\s._-]*E(?:p(?:isode)?)?0*(\d{1,3})\b', re.IGNORECASE)
RANGE_REGEX = re.compile(r'\bS(\d{1,2})[\s._-]*(?:Part)?[\s._-]*E(?:p(?:isode)?)?0*(\d{1,3})\s*(?:to|-)\s*(?:E(?:p(?:isode)?)?)?0*(\d{1,3})', re.IGNORECASE)
SINGLE_REGEX = re.compile(r'\bS(\d{1,2})[\s._-]*(?:Part)?[\s._-]*E(?:p(?:isode)?)?0*(\d{1,3})\b', re.IGNORECASE)
NAMED_REGEX = re.compile(r'Season\s*0*(\d{1,2})[\s\-,:]*(?:Part)?[\s\-,:]*Ep(?:isode)?\s*0*(\d{1,3})\b', re.IGNORECASE)
X_REGEX = re.compile(r'\b0*([1-9]\d?)\s*[xX]\s*0*(\d{1,2})\b', re.IGNORECASE)
DAY_REGEX = re.compile(r'\b(?:S(?:eason)?\s*0*(\d{1,2})[^\w\n\r]*)?(?:Day|D)\s*0*(\d{1,3})\b', re.IGNORECASE)
NO_S_REGEX = re.compile(r'\b(?:Season\s*)?0*(\d{1,2})[\s._-]+E(?:p(?:isode)?)?0*(\d{1,3})\b', re.IGNORECASE)
EP_ONLY_RANGE = re.compile(r'\b(?:EP|Episode)0*(\d{1,3})\s*-\s*0*(\d{1,3})\b', re.IGNORECASE)
EP_ONLY_SINGLE = re.compile(r'\b(?:EP|Episode)\.?\s*0*(\d{1,3})\b', re.IGNORECASE)

MEDIA_FILTER = filters.document | filters.video | filters.audio

locks = defaultdict(asyncio.Lock)
pending_updates = {}
sending_updates = set()


def clean_mentions_links(text: str) -> str:
    return CLEAN_PATTERN.sub("", text or "").strip()


def normalize(s: str) -> str:
    s = NORMALIZE_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def remove_ignored_words(text: str) -> str:
    ignore_words_lower = {w.lower() for w in IGNORE_WORDS}
    return " ".join(
        word for word in text.split()
        if word.lower() not in ignore_words_lower
    )


def is_good_title_match(query: str, found_title: str) -> bool:
    if not query or not found_title:
        return False

    q_raw = YEAR_PATTERN.sub('', query).strip()
    f_raw = YEAR_PATTERN.sub('', found_title).strip()

    def clean_words(s: str):
        s = re.sub(r'^(the|a|an)\s+', '', s, flags=re.IGNORECASE)
        s = re.sub(r"['’]", "", s)
        s = normalize(s).lower()
        return [w for w in s.split() if w]

    q_words = clean_words(q_raw)
    f_words = clean_words(f_raw)

    if not q_words or not f_words:
        return False

    if q_words == f_words:
        return True

    for sep in [':', '-', '–', '—', '|']:
        if sep in f_raw:
            main_part = f_raw.split(sep)[0].strip()
            main_words = clean_words(main_part)
            if q_words == main_words:
                return True

    if len(f_words) >= len(q_words):
        if f_words[:len(q_words)] == q_words:
            extra_words = f_words[len(q_words):]
            allowed_extra = {
                "tv", "series", "hindi", "telugu", "tamil", "kannada", 
                "malayalam", "korea", "korean", "ott", "season", "show"
            }
            if set(extra_words).issubset(allowed_extra) or not extra_words:
                return True

    return False


def get_qualities(text: str) -> str:
    if not text:
        return "N/A"

    v_match = VERSION_STANDALONE.search(text)
    version_str = None
    if v_match:
        raw_v = v_match.group(0).upper()
        raw_v = re.sub(r'^(?:VER\.?|VERSION)\s*', 'V', raw_v)
        if not raw_v.startswith("V"):
            raw_v = f"V{raw_v}"
        version_str = raw_v

    resolutions = []
    for r in RESOLUTION_PATTERN.findall(text):
        norm_r = r.lower() if r.lower() != "4k" else "4K"
        if norm_r not in resolutions:
            resolutions.append(norm_r)

    sources = []
    for s in SOURCE_PATTERN.findall(text):
        s_norm = re.sub(r"[._]+", "-", s).strip().lower()
        formatted = STANDARD_FORMATS.get(s_norm, s.upper())
        if formatted not in sources:
            sources.append(formatted)

    if version_str:
        attached = False
        for idx, s in enumerate(sources):
            if any(k in s.upper() for k in ["HDTC", "CAM", "TS", "PREDVD", "WEBRIP", "WEB-DL", "RIP", "BLURAY"]):
                sources[idx] = f"{s} {version_str}"
                attached = True
                break
        if not attached:
            sources.append(version_str)

    all_items = resolutions + sources
    return ", ".join(all_items) if all_items else "N/A"


def format_movie_qualities(quality_list: list) -> str:
    if not quality_list:
        return "N/A"

    resolutions = set()
    sources = set()
    versions = set()

    for item in quality_list:
        if not item or item == "N/A":
            continue

        v_matches = VERSION_STANDALONE.findall(item)
        for vm in v_matches:
            v_num = re.sub(r"\D", "", vm)
            if v_num:
                versions.add(int(v_num))

        for r in RESOLUTION_PATTERN.findall(item):
            norm_r = r.lower() if r.lower() != "4k" else "4K"
            resolutions.add(norm_r)

        for s in SOURCE_PATTERN.findall(item):
            s_norm = re.sub(r"[._]+", "-", s).strip().lower()
            formatted = STANDARD_FORMATS.get(s_norm, s.upper())
            sources.add(formatted)

    if "HQ-HDTC" in sources and "HDTC" in sources:
        sources.remove("HDTC")
    if "HQ-CAM" in sources:
        sources.discard("CAM")
        sources.discard("HDCam")
    if "HDCam" in sources and "CAM" in sources:
        sources.remove("CAM")
    if "HQ-TS" in sources:
        sources.discard("TS")
        sources.discard("HDTS")
    if "HDTS" in sources and "TS" in sources:
        sources.remove("TS")
    if "HQ-PreDVD" in sources and "PreDVD" in sources:
        sources.remove("PreDVD")
    if "HDR10+" in sources:
        sources.discard("HDR10")
        sources.discard("HDR")
    elif "HDR10" in sources:
        sources.discard("HDR")

    sorted_res = sorted(resolutions, key=lambda x: RES_ORDER.get(x.lower(), 9999))
    version_str = f"V{max(versions)}" if versions else ""

    source_list = []
    for s in sorted(sources):
        if s and s not in source_list:
            source_list.append(s)

    if version_str:
        attached = False
        for idx, s in enumerate(source_list):
            if any(k in s.upper() for k in ["HDTC", "CAM", "TS", "PREDVD", "WEBRIP", "WEB-DL", "RIP", "BLURAY"]):
                source_list[idx] = f"{s} {version_str}"
                attached = True
                break
        if not attached:
            source_list.append(version_str)

    final_parts = sorted_res + source_list
    return ", ".join(final_parts) if final_parts else "N/A"


def extract_ott_platform(text: str) -> str:
    text = text.lower()
    platforms = {
        plat
        for key, plat in OTT_PLATFORMS.items()
        if re.search(rf"\b{re.escape(key)}\b", text)
    }
    return " | ".join(sorted(platforms)) if platforms else "N/A"


def get_clean_title(name: str) -> str:
    t = re.sub(r'\b(19|20)\d{2}\b', '', name)
    return normalize(t).lower()


def format_runtime(runtime_val, is_series: bool = False) -> str:
    if not runtime_val or str(runtime_val).strip().upper() in ("N/A", "NONE", "0", "-", ""):
        return "N/A"

    if isinstance(runtime_val, (list, tuple)):
        if not runtime_val:
            return "N/A"
        runtime_val = runtime_val[0]

    runtime_str = str(runtime_val).strip()
    runtime_str = re.sub(r'[\s/]*(?:ep|episode)\b', '', runtime_str, flags=re.IGNORECASE).strip()

    total_mins = 0
    try:
        try:
            total_mins = int(float(runtime_str))
        except ValueError:
            colon_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", runtime_str)
            if colon_match:
                hours = int(colon_match.group(1))
                mins = int(colon_match.group(2))
                total_mins = (hours * 60) + mins
            else:
                hours_match = re.search(r"(\d+)\s*(?:h|hr|hour)s?", runtime_str, re.IGNORECASE)
                mins_match = re.search(r"(\d+)\s*(?:m|min|minute)s?", runtime_str, re.IGNORECASE)

                if hours_match or mins_match:
                    hours = int(hours_match.group(1)) if hours_match else 0
                    mins = int(mins_match.group(1)) if mins_match else 0
                    total_mins = (hours * 60) + mins
                else:
                    numbers = re.findall(r"\d+", runtime_str)
                    if numbers:
                        total_mins = int(numbers[0])
    except Exception:
        return "N/A"

    if total_mins <= 0:
        return "N/A"

    if total_mins >= 60:
        hours = total_mins // 60
        mins = total_mins % 60
        return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
    else:
        return f"{total_mins}m"


async def fetch_imdb_safely(base_name: str, is_series: bool, year: Optional[str] = None) -> dict:
    sig = inspect.signature(get_movie_details)
    kwargs = {}
    if "is_series" in sig.parameters:
        kwargs["is_series"] = is_series
    elif "media_type" in sig.parameters:
        kwargs["media_type"] = "tv" if is_series else "movie"

    queries = []
    if is_series:
        if year:
            queries.append(f"{base_name} {year}")
        queries.append(f"{base_name} Series")
        queries.append(f"{base_name} TV")
        queries.append(base_name)
    else:
        if year:
            queries.append(f"{base_name} {year}")
        queries.append(base_name)

    best_fallback = {}
    for q in queries:
        try:
            res = await get_movie_details(q, **kwargs) if kwargs else await get_movie_details(q)
            if res and isinstance(res, dict):
                title = res.get("title")
                if title and is_good_title_match(base_name, title):
                    return res
                if not best_fallback and res:
                    best_fallback = res
        except Exception as e:
            logger.warning(f"Error fetching IMDb details for '{q}': {e}")

    return best_fallback


async def fetch_tmdb_safely(tmdb_query: str, base_name: str, is_series: bool) -> dict:
    if not TMDB_POSTER:
        return {}

    sig = inspect.signature(get_movie_detailsx)
    kwargs = {}
    if "is_series" in sig.parameters:
        kwargs["is_series"] = is_series
    elif "media_type" in sig.parameters:
        kwargs["media_type"] = "tv" if is_series else "movie"

    if tmdb_query and tmdb_query.startswith("tt"):
        try:
            res = await get_movie_detailsx(tmdb_query, **kwargs) if kwargs else await get_movie_detailsx(tmdb_query)
            if res and not res.get("error"):
                return res
        except Exception:
            pass

    queries = []
    if is_series:
        queries.append(f"{base_name} Series")
        queries.append(base_name)
    else:
        queries.append(tmdb_query or base_name)

    best_fallback = {}
    for q in queries:
        try:
            res = await get_movie_detailsx(q, **kwargs) if kwargs else await get_movie_detailsx(q)
            if res and not res.get("error"):
                title = res.get("title") or res.get("name")
                if title and is_good_title_match(base_name, title):
                    return res
                if not best_fallback:
                    best_fallback = res
        except Exception:
            pass

    return best_fallback


async def get_hdhub_base_url() -> Optional[str]:
    try:
        if not hasattr(db, 'db'):
            return None
        setting = await db.db.settings.find_one({"_id": "hdhub_base_url"})
        if setting and setting.get("url"):
            return setting["url"]
    except Exception:
        pass
    return None


async def get_blogger_poster_url(base_name: str, year: Optional[str] = None) -> Optional[str]:
    try:
        blog_url = "https://tmdbimdbhdhub4u.blogspot.com"
        if hasattr(db, 'db'):
            setting = await db.db.settings.find_one({"_id": "blogger_base_url"})
            if setting and setting.get("url"):
                blog_url = setting["url"].rstrip("/")

        feed_url = f"{blog_url}/feeds/posts/default?alt=json&max-results=50"

        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(feed_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            return None

        clean_query = f"{base_name} {year}".strip() if year else base_name

        for entry in entries:
            post_title = entry.get("title", {}).get("$t", "")
            if is_good_title_match(clean_query, post_title) or is_good_title_match(base_name, post_title):
                content_html = entry.get("content", {}).get("$t", "")
                soup = BeautifulSoup(content_html, "html.parser")
                img_tag = soup.find("img")
                if img_tag and img_tag.get("src"):
                    img_url = img_tag["src"]
                    img_url = re.sub(r'/s\d+(-c)?/', '/s1600/', img_url)
                    img_url = re.sub(r'/w\d+-[h\d]+/', '/', img_url)
                    return img_url
    except Exception as e:
        logger.error(f"Error fetching Blogger poster: {e}")
    return None


@Client.on_message(filters.command("setdomain"))
async def set_domain_handler(bot, message):
    if len(message.command) < 2:
        current_url = await get_hdhub_base_url()
        current_text = f"<code>{current_url}</code>" if current_url else "<i>Not Set Yet!</i>"
        return await message.reply_text(
            f"🌐 **Current HDHub4u URL:** {current_text}\n\n"
            f"💡 **Usage:** <code>/setdomain https://new-domain.com</code>"
        )
    new_url = message.command[1].strip().split("?")[0].rstrip("/")
    try:
        await db.db.settings.update_one(
            {"_id": "hdhub_base_url"},
            {"$set": {"url": new_url}},
            upsert=True
        )
        await message.reply_text(f"✅ **HDHub4u base URL successfully updated to:**\n<code>{new_url}</code>")
    except Exception as e:
        await message.reply_text(f"❌ Failed to update domain: {e}")


async def get_hdhub4u_data(base_name: str) -> Tuple[str, str, str]:
    genres = "N/A"
    rating = "N/A"
    imdb_url = ""
    try:
        base_url = await get_hdhub_base_url()
        if not base_url:
            return "N/A", "N/A", ""

        clean_search_query = re.sub(r'\b(season|s)\s*\d+\b', '', base_name, flags=re.IGNORECASE)
        clean_query = re.sub(r"\b(19|20)\d{2}\b", "", clean_search_query).strip()
        clean_query = re.sub(r"[._]+|[()\[\]{}:;'–!,.?_]", " ", clean_query).strip()
        search_url = f"{base_url.rstrip('/')}/?s={clean_query.replace(' ', '+')}"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(search_url, headers=headers) as resp:
                if resp.status != 200:
                    return "N/A", "N/A", ""
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["header", "nav", "footer", "aside", "script", "style"]):
            tag.decompose()
        for widget in soup.select(".sidebar, #sidebar, .widget, .trending, .slider, .carousel, .featured"):
            widget.decompose()

        clean_q = re.sub(r"['’]", "", clean_query).lower()
        query_words = [re.sub(r'[^a-zA-Z0-9]', '', w).lower() for w in clean_q.split()]
        query_words = [w for w in query_words if len(w) >= 3]

        candidate_links = soup.select(
            ".archive-posts h2 a, .recent-movies a, .blog-posts a, article a, .post-item a, .entry-title a"
        )

        def match_word(qw, target):
            if qw in target:
                return True
            if qw.endswith('s') and qw[:-1] in target:
                return True
            return False

        movie_page_url = None
        for a in candidate_links:
            title_text = f"{a.get('title', '')} {a.get_text()}".lower()
            href = a.get("href", "")
            if not href or href == "#" or any(x in href for x in ["/category/", "/tag/", "/author/", "/page/"]):
                continue

            clean_target = re.sub(r"['’]", "", title_text).lower()

            if (clean_q in clean_target) or (
                query_words and all(match_word(w, clean_target) for w in query_words)
            ):
                movie_page_url = href
                break

        if not movie_page_url:
            return "N/A", "N/A", ""

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(movie_page_url, headers=headers) as resp:
                if resp.status != 200:
                    return "N/A", "N/A", ""
                movie_html = await resp.text()

        movie_soup = BeautifulSoup(movie_html, "html.parser")

        for tag in movie_soup(["header", "nav", "footer", "aside", "script", "style"]):
            tag.decompose()
        for widget in movie_soup.select(".sidebar, #sidebar, .widget, .related-posts, .comments"):
            widget.decompose()

        content = movie_soup.select_one(".entry-content, .post-content, article, .k-post-content")
        search_area = content if content else movie_soup

        for a_tag in search_area.find_all("a", href=True):
            href = a_tag["href"].strip()
            if "imdb.com/title/tt" in href:
                clean_match = re.search(r'https?://(?:www\.)?imdb\.com/title/(tt\d+)/?', href)
                if clean_match:
                    imdb_url = f"https://www.imdb.com/title/{clean_match.group(1)}/"
                    break

        for elem in search_area.find_all(["p", "div", "span", "strong", "b", "h4"]):
            text = elem.get_text(" ", strip=True)

            if genres == "N/A" and re.search(r'\b(?:Genre|Genres)\b', text, re.IGNORECASE):
                m = re.search(r'\b(?:Genre|Genres)\s*[:\-]\s*([^\n\r]+)', text, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip()
                    candidate = re.split(
                        r'\b(?:Release|IMDb|Rating|Language|Audio|Stars|Cast|Director|Quality|Size|Source|Format|Storyline)\b',
                        candidate, flags=re.IGNORECASE
                    )[0]
                    candidate = re.sub(r'["\'<>{}[\]\\]', '', candidate)
                    parts = re.split(r'[,|/•]', candidate)
                    cleaned = [
                        p.strip() for p in parts 
                        if p.strip() and 2 <= len(p.strip()) <= 30 and not any(
                            bad in p.lower() for bad in ["dropdown", "menu", "select", "category", "home", "search", "click", "download"]
                        )
                    ]
                    if cleaned:
                        genres = ", ".join(cleaned)

            if rating == "N/A" and re.search(r'\b(?:IMDb|IMDB|Rating)\b', text, re.IGNORECASE):
                r_match = re.search(
                    r'\b(?:IMDb|IMDB|iMDB|Rating|Ratings)\s*(?:Rating|Ratings)?\s*[:\-•]?\s*([0-9]+(?:\.[0-9]+)?|[xX]|N/?A)\s*(?:/\s*10)?',
                    text,
                    re.IGNORECASE
                )
                if r_match:
                    raw_val = r_match.group(1).strip()
                    if raw_val.lower() in ("x", "n/a", "na"):
                        rating = "x/10"
                    else:
                        try:
                            val = float(raw_val)
                            if 0.0 < val <= 10.0:
                                rating = f"{val:.1f}"
                        except ValueError:
                            rating = "x/10"

        if genres == "N/A":
            cat_links = search_area.select(".cat-links a, a[rel='category tag'], .entry-category a, .genres a")
            ignored_cats = {
                "uncategorized", "movies", "web series", "bollywood",
                "hollywood", "dual audio", "hindi dubbed", "tv shows",
                "720p", "480p", "1080p", "hevc", "south hindi", "series", "dropdown"
            }
            extracted_genres = [
                c.text.strip()
                for c in cat_links
                if c.text.strip() and c.text.strip().lower() not in ignored_cats and "<" not in c.text and ">" not in c.text
            ]
            if extracted_genres:
                genres = ", ".join(extracted_genres)

    except Exception as e:
        logger.error(f"Error scraping HDHub4u data: {e}")

    return genres, rating, imdb_url


def extract_season_episode(filename: str) -> Tuple[Optional[int], Optional[str]]:
    if m := BONUS_RANGE_REGEX.search(filename):
        return int(m.group(1)), f"Bonus {int(m.group(2))}-{int(m.group(3))}"

    if m := BONUS_REGEX.search(filename):
        return int(m.group(1)), f"Bonus {int(m.group(2))}"

    if m := RANGE_REGEX.search(filename):
        return int(m.group(1)), f"{int(m.group(2))}-{int(m.group(3))}"

    if m := SINGLE_REGEX.search(filename):
        return int(m.group(1)), str(int(m.group(2)))

    if m := NAMED_REGEX.search(filename):
        return int(m.group(1)), str(int(m.group(2)))

    if m := X_REGEX.search(filename):
        ep_val = int(m.group(2))
        if ep_val not in (264, 265):
            return int(m.group(1)), str(ep_val)

    if m := DAY_REGEX.search(filename):
        season = int(m.group(1)) if m.group(1) else 1
        return season, str(int(m.group(2)))

    if m := NO_S_REGEX.search(filename):
        return int(m.group(1)), str(int(m.group(2)))

    if m := EP_ONLY_RANGE.search(filename):
        return 1, f"{int(m.group(1))}-{int(m.group(2))}"

    if m := EP_ONLY_SINGLE.search(filename):
        ep_val = int(m.group(1))
        if ep_val not in (264, 265):
            return 1, str(ep_val)

    return None, None


def schedule_update(bot, base_name, delay=5):
    if handle := pending_updates.get(base_name):
        if not handle.cancelled():
            handle.cancel()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    async def wrapper():
        try:
            await update_movie_message(bot, base_name)
        finally:
            pending_updates.pop(base_name, None)

    pending_updates[base_name] = loop.call_later(
        delay,
        lambda: asyncio.create_task(wrapper())
    )


def extract_media_info(filename: str, caption: str):
    filename = normalize(clean_mentions_links(filename).title())
    caption_clean = clean_mentions_links(caption).lower() if caption else ""
    unified = f"{caption_clean} {filename.lower()}".strip()

    season = None
    episode = None
    year = None
    tag = "#MOVIE"

    processed_raw = filename
    base_raw = filename

    quality = (
        get_qualities(caption)
        or get_qualities(filename)
        or "N/A"
    )

    ott_platform = extract_ott_platform(
        f"{filename} {caption_clean}"
    )

    lang_keys = {
        k
        for k in CAPTION_LANGUAGES
        if re.search(rf"\b{re.escape(k)}\b", unified)
    }

    language = (
        ", ".join(
            sorted(
                {
                    CAPTION_LANGUAGES[k]
                    for k in lang_keys
                }
            )
        )
        if lang_keys
        else "N/A"
    )

    season, episode = extract_season_episode(filename)

    if season is not None:
        tag = "#SERIES"

        m = (
            BONUS_RANGE_REGEX.search(filename)
            or BONUS_REGEX.search(filename)
            or RANGE_REGEX.search(filename)
            or SINGLE_REGEX.search(filename)
            or NAMED_REGEX.search(filename)
            or X_REGEX.search(filename)
            or DAY_REGEX.search(filename)
            or NO_S_REGEX.search(filename)
            or EP_ONLY_RANGE.search(filename)
            or EP_ONLY_SINGLE.search(filename)
        )

        if m:
            match_str = m.group(0)
            start_idx = filename.lower().find(match_str.lower())
            end_idx = start_idx + len(match_str)

            processed_raw = filename[:end_idx]
            base_raw = filename[:start_idx]

            year_match = YEAR_PATTERN.search(
                filename.lower()[end_idx:]
            )

            if year_match:
                y = year_match.group(0)
                yi = filename.lower().find(y, end_idx)

                if yi != -1:
                    processed_raw = filename[:yi + 4]
                    base_raw += f" {y}"

    else:
        year_match = YEAR_PATTERN.search(unified)

        if year_match:
            year = year_match.group(0)
            year_idx = filename.lower().find(year.lower())

            if year_idx != -1:
                processed_raw = filename[:year_idx + 4]
                base_raw = processed_raw

        else:
            qual_match = SOURCE_PATTERN.search(unified) or RESOLUTION_PATTERN.search(unified)

            if qual_match:
                qual_str = qual_match.group(0)
                qual_idx = filename.lower().find(
                    qual_str.lower()
                )

                if qual_idx != -1:
                    processed_raw = filename[:qual_idx]
                    base_raw = processed_raw

    base_name = normalize(
        remove_ignored_words(
            normalize(base_raw)
        )
    )

    if year and year not in base_name:
        base_name += f" {year}"

    if base_name.endswith(")"):
        base_name = re.sub(
            r"\s+\(\d{4}\)$",
            "",
            base_name
        )

        if year:
            base_name += f" {year}"

    def _strip_season_episode_tokens(name: str) -> str:
        if not name:
            return name

        year_match = re.search(
            r"\(?\b(19|20)\d{2}\b\)?\s*$",
            name
        )

        year_part = ""

        if year_match:
            year_part = year_match.group(0)
            name = name[:year_match.start()].strip()

        patterns = [
            r"\bS\d{1,2}[\s._-]*(?:Bonus|Special)[\s._-]*E(?:p(?:isode)?)?0*\d{1,3}\b",
            r"\b(?:Bonus|Special)[\s._-]*Ep(?:isode)?\.?\s*\d{1,3}\b",
            r"\bS\d{1,2}E\d{1,3}\b",
            r"\bS\d{1,2}\b",
            r"\bE\d{1,3}\b",
            r"\b\d{1,2}x\d{1,3}\b",
            r"\bSeason\s*\d{1,2}\b",
            r"\bEp(?:isode)?\.?\s*\d{1,3}\b",
            r"\bEpisode\s*\d{1,3}\b",
            r"\bPart\s*\d{1,2}\b",
            r"\bDay\s*\d{1,3}\b",
            r"\bBonus\b",
            r"\bSpecial\b",
            r"\b[vV]\d+\b",
            r"\b(?:version|ver)\.?\s*\d+\b"
        ]

        for p in patterns:
            name = re.sub(p, " ", name, flags=re.IGNORECASE)

        name = re.sub(r"[_\.\-]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()

        if year_part:
            y = re.search(r"(19|20)\d{2}", year_part)
            if y:
                name = f"{name} {y.group(0)}"

        return name.strip()

    base_name = _strip_season_episode_tokens(base_name)
    base_name = re.sub(r'(\b(?:19|20)\d{2}\b)(?:\s+\1)+', r'\1', base_name).strip()

    if season is not None:
        base_name = f"{base_name} Season {season}"

    if not base_name:
        base_name = (
            normalize(
                remove_ignored_words(
                    normalize(processed_raw)
                )
            )
            or filename
        )

    return {
        "processed": normalize(processed_raw),
        "base_name": base_name,
        "tag": tag,
        "season": season,
        "episode": episode,
        "year": year,
        "quality": quality,
        "ott_platform": ott_platform,
        "language": language
    }


@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    media = next(
        (
            getattr(message, ft)
            for ft in ("document", "video", "audio")
            if getattr(message, ft, None)
        ),
        None
    )

    if not media:
        return

    duration_secs = getattr(media, "duration", None)

    if not duration_secs and message.video:
        duration_secs = message.video.duration

    if not duration_secs and message.audio:
        duration_secs = message.audio.duration

    file_runtime_mins = (
        round(duration_secs / 60)
        if duration_secs
        else None
    )

    media.file_type = next(
        ft
        for ft in ("document", "video", "audio")
        if getattr(message, ft, None)
    )

    media.caption = message.caption or ""

    success, info = await save_file(media)

    if not success:
        return

    try:
        if await db.movie_update_status(bot.me.id):
            await process_and_send_update(
                bot,
                media.file_name or message.caption or "Unknown",
                media.caption,
                file_runtime_mins
            )
    except Exception:
        logger.exception("Error processing media")


async def process_and_send_update(
    bot,
    filename,
    caption,
    file_runtime_mins=None
):
    try:
        media_info = extract_media_info(
            filename,
            caption
        )

        base_name = media_info["base_name"]
        processed = media_info["processed"]

        lock = locks[base_name]

        async with lock:
            await _process_with_lock(
                bot,
                filename,
                caption,
                media_info,
                base_name,
                processed,
                file_runtime_mins
            )

    except PyMongoError as e:
        logger.error(f"Database error in process_and_send_update: {e}")

    except Exception as e:
        logger.exception(f"Processing failed in process_and_send_update: {e}")


async def _process_with_lock(
    bot,
    filename,
    caption,
    media_info,
    base_name,
    processed,
    file_runtime_mins=None
):
    if not hasattr(db, "movie_updates"):
        db.movie_updates = db.db.movie_updates

    clean_title = get_clean_title(base_name)
    movie_doc = await db.movie_updates.find_one(
        {"_id": base_name}
    )
    if not movie_doc:
        movie_doc = await db.movie_updates.find_one({"clean_title": clean_title})
        if movie_doc:
            base_name = movie_doc["_id"]

    is_series = media_info["tag"] == "#SERIES"

    is_mismatched = False
    if movie_doc:
        stored_title = movie_doc.get("title", "")
        if stored_title and not is_good_title_match(base_name, stored_title):
            logger.warning(f"Title mismatch detected: '{stored_title}' for '{base_name}'. Re-fetching!")
            is_mismatched = True

    error_tmdb = False

    final_file_runtime = (
        f"{file_runtime_mins}"
        if file_runtime_mins
        else "N/A"
    )

    file_data = {
        "filename": filename,
        "processed": processed,
        "quality": media_info["quality"],
        "language": media_info["language"],
        "ott_platform": media_info["ott_platform"],
        "timestamp": datetime.now(),
        "tag": media_info["tag"],
        "season": media_info["season"],
        "episode": media_info["episode"],
        "runtime": final_file_runtime
    }

    if not movie_doc or is_mismatched:
        blogger_poster_url = await get_blogger_poster_url(base_name, media_info.get("year"))
        hdhub_genres, hdhub_rating, hdhub_imdb_url = await get_hdhub4u_data(base_name)

        tt_match = re.search(r'tt\d+', hdhub_imdb_url) if hdhub_imdb_url else None
        hdhub_imdb_id = tt_match.group(0) if tt_match else None

        imdb_details = await fetch_imdb_safely(
            base_name,
            is_series=is_series,
            year=media_info.get("year")
        ) or {}

        if not imdb_details or not is_good_title_match(base_name, imdb_details.get("title", "")):
            imdb_id = hdhub_imdb_id
            official_search_title = base_name
        else:
            official_search_title = imdb_details.get("title", base_name)
            imdb_id = hdhub_imdb_id or imdb_details.get("imdb_id")

        tmdb_query = imdb_id if (imdb_id and imdb_id.startswith("tt")) else official_search_title
        tmdb_details = await fetch_tmdb_safely(tmdb_query, base_name, is_series)

        if not tmdb_details or tmdb_details.get("error"):
            error_tmdb = True

        poster_url = ""
        is_backdrop = False

        if blogger_poster_url:
            poster_url = blogger_poster_url
            is_backdrop = True
        elif (
            LANDSCAPE_POSTER
            and TMDB_POSTER
            and tmdb_details.get("backdrop_url")
            and not error_tmdb
        ):
            poster_url = tmdb_details.get("backdrop_url")
            is_backdrop = True

        elif (
            tmdb_details.get("poster_url")
            and not error_tmdb
        ):
            poster_url = tmdb_details.get("poster_url")

        else:
            poster_url = (
                imdb_details.get("poster_url")
                or imdb_details.get("backdrop_url", "")
            )

        imdb_rate = imdb_details.get("rating")
        tmdb_rate = tmdb_details.get("rating")

        if hdhub_rating and hdhub_rating != "N/A":
            rating = hdhub_rating
        elif imdb_rate and str(imdb_rate).strip().upper() not in ("N/A", "NONE", "0", "0.0", "-", ""):
            rating = str(imdb_rate).strip()
        elif tmdb_rate and str(tmdb_rate).strip().upper() not in ("N/A", "NONE", "0", "0.0", "-", ""):
            rating = str(tmdb_rate).strip()
        else:
            rating = "x/10"

        # 👉 Strict HDHub4u IMDb URL assignment (No external API fallback for URL)
        imdb_url = hdhub_imdb_url if hdhub_imdb_url else ""

        imdb_r = imdb_details.get("runtime")
        tmdb_r = (
            tmdb_details.get("episode_run_time")
            if is_series and tmdb_details.get("episode_run_time")
            else tmdb_details.get("runtime")
        )

        if isinstance(imdb_r, (list, tuple)) and imdb_r:
            imdb_r = imdb_r[0]
        if isinstance(tmdb_r, (list, tuple)) and tmdb_r:
            tmdb_r = tmdb_r[0]

        if is_series:
            if tmdb_r and str(tmdb_r).strip().upper() not in ("N/A", "NONE", "0", ""):
                runtime = str(tmdb_r).strip()
            elif final_file_runtime != "N/A":
                runtime = final_file_runtime
            elif imdb_r and str(imdb_r).strip().upper() not in ("N/A", "NONE", "0", ""):
                runtime = str(imdb_r).strip()
            else:
                runtime = "N/A"
        else:
            if imdb_r and str(imdb_r).strip().upper() not in ("N/A", "NONE", "0", ""):
                runtime = str(imdb_r).strip()
            elif tmdb_r and str(tmdb_r).strip().upper() not in ("N/A", "NONE", "0", ""):
                runtime = str(tmdb_r).strip()
            else:
                runtime = final_file_runtime if final_file_runtime != "N/A" else "N/A"

        certificates = (
            tmdb_details.get("certificates")
            if tmdb_details.get("certificates")
            and tmdb_details.get("certificates") != "N/A"
            else imdb_details.get("certificates", "N/A")
        )

        genre_list = []
        if hdhub_genres and hdhub_genres != "N/A":
            raw_parts = re.split(r'[,|/•]', hdhub_genres)
            for p in raw_parts:
                clean_p = p.strip()
                if not clean_p or clean_p == "N/A" or any(bad in clean_p.lower() for bad in ["dropdown", "menu", "select", "category"]):
                    continue

                if "&" in clean_p:
                    for sub_p in clean_p.split("&"):
                        sub_clean = sub_p.strip().title()
                        if sub_clean and sub_clean not in genre_list:
                            genre_list.append(sub_clean)
                else:
                    formatted_p = clean_p.title()
                    if formatted_p not in genre_list:
                        genre_list.append(formatted_p)

        if not genre_list:
            raw_genres = tmdb_details.get("genres") or imdb_details.get("genres", "N/A")
            fallback_genres = []
            if isinstance(raw_genres, str) and raw_genres != "N/A":
                fallback_genres = [g.strip() for g in raw_genres.split(",") if g.strip() and g.strip() != "N/A"]
            elif isinstance(raw_genres, (list, tuple)):
                for g in raw_genres:
                    if isinstance(g, dict):
                        name = g.get("name") or g.get("genre")
                        if name:
                            fallback_genres.append(str(name).strip())
                    elif isinstance(g, str):
                        fallback_genres.append(g.strip())

            for g in fallback_genres:
                clean_g = g.strip().title()
                if clean_g and clean_g not in genre_list:
                    genre_list.append(clean_g)

        genres = ", ".join(genre_list) if genre_list else "N/A"

        movie_year = (
            media_info.get("year")
            or imdb_details.get("year")
            or tmdb_details.get("year")
        )

        if is_mismatched:
            update_data = {
                "title": official_search_title,
                "clean_title": clean_title,
                "poster_url": poster_url,
                "genres": genres,
                "rating": rating,
                "runtime": runtime,
                "certificates": certificates,
                "imdb_url": imdb_url,
                "year": movie_year,
                "tag": media_info["tag"],
                "ott_platform": media_info["ott_platform"],
                "error_tmdb": error_tmdb,
                "is_backdrop": is_backdrop
            }
            await db.movie_updates.update_one(
                {"_id": base_name},
                {
                    "$set": update_data,
                    "$push": {"files": file_data}
                }
            )
            schedule_update(bot, base_name)
            return

        new_doc = {
            "_id": base_name,
            "clean_title": clean_title,
            "title": official_search_title,
            "files": [file_data],
            "poster_url": poster_url,
            "genres": genres,
            "rating": rating,
            "runtime": runtime,
            "certificates": certificates,
            "imdb_url": imdb_url,
            "year": movie_year,
            "tag": media_info["tag"],
            "ott_platform": media_info["ott_platform"],
            "message_id": None,
            "is_photo": False,
            "error_tmdb": error_tmdb,
            "is_backdrop": is_backdrop
        }

        try:
            await db.movie_updates.insert_one(new_doc)
        except DuplicateKeyError:
            movie_doc = await db.movie_updates.find_one({"_id": base_name})
            if not movie_doc:
                return

            if any(f.get("filename") == filename for f in movie_doc.get("files", [])):
                return

            await db.movie_updates.update_one(
                {"_id": base_name},
                {"$push": {"files": file_data}}
            )
            schedule_update(bot, base_name)
            return

        await send_movie_update(bot, base_name)

    else:
        existing_files = movie_doc.get("files", [])
        if any(f.get("filename") == filename for f in existing_files):
            logger.info(f"Duplicate file skipped: {filename}")
            return

        update_fields = {"$push": {"files": file_data}}

        current_db_runtime = movie_doc.get("runtime")
        if (not current_db_runtime or str(current_db_runtime).strip().upper() in ("N/A", "NONE", "0", "")) and final_file_runtime != "N/A":
            update_fields["$set"] = {"runtime": final_file_runtime}

        current_db_rating = movie_doc.get("rating")
        if not current_db_rating or str(current_db_rating).strip().upper() in ("N/A", "NONE", "0", "0.0", "-", "X/10"):
            _, hdhub_rating, _ = await get_hdhub4u_data(base_name)
            if hdhub_rating and hdhub_rating != "N/A" and hdhub_rating != "x/10":
                update_fields.setdefault("$set", {})["rating"] = hdhub_rating

        await db.movie_updates.update_one(
            {"_id": base_name},
            update_fields
        )

        schedule_update(bot, base_name)


async def send_movie_update(bot, base_name):
    if base_name in sending_updates:
        logger.warning(f"Duplicate send prevented: {base_name}")
        return None

    sending_updates.add(base_name)

    try:
        max_retries = 3

        for attempt in range(max_retries):
            try:
                movie_doc = await db.movie_updates.find_one({"_id": base_name})
                if not movie_doc:
                    return None

                existing_message_id = movie_doc.get("message_id")
                if existing_message_id:
                    logger.info(f"Movie already posted, updating instead: {base_name}")
                    await update_movie_message(bot, base_name)
                    return None

                text = generate_movie_message(movie_doc, base_name)

                all_tags = {
                    f.get("tag")
                    for f in movie_doc.get("files", [])
                    if f.get("tag")
                }

                primary_tag = "#SERIES" if "#SERIES" in all_tags else "#MOVIE"
                btn_style = enums.ButtonStyle.SUCCESS if primary_tag == "#SERIES" else enums.ButtonStyle.DANGER

                # 👉 Button query format: Lanterns-S01 (automatically converted from base_name)
                match = re.search(r'(.+?)\s+Season\s+(\d+)', base_name, re.IGNORECASE)
                if match:
                    series_name = match.group(1).strip()
                    season_num = int(match.group(2))
                    button_query = f"{series_name}-S{season_num:02d}"
                else:
                    button_query = base_name

                buttons = InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "ɢᴇᴛ ғɪʟᴇs",
                            url=(
                                f"https://t.me/{temp.U_NAME}"
                                f"?start=getfile-"
                                f"{button_query.replace(' ', '-')}"
                            ),
                            style=btn_style
                        )
                    ]]
                )

                size = (
                    (2560, 1440)
                    if (
                        LANDSCAPE_POSTER
                        and TMDB_POSTER
                        and movie_doc.get("is_backdrop")
                        and not movie_doc.get("error_tmdb")
                    )
                    else (853, 1280)
                )

                if movie_doc.get("poster_url") and not LINK_PREVIEW:
                    resized_poster = await fetch_image(movie_doc["poster_url"], size)
                    if resized_poster:
                        msg = await bot.send_photo(
                            chat_id=MOVIE_UPDATE_CHANNEL,
                            photo=resized_poster,
                            caption=text,
                            reply_markup=buttons,
                            parse_mode=enums.ParseMode.HTML
                        )
                        is_photo = True
                    else:
                        msg = await bot.send_message(
                            chat_id=MOVIE_UPDATE_CHANNEL,
                            text=text,
                            reply_markup=buttons,
                            parse_mode=enums.ParseMode.HTML
                        )
                        is_photo = False
                else:
                    send_params = {
                        "chat_id": MOVIE_UPDATE_CHANNEL,
                        "text": text,
                        "reply_markup": buttons,
                        "parse_mode": enums.ParseMode.HTML
                    }
                    if movie_doc.get("poster_url") and LINK_PREVIEW:
                        send_params["invert_media"] = ABOVE_PREVIEW

                    msg = await bot.send_message(**send_params)
                    is_photo = False

                await db.movie_updates.update_one(
                    {"_id": base_name, "message_id": None},
                    {"$set": {"message_id": msg.id, "is_photo": is_photo}}
                )

                logger.info(f"Movie update posted successfully: {base_name} -> {msg.id}")
                return msg

            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
            except Exception as e:
                logger.error(f"Failed to send movie update: {e}")
                break

        return None

    finally:
        sending_updates.discard(base_name)


async def update_movie_message(bot, base_name):
    try:
        movie_doc = await db.movie_updates.find_one({"_id": base_name})
        if not movie_doc:
            return

        text = generate_movie_message(movie_doc, base_name)

        all_tags = {
            f.get("tag")
            for f in movie_doc.get("files", [])
            if f.get("tag")
        }

        primary_tag = "#SERIES" if "#SERIES" in all_tags else "#MOVIE"
        btn_style = enums.ButtonStyle.SUCCESS if primary_tag == "#SERIES" else enums.ButtonStyle.DANGER

        # 👉 Button query format yahan bhi: Lanterns-S01
        match = re.search(r'(.+?)\s+Season\s+(\d+)', base_name, re.IGNORECASE)
        if match:
            series_name = match.group(1).strip()
            season_num = int(match.group(2))
            button_query = f"{series_name}-S{season_num:02d}"
        else:
            button_query = base_name

        buttons = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(
                    "ɢᴇᴛ ғɪʟᴇs",
                    url=(
                        f"https://t.me/{temp.U_NAME}"
                        f"?start=getfile-"
                        f"{button_query.replace(' ', '-')}"
                    ),
                    style=btn_style
                )
            ]]
        )

        message_id = movie_doc.get("message_id")
        is_photo = movie_doc.get("is_photo", False)

        if not message_id:
            await send_movie_update(bot, base_name)
            return

        try:
            if is_photo:
                await bot.edit_message_caption(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    message_id=message_id,
                    caption=text,
                    reply_markup=buttons,
                    parse_mode=enums.ParseMode.HTML
                )
            else:
                await bot.edit_message_text(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    message_id=message_id,
                    text=text,
                    reply_markup=buttons,
                    parse_mode=enums.ParseMode.HTML,
                    invert_media=ABOVE_PREVIEW,
                    disable_web_page_preview=not LINK_PREVIEW
                )

            logger.info(f"Movie update edited successfully: {base_name}")

        except MessageNotModified:
            logger.info(f"Movie message unchanged: {base_name}")

        except MessageIdInvalid:
            logger.warning(f"Invalid movie message ID: {base_name}")
            await db.movie_updates.update_one(
                {"_id": base_name},
                {"$set": {"message_id": None}}
            )
            await send_movie_update(bot, base_name)

        except Exception as e:
            logger.error(f"Error updating movie message: {e}")

    except Exception as e:
            logger.error(f"Failed to update movie message for {base_name}: {e}")


def generate_movie_message(movie_doc, base_name):
    all_raw_qualities = []
    all_languages = set()
    all_ott_platforms = set()
    all_tags = set()
    episodes_by_season = defaultdict(set)

    for file in movie_doc.get("files", []):
        if file.get("quality") and file.get("quality") != "N/A":
            all_raw_qualities.append(file.get("quality"))

        lang_val = file.get("language")
        if lang_val and lang_val != "N/A":
            for lang in lang_val.split(","):
                clean_l = lang.strip()
                if clean_l and clean_l != "N/A":
                    norm_l = CAPTION_LANGUAGES.get(clean_l.lower(), clean_l.title())
                    all_languages.add(norm_l)

        ott_val = file.get("ott_platform")
        if ott_val and ott_val != "N/A":
            for plat in ott_val.split("|"):
                clean_p = plat.strip()
                if clean_p and clean_p != "N/A":
                    norm_p = OTT_PLATFORMS.get(clean_p.lower(), clean_p)
                    all_ott_platforms.add(norm_p)

        if file.get("tag"):
            all_tags.add(file.get("tag"))

        if file.get("season") is not None and file.get("episode"):
            season = file.get("season")
            episode = str(file.get("episode"))
            episodes_by_season[season].add(episode)

    if "Disney+ Hotstar" in all_ott_platforms and "Disney+" in all_ott_platforms:
        all_ott_platforms.remove("Disney+")
    if "JioHotstar" in all_ott_platforms:
        all_ott_platforms.discard("Disney+ Hotstar")
        all_ott_platforms.discard("Disney+")
    if "HBO Max" in all_ott_platforms and "Max" in all_ott_platforms:
        all_ott_platforms.remove("Max")

    primary_tag = "#SERIES" if "#SERIES" in all_tags else "#MOVIE"
    is_series = (primary_tag == "#SERIES")

    epi_block = ""

    if episodes_by_season:
        episode_lines = []

        for season, episodes in sorted(
            episodes_by_season.items(),
            key=lambda x: int(x[0])
        ):
            regular_eps = set()
            bonus_eps = set()

            for ep in episodes:
                ep_str = str(ep).strip()
                if not ep_str or ep_str.lower() in ("bonus", "special", "episodes", "episode"):
                    continue

                if ep_str.lower().startswith("bonus"):
                    val = re.sub(r'(?i)bonus\s*', '', ep_str).strip()
                    if "-" in val:
                        try:
                            p1, p2 = val.split("-")
                            bonus_eps.update(range(int(p1), int(p2) + 1))
                        except ValueError:
                            pass
                    elif val.isdigit():
                        bonus_eps.add(int(val))
                elif "-" in ep_str:
                    try:
                        p1, p2 = ep_str.split("-")
                        regular_eps.update(range(int(p1), int(p2) + 1))
                    except ValueError:
                        pass
                elif ep_str.isdigit():
                    regular_eps.add(int(ep_str))

            def collapse_range(num_set):
                sorted_nums = sorted(num_set)
                if not sorted_nums:
                    return []
                collapsed = []
                start = end = sorted_nums[0]
                for num in sorted_nums[1:]:
                    if num == end + 1:
                        end = num
                    else:
                        collapsed.append(str(start) if start == end else f"{start}-{end}")
                        start = end = num
                collapsed.append(str(start) if start == end else f"{start}-{end}")
                return collapsed

            line_parts = []
            reg_list = collapse_range(regular_eps)
            if reg_list:
                line_parts.append(", ".join(reg_list))

            bon_list = collapse_range(bonus_eps)
            if bon_list:
                line_parts.append(f"Bonus {', '.join(bon_list)}")

            if line_parts:
                episode_lines.append(f"S{int(season)}: {', '.join(line_parts)}")

        epi_str = "\n".join(episode_lines)
        if epi_str:
            epi_block = f"\n📺 ᴇᴘɪsᴏᴅᴇs : <b>{epi_str}</b>"

    genres = movie_doc.get("genres", "N/A")
    quality_str = format_movie_qualities(all_raw_qualities)
    language_str = ", ".join(sorted(all_languages)) if all_languages else "N/A"
    ott_str = " | ".join(sorted(all_ott_platforms)) if all_ott_platforms else "N/A"

    raw_rating = str(movie_doc.get("rating", "x/10")).strip()
    imdb_url = movie_doc.get("imdb_url", "")

    if raw_rating.lower() in ("x/10", "x", "n/a", "-", "none", "", "0", "0.0", "null"):
        rating_display = "<small>x/10</small>"
    else:
        clean_rating = raw_rating.replace("/10", "").strip()
        rating_display = f"<small>{clean_rating}/10</small>"

    if imdb_url:
        rating_text = f'<a href="{imdb_url}">{rating_display}</a>'
    else:
        rating_text = rating_display

    raw_runtime = movie_doc.get("runtime", "N/A")
    runtime = format_runtime(raw_runtime, is_series=is_series)
    certificates = movie_doc.get("certificates", "N/A")

    stored_title = movie_doc.get("title", base_name)
    
    # 👉 Top Title Clean: Upar se 'Season X' ya 'S01' ko completely hata diya hai taaki sirf clean name aaye
    display_title = re.sub(r'\s+Season\s*\d+', '', stored_title, flags=re.IGNORECASE).strip()
    display_title = re.sub(r'\s+S\d+', '', display_title, flags=re.IGNORECASE).strip()

    movie_year = movie_doc.get("year")
    
    if movie_year and str(movie_year) not in str(display_title) and primary_tag != "#SERIES":
        filename_display = f"{display_title} {movie_year}"
    else:
        filename_display = display_title

    raw_text = script.MOVIE_UPDATE_NOTIFY_TXT.format(
        poster_url=movie_doc.get("poster_url", ""),
        imdb_url=imdb_url,
        filename=filename_display,
        tag=primary_tag,
        genres=genres,
        ott=ott_str,
        runtime=runtime,
        certificates=certificates,
        quality=quality_str,
        language=language_str,
        episodes=epi_block,
        rating=rating_text,
        search_link=temp.B_LINK
    )

    return "\n".join(
        line.strip()
        for line in raw_text.splitlines()
    )
