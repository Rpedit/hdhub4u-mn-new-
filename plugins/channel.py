import re
import logging
import asyncio
from datetime import datetime
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

# Precomputed sets for faster lookups
IGNORE_WORDS = {
    "rarbg", "dub", "sub", "sample", "mkv", "aac", "combined",
    "action", "adventure", "animation", "biography", "comedy", "crime", 
    "documentary", "drama", "fantasy", "film-noir", "history", 
    "horror", "music", "musical", "mystery", "romance", "sci-fi", "sport", 
    "thriller", "war", "western", "hdcam", "hdtc", "camrip", "ts", "tc", 
    "telesync", "dvdscr", "dvdrip", "predvd", "webrip", "web-dl", "tvrip", 
    "hdtv", "web dl", "webdl", "bluray", "brrip", "bdrip", "360p", "480p", 
    "720p", "1080p", "2160p", "4k", "1440p", "540p", "240p", "140p", "hevc", 
    "hdrip", "hin", "hindi", "tam", "tamil", "kan", "kannada", "tel", "telugu", 
    "mal", "malayalam", "eng", "english", "pun", "punjabi", "ben", "bengali", 
    "mar", "marathi", "guj", "gujarati", "urd", "urdu", "kor", "korean", "jpn", 
    "japanese", "nf", "netflix", "sonyliv", "sony", "sliv", "amzn", "prime", 
    "primevideo", "hotstar", "zee5", "jio", "jhs", "aha", "hbo", "paramount", 
    "apple", "hoichoi", "sunnxt", "viki"
}|BAD_WORDS

# Constants
CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi", "tam": "Tamil", "tamil": "Tamil",
    "kan": "Kannada", "kannada": "Kannada", "tel": "Telugu", "telugu": "Telugu",
    "mal": "Malayalam", "malayalam": "Malayalam", "eng": "English", "english": "English",
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix", "sonyliv": "SonyLiv", "amzn": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "zee5": "Zee5", "jio": "JioHotstar", "aha": "Aha",
}

STANDARD_GENRES = {
    'Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary',
    'Drama', 'Family', 'Fantasy', 'Film-Noir', 'History', 'Horror', 'Music',
    'Musical', 'Mystery', 'Romance', 'Sci-Fi', 'Sport', 'Thriller', 'War', 'Western'
}

# --- REGEX PATTERNS ---
CLEAN_PATTERN = re.compile(r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+')
NORMALIZE_PATTERN = re.compile(r"[._]+|[()\[\]{}:;'–!,.?_]")
QUALITY_PATTERN = re.compile(r"\b(?:HDCam|HDTC|CamRip|TS|TC|DVDScr|DVDRip|WEBRip|WEB-DL|BluRay|BRRip|BDRip|4k|1080p|720p|480p|HEVC)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")
RANGE_REGEX = re.compile(r'\bS(\d{1,2})[^\w]*E(\d{1,2})\s*(?:to|-)\s*E?(\d{1,2})', re.IGNORECASE)
SINGLE_REGEX = re.compile(r'\bS(\d{1,2})[^\w]*E(\d{1,3})', re.IGNORECASE)

MEDIA_FILTER = filters.document | filters.video | filters.audio
locks = defaultdict(asyncio.Lock)
pending_updates = {}

# --- HELPER FUNCTIONS ---
def clean_mentions_links(text): return CLEAN_PATTERN.sub("", text or "").strip()
def normalize(s): return re.sub(r"\s+", " ", NORMALIZE_PATTERN.sub(" ", s)).strip()
def remove_ignored_words(text):
    words = {w.lower() for w in IGNORE_WORDS}
    return " ".join(w for w in text.split() if w.lower() not in words)

def extract_season_episode(filename):
    if m := RANGE_REGEX.search(filename): return int(m.group(1)), f"{int(m.group(2))}-{int(m.group(3))}"
    if m := SINGLE_REGEX.search(filename): return int(m.group(1)), m.group(2)
    return None, None

def extract_media_info(filename, caption):
    filename = normalize(clean_mentions_links(filename).title())
    caption_clean = clean_mentions_links(caption).lower() if caption else ""
    unified = f"{caption_clean} {filename.lower()}".strip()

    season, episode = extract_season_episode(filename)
    tag = "#SERIES" if season else "#MOVIE"
    
    # Base name cleaning
    base_raw = filename
    year_match = YEAR_PATTERN.search(unified)
    year = year_match.group(0) if year_match else None
    
    base_name = normalize(remove_ignored_words(base_raw))
    if year and year not in base_name: base_name += f" {year}"
    
    return {
        "base_name": base_name, "tag": tag, "season": season, "episode": episode,
        "year": year, "quality": QUALITY_PATTERN.findall(unified),
        "ott": [p for k, p in OTT_PLATFORMS.items() if k in unified],
        "lang": [v for k, v in CAPTION_LANGUAGES.items() if k in unified]
    }

# --- HANDLERS ---
@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    media = getattr(message, message.media.value)
    if not media: return
    success, _ = await save_file(media)
    if success and await db.movie_update_status(bot.me.id):
        await process_and_send_update(bot, media.file_name, message.caption or "")

async def process_and_send_update(bot, filename, caption):
    info = extract_media_info(filename, caption)
    base_name = info["base_name"]
    async with locks[base_name]:
        await _process_with_lock(bot, filename, info, base_name)

async def _process_with_lock(bot, filename, info, base_name):
    if not hasattr(db, 'movie_updates'): db.movie_updates = db.db.movie_updates
    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    
    file_data = {
        "filename": filename, "quality": ", ".join(set(info["quality"])),
        "language": ", ".join(set(info["lang"])), "ott_platform": " | ".join(set(info["ott"])),
        "tag": info["tag"], "season": info["season"], "episode": info["episode"]
    }

    if not movie_doc:
        details = await get_movie_detailsx(base_name)
        if not details or details.get("error"):
            details = await get_movie_details(base_name) or {}

        # FIX: Ensure IMDb URL is always used
        imdb_id = details.get("imdb_id")
        imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else details.get("url", "")

        movie_doc = {
            "_id": base_name, "files": [file_data],
            "poster_url": details.get("backdrop_url") if LANDSCAPE_POSTER and details.get("backdrop_url") else details.get("poster_url"),
            "genres": details.get("genres", ""), "rating": details.get("rating", "6.5"),
            "imdb_url": imdb_url, "message_id": None, "is_photo": False
        }
        await db.movie_updates.insert_one(movie_doc)
        await send_movie_update(bot, base_name)
    else:
        if any(f["filename"] == filename for f in movie_doc["files"]): return
        await db.movie_updates.update_one({"_id": base_name}, {"$push": {"files": file_data}})
        await schedule_update_call(bot, base_name)

async def schedule_update_call(bot, base_name):
    await asyncio.sleep(5)
    await update_movie_message(bot, base_name)

async def send_movie_update(bot, base_name):
    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    if not movie_doc: return
    
    text = generate_movie_message(movie_doc, base_name)
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton('ɢᴇᴛ ғɪʟᴇs', url=f"https://t.me/{temp.U_NAME}?start=getfile-{base_name.replace(' ', '-')}")]])
    
    poster = str(movie_doc.get("poster_url", "")).strip()
    try:
        if poster and not LINK_PREVIEW:
            img = await fetch_image(poster)
            msg = await bot.send_photo(MOVIE_UPDATE_CHANNEL, img, caption=text, reply_markup=buttons)
            is_photo = True
        else:
            msg = await bot.send_message(MOVIE_UPDATE_CHANNEL, text, reply_markup=buttons, disable_web_page_preview=not LINK_PREVIEW)
            is_photo = False
        await db.movie_updates.update_one({"_id": base_name}, {"$set": {"message_id": msg.id, "is_photo": is_photo}})
    except Exception as e: logger.error(f"Send Error: {e}")

