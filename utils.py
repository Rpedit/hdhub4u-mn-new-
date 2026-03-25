import re
import os
import logging
from info import *
from imdb import Cinemagoer 
import asyncio
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid, ChatAdminRequired, MessageNotModified
from pyrogram import enums
from typing import Union, List
from Script import script
from database.users_chats_db import db
from bs4 import BeautifulSoup
import requests
from shortzy import Shortzy

# FIX: Imdbposter se function import check karein
from plugins.Dreamxfutures.Imdbposter import get_movie_detailsx

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

imdb = Cinemagoer() 
BANNED = {}
SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)

class temp(object):   
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT = int(os.environ.get("SKIP", 2))
    CANCEL = False
    B_USERS_CANCEL = False
    B_GROUPS_CANCEL = False 
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    B_LINK = None
    SETTINGS = {}
    GETALL = {}
    SHORT = {}
    IMDB_CAP = {}
    VERIFICATIONS = {}
    TEMP_INVITE_LINKS = {}

# FIX: listx_to_str ka issue solve karne ke liye hum isi naam ka function bana dete hain
# jo list_to_str ko call karega, taaki Imdbposter crash na ho.
def list_to_str(k):
    if not k or k == "N/A":
        return "N/A"
    if isinstance(k, str):
        return k
    if len(k) == 1:
        return str(k[0])
    if MAX_LIST_ELM:
        k = k[:int(MAX_LIST_ELM)]
    return ', '.join(f'{elem}' for elem in k)

# Alias for compatibility with your other files
def listx_to_str(k):
    return list_to_str(k)

async def is_req_subscribed(bot, user_id, rqfsub_channels):
    btn = []
    for ch_id in rqfsub_channels:
        if await db.has_joined_channel(user_id, ch_id):
            continue
        try:
            member = await bot.get_chat_member(ch_id, user_id)
            if member.status != enums.ChatMemberStatus.BANNED:
                await db.add_join_req(user_id, ch_id)
                continue
        except UserNotParticipant:
            pass
        except Exception as e:
            logger.error(f"Error checking membership in {ch_id}: {e}")

        try:
            chat = await bot.get_chat(ch_id)
            invite = await bot.create_chat_invite_link(ch_id, creates_join_request=True)
            btn.append([InlineKeyboardButton(f"⛔️ Join {chat.title}", url=invite.invite_link)])
        except Exception as e:
            logger.warning(f"Invite link error for {ch_id}: {e}")
            
    return btn

async def is_subscribed(bot, user_id, fsub_channels):
    btn = []
    async def check_channel(channel_id):
        try:
            await bot.get_chat_member(channel_id, user_id)
        except UserNotParticipant:
            try:
                chat = await bot.get_chat(int(channel_id))
                invite_link = await bot.create_chat_invite_link(channel_id)
                return InlineKeyboardButton(f"📢 Join {chat.title}", url=invite_link.invite_link)
            except Exception as e:
                logger.warning(f"Failed to create invite for {channel_id}: {e}")
        except Exception as e:
            logger.exception(f"is_subscribed error for {channel_id}: {e}")
        return None

    tasks = [check_channel(channel_id) for channel_id in fsub_channels]
    results = await asyncio.gather(*tasks)
    for button in results:
        if button:
            btn.append([button])
    return btn

async def users_broadcast(user_id, message, is_pin):
    try:
        m = await message.copy(chat_id=user_id)
        if is_pin:
            await m.pin(both_sides=True)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await users_broadcast(user_id, message, is_pin)
    except Exception:
        await db.delete_user(int(user_id))
        return False, "Error"

