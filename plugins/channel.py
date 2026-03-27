async def _process_with_lock(bot, filename, caption, media_info, base_name, processed):
    if not hasattr(db, 'movie_updates'):
        db.movie_updates = db.db.movie_updates

    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    error_tmdb = False
    
    file_data = {
        "filename": filename,
        "processed": processed,
        "quality": media_info["quality"],
        "language": media_info["language"],
        "ott_platform": media_info["ott_platform"],
        "timestamp": datetime.now(),
        "tag": media_info["tag"],
        "season": media_info["season"],
        "episode": media_info["episode"]
    }

    if not movie_doc:
        # --- DATA FETCHING LOGIC START ---
        details = {}
        if TMDB_POSTER:
            try:
                # Pehle TMDB details lo
                details = await get_movie_detailsx(base_name)
                # Check karo agar Poster ya Genres missing hain
                if not details or details.get("genres") == "N/A" or not details.get("poster_url"):
                    error_tmdb = True
                    logger.info(f"TMDB incomplete for {base_name}, fetching from IMDb...")
                    imdb_details = await get_movie_details(base_name)
                    if imdb_details:
                        # Dono ko merge karo (Rating TMDB ki, baaki IMDb ka)
                        imdb_details['rating'] = details.get('rating') if details and details.get('rating') != "N/A" else imdb_details.get('rating')
                        details = imdb_details
            except Exception as e:
                error_tmdb = True
                logger.error(f"TMDB Failed: {e}")
                details = await get_movie_details(base_name) or {}
        else:
            details = await get_movie_details(base_name) or {}

        # Genre filtering (Sirf standard genres rakho)
        raw_genres = details.get("genres", "N/A")
        if isinstance(raw_genres, str) and raw_genres != "N/A":
            genre_list = [g.strip() for g in raw_genres.split(",")]
            genres = ", ".join(g for g in genre_list if g in STANDARD_GENRES) or "N/A"
        else:
            genres = raw_genres if raw_genres else "N/A"

        # Poster Selection
        final_poster = details.get("poster_url")
        if LANDSCAPE_POSTER and TMDB_POSTER and details.get("backdrop_url") and not error_tmdb:
            final_poster = details.get("backdrop_url")

        movie_doc = {
            "_id": base_name,
            "files": [file_data],
            "poster_url": final_poster,
            "genres": genres,
            "rating": details.get("rating", "N/A"),
            "imdb_url": details.get("url", "") if not TMDB_POSTER or error_tmdb else details.get("tmdb_url"),
            "year": media_info["year"] or details.get("year"),
            "tag": media_info["tag"],
            "ott_platform": media_info["ott_platform"],
            "message_id": None,
            "is_photo": False,
            "error_tmdb": error_tmdb,
            "is_backdrop": True if LANDSCAPE_POSTER and details.get("backdrop_url") else False
        }
        # --- DATA FETCHING LOGIC END ---

        try:
            await db.movie_updates.insert_one(movie_doc)
            await send_movie_update(bot, base_name)
        except DuplicateKeyError:
            await db.movie_updates.update_one(
                {"_id": base_name},
                {"$push": {"files": file_data}}
            )
            schedule_update(bot, base_name)
    else:
        # Existing file handling
        if any(f["filename"] == filename for f in movie_doc["files"]):
            return
        await db.movie_updates.update_one(
            {"_id": base_name},
            {"$push": {"files": file_data}}
        )
        schedule_update(bot, base_name)

# --- SEND FUNCTION UPDATE ---
async def send_movie_update(bot, base_name):
    movie_doc = await db.movie_updates.find_one({"_id": base_name})
    if not movie_doc: return

    text = generate_movie_message(movie_doc, base_name)
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton('ɢᴇᴛ ғɪʟᴇs', url=f"https://t.me/{temp.U_NAME}?start=getfile-{base_name.replace(' ', '-')}")
    ]])

    # Dynamic Poster Size
    if LANDSCAPE_POSTER and movie_doc.get("is_backdrop"):
        img_size = (1280, 720) 
    else:
        img_size = (860, 1200)

    try:
        if movie_doc.get("poster_url"):
            # Fetch_image calling
            processed_post = await fetch_image(movie_doc["poster_url"], img_size)
            msg = await bot.send_photo(
                chat_id=MOVIE_UPDATE_CHANNEL,
                photo=processed_post,
                caption=text,
                reply_markup=buttons
            )
            is_photo = True
        else:
            msg = await bot.send_message(
                chat_id=MOVIE_UPDATE_CHANNEL,
                text=text,
                reply_markup=buttons
            )
            is_photo = False

        await db.movie_updates.update_one(
            {"_id": base_name},
            {"$set": {"message_id": msg.id, "is_photo": is_photo}}
        )
    except Exception as e:
        logger.error(f"Send Update Error: {e}")