async def update_movie_message(bot, base_name):
    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    if not movie_doc or not movie_doc.get("message_id"): return
    text = generate_movie_message(movie_doc, base_name)
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton('ɢᴇᴛ ғɪʟᴇs', url=f"https://t.me/{temp.U_NAME}?start=getfile-{base_name.replace(' ', '-')}")]])
    try:
        if movie_doc["is_photo"]:
            await bot.edit_message_caption(MOVIE_UPDATE_CHANNEL, movie_doc["message_id"], caption=text, reply_markup=buttons)
        else:
            await bot.edit_message_text(MOVIE_UPDATE_CHANNEL, movie_doc["message_id"], text=text, reply_markup=buttons)
    except Exception: pass

def generate_movie_message(movie_doc, base_name):
    qualities, languages, otts, tags = set(), set(), set(), set()
    episodes = defaultdict(set)
    for f in movie_doc["files"]:
        if f.get("quality"): qualities.update(q.strip() for q in f["quality"].split(","))
        if f.get("language"): languages.update(l.strip() for l in f["language"].split(","))
        if f.get("ott_platform"): otts.update(o.strip() for o in f["ott_platform"].split("|"))
        tags.add(f["tag"])
        if f.get("season"): episodes[f["season"]].add(f["episode"])

    epi_str = ""
    if episodes:
        lines = [f"S{s}: {', '.join(sorted(list(eps)))}" for s, eps in sorted(episodes.items())]
        epi_str = f"📺 ᴇᴘɪsᴏᴅᴇs : <b>" + "\n".join(lines) + "</b>"

    # IMDB LINK FIX: Rating converts to clickable IMDb URL
    raw_rating = str(movie_doc.get("rating", "6.5")).strip()
    imdb_url = movie_doc.get("imdb_url") or "https://www.imdb.com"
    rating_display = f'<a href="{imdb_url}">{raw_rating}</a>'

    # N/A & Empty line removal
    def get_val(val, fallback=""):
        v = str(val).strip()
        return v if v and v.lower() != "n/a" else fallback

    msg = script.MOVIE_UPDATE_NOTIFY_TXT.format(
        poster_url=get_val(movie_doc.get("poster_url")),
        imdb_url=imdb_url,
        filename=base_name,
        tag="#SERIES" if "#SERIES" in tags else "#MOVIE",
        genres=get_val(movie_doc.get("genres"), "Drama, Action"),
        ott=", ".join(otts) if otts else "Amazon Prime",
        quality=", ".join(qualities) if qualities else "1080p, 720p",
        language=", ".join(languages) if languages else "Hindi, English",
        episodes=epi_str,
        rating=rating_display,
        search_link=temp.B_LINK
    )
    # Remove extra spaces and empty lines
    return "\n".join([line for line in msg.splitlines() if line.strip()])