async def get_poster(query, bulk=False, id=False, file=None):
    if not id:
        query = (query.strip()).lower()
        title = query
        year = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
        if year:
            year = list_to_str(year[:1])
            title = (query.replace(year, "")).strip()
        elif file is not None:
            year = re.findall(r'[1-2]\d{3}', file, re.IGNORECASE)
            if year:
                year = list_to_str(year[:1]) 
        else:
            year = None
        
        movieid = await asyncio.to_thread(imdb.search_movie, title.lower())
        if not movieid:
            return None
        if year:
            filtered = list(filter(lambda k: str(k.get('year')) == str(year), movieid))
            if not filtered:
                filtered = movieid
        else:
            filtered = movieid
        movieid = list(filter(lambda k: k.get('kind') in ['movie', 'tv series'], filtered))
        if not movieid:
            movieid = filtered
        if bulk:
            return movieid
        movieid = movieid[0].movieID
    else:
        movieid = query

    movie = await asyncio.to_thread(imdb.get_movie, movieid)
    imdb.update(movie, info=['main', 'vote details'])
    
    date = movie.get("original air date") or movie.get("year") or "N/A"
    
    plot = ""
    if not LONG_IMDB_DESCRIPTION:
        plot_list = movie.get('plot')
        plot = plot_list[0] if plot_list and len(plot_list) > 0 else ""
    else:
        plot = movie.get('plot outline') or ""
    
    if plot and len(plot) > 800:
        plot = plot[0:800] + "..."

    return {
        'title': movie.get('title'),
        'votes': movie.get('votes'),
        "aka": list_to_str(movie.get("akas")),
        "seasons": movie.get("number of seasons"),
        "box_office": movie.get('box office'),
        "imdb_id": f"tt{movie.get('imdbID')}",
        "cast": list_to_str(movie.get("cast")),
        "runtime": list_to_str(movie.get("runtimes")),
        "languages": list_to_str(movie.get("languages")),
        "director": list_to_str(movie.get("director")),
        'year': movie.get('year'),
        'genres': list_to_str(movie.get("genres")),
        'poster': movie.get('full-size cover url'),
        'plot': plot,
        'rating': str(movie.get("rating")),
        'url': f'https://www.imdb.com/title/tt{movieid}'
    }

async def get_posterx(query, bulk=False, id=False, file=None):
    details = await get_movie_detailsx(query, id=id, file=file)
    if not details or details.get("error"):
        return None
    
    # Mapping and formatting
    return {
        'title': details.get('title'),
        'votes': details.get('votes'),
        "aka": details.get("aka", "N/A"),
        "seasons": details.get('seasons'),
        "box_office": details.get('box_office'),
        "imdb_id": details.get('imdb_id'),
        "cast": list_to_str(details.get("cast")),
        "runtime": list_to_str(details.get("runtime")),
        "languages": list_to_str(details.get("languages")),
        "director": list_to_str(details.get("director")),
        'year': details.get('year'),
        'genres': list_to_str(details.get("genres")),
        'poster': details.get('poster_url'),
        'backdrop': details.get('backdrop_url'),
        'plot': details.get('plot', ""),
        'rating': str(details.get("rating", "N/A")),
        'url': details.get('tmdb_url') or details.get('url')
    }

def clean_filename(file_name):
    prefixes = ('[', '@', 'www.')
    unwanted = {word.lower() for word in BAD_WORDS}
    file_name = ' '.join(
        word for word in file_name.split()
        if not (word.startswith(prefixes) or word.lower() in unwanted)
    )
    return file_name

def get_size(size):
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])

async def get_cap(settings, remaining_seconds, files, query, total_results, search, offset=0):
    try:
        if settings["imdb"]:
            # Check cached IMDB Cap
            cap = temp.IMDB_CAP.get(query.from_user.id)
            if not cap:
                imdb_data = await get_posterx(search, file=(files[0]).file_name) if TMDB_ON_SEARCH else await get_poster(search, file=(files[0]).file_name)
                if imdb_data:
                    TEMPLATE = script.IMDB_TEMPLATE_TXT
                    cap = TEMPLATE.format(
                        query=search, **imdb_data, **locals()
                    )
                else:
                    cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n🧱 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code></b>"
            
            cap += "\n\n<u>Your Requested Files Are Here</u>\n\n"
            for idx, file in enumerate(files, start=offset + 1):
                cap += f"<b>{idx}. <a href='https://telegram.me/{temp.U_NAME}?start=file_{query.message.chat.id}_{file.file_id}'>[{get_size(file.file_size)}] {clean_filename(file.file_name)}</a></b>\n\n"
            return cap
        else:
            cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n🧱 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds}s</code></b>\n\n<u>Your Requested Files Are Here</u>\n\n"
            for idx, file in enumerate(files, start=offset + 1):
                cap += f"<b>{idx}. <a href='https://telegram.me/{temp.U_NAME}?start=file_{query.message.chat.id}_{file.file_id}'>[{get_size(file.file_size)}] {clean_filename(file.file_name)}</a></b>\n\n"
            return cap
    except Exception as e:
        logger.error(f"Error in get_cap: {e}")
        return f"<b>🏷 ᴛɪᴛʟᴇ : {search}</b>"

# ... Baki functions (get_settings, save_group_settings etc) same rahengi ...
