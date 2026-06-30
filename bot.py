import re
import asyncio
import json
import os
import random

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

BOT_TOKEN = "8422286281:AAGcb2_M7l2Aly7XohtRE2p296hNsW0nDvQ"
OWNER_ID = 5742325054
bot_enabled = True        # Весь бот (команды + модерация)
moderation_enabled = True # Только модерация (фильтр оскорблений)
chat_locked = False       # Заглушка чата

DATA_FILE = "bot_data.json"
LOG_FILE = "bot_log.txt"

# ── Загрузка / сохранение данных ──────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"stats": {}, "total_violations": 0, "user_info": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "stats": stats,
            "total_violations": total_violations,
            "user_info": user_info,
        }, f, ensure_ascii=False, indent=2)

_data = load_data()
stats            = _data.get("stats", {})
total_violations = _data.get("total_violations", 0)
user_info        = _data.get("user_info", {})

user_last_msg = defaultdict(str)
user_repeat   = defaultdict(int)

# ================== СИСТЕМА МАФИИ И ЭКОНОМИКИ ==================

mafia_games = {}

ROLES = {
    "mafia": "🔪 Мафия",
    "doctor": "❤️ Доктор",
    "civilian": "👤 Мирный житель",
}

MIN_PLAYERS = 4
MAX_PLAYERS = 20

# Проверка и инициализация базовых полей экономики для пользователя
def init_economy_fields(uid, name, username=""):
    if uid not in user_info:
        user_info[uid] = {
            "name": name,
            "username": username,
            "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "violations": 0,
            "money": 500,
            "gems": 10,
            "buffs": []
        }
    if "money" not in user_info[uid]: user_info[uid]["money"] = 500
    if "gems" not in user_info[uid]: user_info[uid]["gems"] = 10
    if "buffs" not in user_info[uid]: user_info[uid]["buffs"] = []
    save_data()

# ── Функция обновления сообщения набора в группу (Лобби) ──────────────────────
async def update_lobby_message(bot, chat_id):
    game = mafia_games[chat_id]
    bot_obj = await bot.get_me()
    bot_username = bot_obj.username
    
    # Кнопка «Присоединиться» — это deep link (переход в ЛС к боту с ID чата)
    keyboard = [
        [
            InlineKeyboardButton("➕ Присоединиться", url=f"https://t.me/{bot_username}?start=join_{chat_id}")
        ],
        [
            InlineKeyboardButton("▶ Начать", callback_data="mafia_start"),
            InlineKeyboardButton("❌ Отменить", callback_data="mafia_cancel")
        ]
    ]
    
    players_list = "\n".join([f"• {name}" for name in game["players"].values()])
    text = (
        "🎭 <b>Ведётся набор в игру «Мафия»!</b>\n\n"
        f"👥 Игроков: {len(game['players'])}/{MAX_PLAYERS}\n"
        f"⚠️ Минимум для старта: {MIN_PLAYERS}\n\n"
        f"<b>Текущее лобби:</b>\n{players_list}\n\n"
        "Нажмите кнопку ниже, чтобы войти в игру через ЛС бота! ❤️"
    )
    
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=game["message_id"],
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        print(f"[ОШИБКА] Обновление лобби: {e}")

# ── Создание игры в группе ───────────────────────────────────────────────────
async def mafia_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.message.chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❌ Игру можно запустить только в группе!")
        return

    if chat_id in mafia_games:
        await update.message.reply_text("❌ В этом чате уже идёт игра или сбор лобби!")
        return

    mafia_games[chat_id] = {
        "owner": update.effective_user.id,
        "players": {update.effective_user.id: update.effective_user.first_name},
        "started": False,
        "message_id": None,
        "status": "lobby",
        "roles": {},
        "alive": [],
        "votes": {},
        "voted": [],
        "night_kill": None,
        "night_heal": None,
        "last_word_user": None
    }
    
    init_economy_fields(str(update.effective_user.id), update.effective_user.first_name, update.effective_user.username or "")
    
    bot_obj = await context.bot.get_me()
    bot_username = bot_obj.username

    keyboard = [
        [InlineKeyboardButton("➕ Присоединиться", url=f"https://t.me/{bot_username}?start=join_{chat_id}")],
        [
            InlineKeyboardButton("▶ Начать", callback_data="mafia_start"),
            InlineKeyboardButton("❌ Отменить", callback_data="mafia_cancel")
        ]
    ]

    text = (
        "🎭 <b>Ведётся набор в игру «Мафия»!</b>\n\n"
        f"👥 Игроков: 1/{MAX_PLAYERS}\n"
        f"⚠️ Минимум для старта: {MIN_PLAYERS}\n\n"
        f"<b>Текущее лобби:</b>\n• {update.effective_user.first_name}\n\n"
        "Нажмите кнопку ниже, чтобы войти в игру через ЛС бота! ❤️"
    )

    msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    mafia_games[chat_id]["message_id"] = msg.message_id

# ── Хэндлер кнопок управления лобби и игровых действий ────────────────────────
async def mafia_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    uid = query.from_user.id

    # Логика голосования днем в группе
    if query.data.startswith("mafia_vote_"):
        target_id = int(query.data.split("_")[2])
        found_chat = None
        for c_id, g in mafia_games.items():
            if g.get("status") == "voting" and uid in g["alive"]:
                found_chat = c_id
                break
        if not found_chat:
            await query.answer("❌ Вы не можете голосовать сейчас!", show_alert=True)
            return
            
        g = mafia_games[found_chat]
        if uid in g["voted"]:
            await query.answer("❌ Вы уже отдали свой голос!", show_alert=True)
            return
            
        g["voted"].append(uid)
        if target_id not in g["votes"]:
            g["votes"][target_id] = []
        g["votes"][target_id].append(uid)
        await query.answer(f"✅ Голос против {g['players'][target_id]} засчитан!")
        return

    # Логика ночных скрытых действий в ЛС бота
    if query.data.startswith("mafia_target_"):
        parts = query.data.split("_")
        target_id = int(parts[2])
        g_chat_id = int(parts[3])
        
        if g_chat_id not in mafia_games:
            await query.answer("❌ Игра уже завершена.", show_alert=True)
            return
            
        g = mafia_games[g_chat_id]
        role = g["roles"].get(uid)
        
        if g["status"] != "night" or uid not in g["alive"]:
            await query.answer("❌ Вы не можете сделать ход.", show_alert=True)
            return
            
        if role == "mafia":
            g["night_kill"] = target_id
            await query.edit_message_text(f"🔪 Цель выбрана! Ночью вы убьёте: <b>{g['players'][target_id]}</b>", parse_mode="HTML")
        elif role == "doctor":
            g["night_heal"] = target_id
            await query.edit_message_text(f"❤️ Выбор сделан! Ночью вы вылечите: <b>{g['players'][target_id]}</b>", parse_mode="HTML")
        return

    # Управление лобби
    if chat_id not in mafia_games:
        return
    game = mafia_games[chat_id]

    if query.data == "mafia_cancel":
        if uid != game["owner"]:
            await query.answer("❌ Только создатель лобби может отменить игру.", show_alert=True)
            return
        del mafia_games[chat_id]
        await query.edit_message_text("❌ Сбор лобби отменен создателем.")
        return

    elif query.data == "mafia_start":
        if uid != game["owner"]:
            await query.answer("❌ Только создатель лобби может запустить игру.", show_alert=True)
            return
        if len(game["players"]) < MIN_PLAYERS:
            await query.answer(f"⚠️ Мало людей! Нужно минимум {MIN_PLAYERS} игрока.", show_alert=True)
            return

        game["started"] = True
        await query.edit_message_text("🎲 <b>Роли распределяются! Проверьте личные сообщения с ботом...</b>", parse_mode="HTML")
        
        roles_ok = await mafia_send_roles(context, chat_id)
        if roles_ok:
            asyncio.create_task(run_game_cycle(context, chat_id))

# ── Распределение ролей в ЛС ─────────────────────────────────────────────────
async def mafia_send_roles(context, chat_id):
    game = mafia_games[chat_id]
    players = list(game["players"].items())
    random.shuffle(players)
    count = len(players)

    if count <= 5:
        mafia_count = 1
    elif count <= 8:
        mafia_count = 2
    else:
        mafia_count = 3

    roles = ["mafia"] * mafia_count + ["doctor"]
    while len(roles) < count:
        roles.append("civilian")
    random.shuffle(roles)

    game["roles"] = {}
    for (uid, name), role in zip(players, roles):
        game["roles"][uid] = role
        try:
            if role == "mafia":
                text = "🔪 <b>Ты — Мафия!</b>\n\nТвоя задача — уничтожить мирных жителей и остаться незамеченным. Каждую ночь выбирай жертву."
            elif role == "doctor":
                text = "❤️ <b>Ты — Доктор!</b>\n\nКаждую ночь ты можешь спасти одного человека от нападения мафии. Себя лечить тоже можно!"
            else:
                text = "👨🏼 <b>Ты — Мирный житель!</b>\n\nТвоя задача вычислить коварную мафию и на городском собрании (днём) линчевать засранцев."
            
            await context.bot.send_message(uid, text, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(
                chat_id,
                f"❌ Игрок <b>{name}</b> не запустил бота в ЛС!\nИгра отменена. Пожалуйста, откройте чат с ботом, нажмите /start и соберите лобби заново.",
                parse_mode="HTML"
            )
            del mafia_games[chat_id]
            return False
    return True

# ── Главный автоматический игровой цикл ───────────────────────────────────────
async def run_game_cycle(context, chat_id):
    if chat_id not in mafia_games: return
    game = mafia_games[chat_id]
    game["alive"] = list(game["players"].keys())
    
    await asyncio.sleep(2)
    
    while True:
        # Проверка победы перед началом фазы
        winner = check_mafia_winners(game)
        if winner:
            await finish_mafia_game(context, chat_id, winner)
            break
            
        # ─── ФАЗА: НОЧЬ ───
        game["status"] = "night"
        game["night_kill"] = None
        game["night_heal"] = None
        
        alive_list = "\n".join([f"• {game['players'][p]}" for p in game["alive"]])
        await context.bot.send_message(
            chat_id,
            f"🌌 <b>Наступает ночь.</b> Город засыпает, на улицы выходят темные личности...\n\n"
            f"<b>Живые в игре:</b>\n{alive_list}\n\n"
            f"⏳ У активных ролей есть 35 секунд на выбор действий в ЛС бота!",
            parse_mode="HTML"
        )
        
        # Запрос действий в ЛС у живых ролей
        target_buttons = [[InlineKeyboardButton(game["players"][p], callback_data=f"mafia_target_{p}_{chat_id}")] for p in game["alive"]]
        night_markup = InlineKeyboardMarkup(target_buttons)
        
        for p_id in game["alive"]:
            role = game["roles"][p_id]
            try:
                if role == "mafia":
                    await context.bot.send_message(p_id, "🌙 Ночь! Выберите, кого хотите убрать из игры:", reply_markup=night_markup)
                elif role == "doctor":
                    await context.bot.send_message(p_id, "🌙 Ночь! Выберите, кого хотите излечить:", reply_markup=night_markup)
            except Exception: pass
            
        await asyncio.sleep(35) # Таймер ночи
        
        # ─── ФАЗА: ДЕНЬ ───
        game["status"] = "day"
        victim = game["night_kill"]
        saved = game["night_heal"]
        
        day_text = "🌅 <b>День Х. Солнце всходит, подсушивая на тротуарах пролитую ночью кровь...</b>\n\n"
        died_user = None
        
        if victim and victim != saved:
            died_user = victim
            game["alive"].remove(victim)
            role_ru = ROLES.get(game["roles"][victim], "Мирный житель")
            day_text += f"💀 Сегодня ночью был жестоко убит {role_ru} — <b>{game['players'][victim]}</b>.\n"
        else:
            day_text += "🕊️ Удивительно, но ночь прошла спокойно! Доктор сработал отлично, либо мафия промахнулась.\n"
            
        mafia_cnt = sum(1 for p in game["alive"] if game["roles"][p] == "mafia")
        doc_cnt = sum(1 for p in game["alive"] if game["roles"][p] == "doctor")
        civ_cnt = sum(1 for p in game["alive"] if game["roles"][p] == "civilian")
        day_text += f"\n📊 Кто-то из них: Мафия ({mafia_cnt}), Доктор ({doc_cnt}), Мирные ({civ_cnt}). Всего: {len(game['alive'])} чел."
        
        await context.bot.send_message(chat_id, day_text, parse_mode="HTML")
        
        # Логика предсмертной записки в ЛС убитому
        if died_user:
            game["last_word_user"] = died_user
            try:
                await context.bot.send_message(died_user, "💀 Тебя убили! Напиши сюда текст своего предсмертного послания, и я перешлю его в группу:")
            except Exception: pass
            await asyncio.sleep(15) # Ожидание текста предсмертной записки
            game["last_word_user"] = None
            
        # Проверка победы после ночных убийств
        winner = check_mafia_winners(game)
        if winner:
            await finish_mafia_game(context, chat_id, winner)
            break
            
        # ─── ФАЗА: ГОЛОСОВАНИЕ ───
        game["status"] = "voting"
        game["votes"] = {}
        game["voted"] = []
        
        vote_buttons = [[InlineKeyboardButton(game["players"][p], callback_data=f"mafia_vote_{p}")] for p in game["alive"]]
        
        vote_msg = await context.bot.send_message(
            chat_id,
            "⚖️ <b>Пришло время определить и наказать виноватых.</b>\n"
            "Голосование открыто! Нажмите кнопку с подозреваемым.\n"
            "⏳ Голосование продлится 35 секунд.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(vote_buttons)
        )
        
        await asyncio.sleep(35) # Таймер голосования
        
        try: await context.bot.edit_message_reply_markup(chat_id, vote_msg.message_id, reply_markup=None)
        except Exception: pass
        
        if not game["votes"]:
            await context.bot.send_message(chat_id, "Голосование окончено. Мнения жителей разошлись... так никого и не повесив... 🕊️")
        else:
            max_v = -1
            lynched = None
            is_tie = False
            for p_id, voters in game["votes"].items():
                if len(voters) > max_v:
                    max_v = len(voters)
                    lynched = p_id
                    is_tie = False
                elif len(voters) == max_v:
                    is_tie = True
                    
            if is_tie or max_v == 0:
                await context.bot.send_message(chat_id, "Голосование окончено. Мнения жителей разошлись... так никого и не повесив... 🕊️")
            else:
                game["alive"].remove(lynched)
                role_ru = ROLES.get(game["roles"][lynched], "Мирный житель")
                await context.bot.send_message(
                    chat_id,
                    f"⚖️ Суд Линча состоялся! Большинством в {max_v} голосов жители казнили <b>{game['players'][lynched]}</b>.\n"
                    f"Обыск показал, что он был: {role_ru}."
                )
        await asyncio.sleep(3)

# ── Проверка условий победы ──────────────────────────────────────────────────
def check_mafia_winners(game):
    mafia_cnt = sum(1 for p in game["alive"] if game["roles"][p] == "mafia")
    peaceful_cnt = sum(1 for p in game["alive"] if game["roles"][p] in ("civilian", "doctor"))
    
    if mafia_cnt == 0:
        return "civilians"
    if mafia_cnt >= peaceful_cnt:
        return "mafia"
    return None

# ── Завершение игры, раздача наград и профиль экономики ───────────────────────
async def finish_mafia_game(context, chat_id, winner):
    game = mafia_games[chat_id]
    
    win_title = "🏆 <b>Победили Мирные жители!</b> Город чист." if winner == "civilians" else "🏆 <b>Победила Мафия!</b> Преступники захватили контроль."
    
    summary = f"🎉 <b>Игра окончена!</b>\n\n{win_title}\n\n👥 <b>Роли всех участников:</b>\n"
    for p_id, name in game["players"].items():
        role_key = game["roles"][p_id]
        role_ru = ROLES.get(role_key, "Мирный")
        status_str = "🟢 Жив" if p_id in game["alive"] else "💀 Мертв"
        summary += f"• {name} — {role_ru} ({status_str})\n"
        
        # Раздача денег
        uid_str = str(p_id)
        init_economy_fields(uid_str, name)
        
        is_winner = (winner == "mafia" and role_key == "mafia") or (winner == "civilians" and role_key in ("civilian", "doctor"))
        reward = 350 if is_winner else 120
        user_info[uid_str]["money"] += reward
        
        try:
            await context.bot.send_message(
                p_id,
                f"📊 Игра в группе завершена!\n"
                f"Вы получили: 💵 <b>{reward} монет</b>.\n"
                f"Твой новый баланс: 💵 {user_info[uid_str]['money']}\n"
                f"Напиши /profile в ЛС, чтобы открыть магазин бонусов и баффов ролей!",
                parse_mode="HTML"
            )
        except Exception: pass
        
    save_data()
    await context.bot.send_message(chat_id, summary, parse_mode="HTML")
    if chat_id in mafia_games:
        del mafia_games[chat_id]

# ── Личный профиль и Магазин баффов ролей (В ЛС) ──────────────────────────────
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ("group", "supergroup"):
        await update.message.reply_text("🏦 Твой профиль доступен только в личных сообщениях с ботом! Напиши мне в ЛС.")
        return
        
    uid = str(update.effective_user.id)
    init_economy_fields(uid, update.effective_user.first_name, update.effective_user.username or "")
    
    info = user_info[uid]
    buffs_str = ", ".join(info["buffs"]) if info["buffs"] else "Нет купленных баффов"
    
    text = (
        f"🏦 <b>Твой игровой Профиль и Кошелёк</b>\n\n"
        f"💵 Баланс денег: <b>{info['money']}</b>\n"
        f"💎 Баланс камней: <b>{info['gems']}</b>\n"
        f"👑 Активные баффы на роли: <i>{buffs_str}</i>\n\n"
        f"Если не везёт с выпадением активной роли, то в Магазине можно купить бафф на шанс выпадения! 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("🛒 Купить Бафф Мафии (300 💵)", callback_data="shop_buy_mafia")],
        [InlineKeyboardButton("🛒 Купить Бафф Доктора (300 💵)", callback_data="shop_buy_doctor")],
        [InlineKeyboardButton("💎 Обменять 1 камень ➔ 150 💵", callback_data="shop_exchange")]
    ]
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

# ── Обработчик Callback-покупок в магазине ──────────────────────────────────
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    
    if uid not in user_info: return
    info = user_info[uid]
    
    if query.data == "shop_buy_mafia":
        if info["money"] < 300:
            await query.answer("❌ Недостаточно монет на балансе!", show_alert=True)
            return
        info["money"] -= 300
        info["buffs"].append("Шанс Мафии 🔪")
        save_data()
        await query.answer("🎉 Бафф на Мафию успешно приобретен!", show_alert=True)
    elif query.data == "shop_buy_doctor":
        if info["money"] < 300:
            await query.answer("❌ Недостаточно монет на балансе!", show_alert=True)
            return
        info["money"] -= 300
        info["buffs"].append("Шанс Доктора ❤️")
        save_data()
        await query.answer("🎉 Бафф на Доктора успешно приобретен!", show_alert=True)
    elif query.data == "shop_exchange":
        if info["gems"] < 1:
            await query.answer("❌ У вас нет драгоценных камней!", show_alert=True)
            return
        info["gems"] -= 1
        info["money"] += 150
        save_data()
        await query.answer("✨ Успешный обмен! Получено 150 монет.", show_alert=True)
        
    buffs_str = ", ".join(info["buffs"]) if info["buffs"] else "Нет купленных баффов"
    text = (
        f"🏦 <b>Твой игровой Профиль и Кошелёк</b>\n\n"
        f"💵 Баланс денег: <b>{info['money']}</b>\n"
        f"💎 Баланс камней: <b>{info['gems']}</b>\n"
        f"👑 Активные баффы на роли: <i>{buffs_str}</i>\n\n"
        f"Если не везёт с выпадением активной роли, то в Магазине можно купить бафф на шанс выпадения! 👇"
    )
    keyboard = [
        [InlineKeyboardButton("🛒 Купить Бафф Мафии (300 💵)", callback_data="shop_buy_mafia")],
        [InlineKeyboardButton("🛒 Купить Бафф Доктора (300 💵)", callback_data="shop_buy_doctor")],
        [InlineKeyboardButton("💎 Обменять 1 камень ➔ 150 💵", callback_data="shop_exchange")]
    ]
    try: await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception: pass

# ── Измененный обработчик команды /start для поддержки Deep Links ─────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    uid = update.effective_user.id
    name = update.effective_user.first_name
    
    # Если зашли через кнопку глубокой ссылки «Присоединиться»
    if args and args[0].startswith("join_"):
        try: target_chat_id = int(args[0].replace("join_", ""))
        except ValueError:
            await update.message.reply_text("❌ Сломанная ссылка регистрации лобби.")
            return
            
        if target_chat_id not in mafia_games:
            await update.message.reply_text("❌ Сбор лобби в этой группе уже завершён или отменён.")
            return
            
        game = mafia_games[target_chat_id]
        if game["started"]:
            await update.message.reply_text("❌ Игра в группе уже началась, вход закрыт!")
            return
            
        if uid in game["players"]:
            await update.message.reply_text("Да в игре ты уже! Слышишь? В игре! :) ❤️")
            return
            
        if len(game["players"]) >= MAX_PLAYERS:
            await update.message.reply_text("❌ В лобби закончились свободные места.")
            return
            
        game["players"][uid] = name
        init_economy_fields(str(uid), name, update.effective_user.username or "")
        await update.message.reply_text("Ты успешно присоединился к игре! ❤️ Жди запуска создателем.")
        
        # Обновляем список в группе
        await update_lobby_message(context.bot, target_chat_id)
        return

    # Обычный /start в ЛС
    await update.message.reply_text("👋 Привет! Я многофункциональный игровой бот. Напиши команду /help, чтобы увидеть весь список моих возможностей.")

# ================== СТАРЫЙ ФУНКЦИОНАЛ МОДЕРАЦИИ И ИГР ==================

# ── Логирование ───────────────────────────────────────────────────────────────
def log(action: str, details: str = ""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {action}"
    if details: line += f" | {details}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

async def send_owner_log(bot, text: str):
    try: await bot.send_message(chat_id=OWNER_ID, text=text, parse_mode="HTML")
    except Exception as e: print(f"[ОШИБКА] Лог владельцу: {e}")

# Паттерны оскорблений
INSULT_PATTERNS = [
    r"\bдаун\b", r"\bдауна\b", r"\bдауны\b", r"д[аa][уy]н",
    r"\bэблан\b", r"\bэблана\b", r"\bеблан\b", r"\bёблан\b",
    r"\bеблана\b", r"\bёблана\b", r"[эeеёЕЭЁ]бл[аa]н", r"[эeеёЕЭЁ]б[лl][аa4]н",
    r"иди\s*на[хx\*х]+", r"иди\s*н[4а][хx\*х]", r"ид[и1]\s*на[хx\*х]",
    r"пошёл?\s*на[хx\*х]", r"пош[её]л\s*на[хx\*х]", r"вали\s*на[хx\*х]",
    r"иди\s+на\s+х[уy][иiй]", r"иди\s+на\s+[хx][уy][иiй]",
    r"ид[и1]\s+на\s+[хx][уy][иiй]", r"иди\s*на\s*[хx][уy][иiй]",
    r"\b(ты|вы|он|она|оно)\s*(тупой|тупая|тупые|тупо[ей])",
    r"\b(ты|вы|он|она|оно)\s*(идиот|идиотка|дебил|дебилка|кретин|кретинка)",
    r"\b(ты|вы|он|она|оно)\s*(урод|уродина|урода)",
    r"\b(ты|вы|он|она|оно)\s*(лох|лоха|лошара|лохушка)",
    r"\b(ты|вы|он|она|оно)\s*(мразь|тварь|скотина|ублюдок|ублюдка)",
    r"\b(ты|вы|он|она|оно)\s*(придурок|придурка|даун|дауна)",
    r"\b(ты|вы|он|она|оно)\s*(нуб|нубас|нубик)",
    r"\b(ты|вы|он|она|оно)\s*г[аa][нn][дd][оo][нn]",
    r"\b(ты|вы|он|она|оно)\s*[хx][уy][её][сc][оo][сc]",
    r"\b(ты|вы|он|она|оно)\s*п[иi1][дd][аa][рp][аa][сc]",
    r"\b(ты|вы|он|она|оно)\s*п[иi1][дd][оo][рp]",
    r"\b(ты|вы|он|она|оно)\s*[уy][её][бb][аa][нn]",
    r"\bтупица\b", r"\bдебил[аку]?\b", r"\bидиот[аку]?\b", r"\bкретин[аку]?\b",
    r"\bурод(ина|а)?\b", r"\bлошара\b", r"\bлохушка\b", r"\bмразь\b",
    r"\bтварь\b", r"\bскотина\b", r"\bублюдок\b", r"\bублюдка\b",
    r"\bпридурок\b", r"\bпридурка\b", r"\bлох\b", r"\bлоха\b",
    r"\bгандон\b", r"\bгандона\b", r"\bгандоны\b",
    r"\bхуесос\b", r"\bхуесоска\b",
    r"\bпидарас\b", r"\bпидараса\b", r"\bпидор\b", r"\bпидора\b",
    r"\bпидоры\b", r"\bпидорас\b",
    r"\bуебан\b", r"\bуебана\b", r"\bуебаны\b", r"\bуёбан\b",
    r"\bчмо\b", r"\bчмошник\b", r"\bчмошница\b",
    r"\bсучка\b", r"\bсучки\b", r"\bсучку\b", r"\bсука\b", r"\bсуки\b",
    r"\bблядь\b", r"\bбляди\b", r"\bблядина\b", r"\bшлюха\b", r"\bшлюхи\b",
    r"\bебанашка\b", r"\bёбанашка\b", r"\bсучонок\b", r"\bсучара\b",
    r"д[еe3]б[иi1]л", r"[иi1]д[иi1][оo0]т", r"кр[еe3]т[иi1]н",
    r"т[уy][пп][оo0][йеея]", r"[уу]р[оo0]д", r"[уу]б[лл][юю]д[оo0]к",
    r"пр[иi1]д[уу]р[оo0]к", r"г[аa][нn][дd][оo][нn]",
    r"[хx][уy][её][сc][оo][сc]", r"п[иi1][дd][аa][рp][аa][сc]",
    r"п[иi1][дd][оo][рp]", r"[уy][её][бb][аa][нn]",
    r"с[уy][чч][кk][аa]", r"с[уy][кk][аa]", r"бл[яy][дd]",
    r"[её]б[аa][нн][аa][яy]\s*(мать|маму|батю|отца|сестру|брата|бабушку|деда|отчима)",
    r"[её]б[аa][нн][ыы][йи]\s*(отец|батя|брат|дед|отчим)",
    r"ид[иi1]\s*[её]б", r"[её]б[иись]\s*(отсюда|нах)",
    r"за[тт]кни[сс]ь", r"за[тт]кни\s*рот",
    r"убью\s*(тебя|вас|его|её)", r"прибью\s*(тебя|вас|его|её)",
    r"н[аa]х[уy][иi]", r"[пp][иi1][зz3][дd][аa]",
    r"\bпизда\b", r"\bпизды\b", r"\bпизде\b", r"\bпизду\b",
    r"п[иi1]зд[аaеeуy]", r"п[иi1][зz3]д",
    r"[хx][уy][иiй]\s*[тt][её][бb][её]", r"[хx][уy][иiй]\s*[тt][её][бb][яa]",
    r"[хx][уy][иiй]\s*[тt][яy]", r"[хx][уy][иiй]\s*[вv][аa][мm]",
    r"[хx][уy][иiй]\s*[тt][её][бb][её]\s*в\s*р[оo][тt]",
    r"[хx][уy][иiй]\s*в\s*р[оo][тt]", r"в\s*р[оo][тt]\s*[тt][её][бb][её]",
    r"в\s*р[оo][тt]\s*[её][бb][уy]",
    r"[тt][её][бb][яa]\s*[её][бb][аa][лл]", r"[тt][её][бb][яa]\s*[эe][бb][аa][лл]",
    r"[тt][её][бb][яa]\s*[её][бb][уy]", r"[тt][её][бb][яa]\s*[её][бb][аa][тт][ьъ]",
    r"[тt][её][бb][яa]\s*[её][бb][аa][тт]",
    r"[яy]\s*[тt][её][бb][яa]\s*[её][бb][аa][лл]",
    r"[яy]\s*[тt][её][бb][яa]\s*[эe][бb][аa][лл]",
    r"[яy]\s*[тt][её][бb][яa]\s*[её][бb][уy]",
    r"[яy]\s*[тt][её][бb][яa]\s*в\s*р[оo][тt]",
    r"[яy]\s*[тt][вv][оo][юy]\s*м[аa][тt][ьъ]\s*[её][бb][аa][лл]",
    r"[яy]\s*[тt][вv][оo][юy]\s*[Mm][аa][тt][ьъ]\s*[её][бb][аa][лл]",
    r"м[аa][тt][ьъ]\s*[тt][вv][оo][юy]\s*[её][бb][аa][нн][аa][яy]",
    r"[тt][вv][оo][юy]\s*м[аa][тt][ьъ]\s*[её][бb][аa][нн][аa][яy]",
    r"[тt][вv][оo][юy]\s*[Mm][аa][тt][ьъ]\s*[хx][уy][иiй][нн][яy]",
    r"[её][бb][аa][тт][ьъ]\s*(твою?|его|её|вашу?)\s*(мать|маму|батю|отца|сестру|брата|бабушку|деда|отчима)",
    r"[её][бb][уy]\s*(твою?|его|её|вашу?)\s*(мать|маму|батю|отца|сестру|брата|бабушку|деда|отчима)",
    r"[яy]\s*(твоего?|твою|вашего?|вашу)\s*(отчима|мать|маму|батю|отца|сестру|брата|бабушку|деда|папу|мачеху)\s*[её][бb][аa][лл]",
    r"(иди|ади|вали|пошёл|пошел)\s*[чч][мm][оo]",
]
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE | re.UNICODE) for p in INSULT_PATTERNS]

def contains_insult(text):
    for pattern in COMPILED_PATTERNS:
        if pattern.search(text): return True
    return False

async def unmute_user(bot, chat_id, user_id, mention, mute_msg_id):
    await asyncio.sleep(15)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_polls=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
            ),
        )
    except Exception as e:
        print(f"[ОШИБКА] Снятие мута: {e}")
        return
    try: await bot.delete_message(chat_id=chat_id, message_id=mute_msg_id)
    except Exception: pass
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔊 {mention} — мут снят, можете снова общаться.\n⚠️ Следите за языком!",
            parse_mode="HTML",
        )
    except Exception as e: print(f"[ОШИБКА] Сообщение снятия мута: {e}")

async def do_mute(context, chat_id, user_id, mention, reason="оскорбление", deleted_text=""):
    global total_violations
    mute_until = datetime.now(timezone.utc) + timedelta(seconds=20)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False, can_send_polls=False,
                can_send_other_messages=False, can_add_web_page_previews=False,
            ),
            until_date=mute_until,
        )
    except Exception as e: print(f"[ОШИБКА] Мут: {e}")

    total_violations += 1
    uid = str(user_id)
    if uid not in stats: stats[uid] = {"violations": 0, "name": ""}
    stats[uid]["violations"] += 1
    if uid in user_info: user_info[uid]["violations"] = user_info[uid].get("violations", 0) + 1
    save_data()

    name = stats[uid].get("name", uid)
    log("МУТ", f"user={name} ({uid}) | причина={reason} | сообщение={deleted_text[:80]}")
    await send_owner_log(
        context.bot,
        f"🔇 <b>МУТ</b>\n👤 {mention} (ID: <code>{user_id}</code>)\n📌 Причина: {reason}\n"
        + (f"💬 Сообщение: <i>{deleted_text[:200]}</i>\n" if deleted_text else "")
        + f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        mute_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔇 {mention} получил мут на <b>15 секунд</b> за {reason}.\n❌ Сообщение удалено.",
            parse_mode="HTML",
        )
        asyncio.ensure_future(unmute_user(context.bot, chat_id, user_id, mention, mute_msg.message_id))
    except Exception as e: print(f"[ОШИБКА] Сообщение мута: {e}")

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        uid = str(member.id)
        init_economy_fields(uid, member.first_name, member.username or "")
        log("ВСТУПЛЕНИЕ", f"user={member.first_name} ({uid})")
        mention = f'<a href="tg://user?id={member.id}">{member.first_name}</a>'
        await update.message.reply_text(
            f"👋 Привет, {mention}! Добро пожаловать!\n📋 Маты разрешены, оскорбления — запрещены.\n📌 /rules — правила.",
            parse_mode="HTML",
        )

# ── Перехват сообщений (Антиспам + Проверка Предсмертных записок) ──────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global chat_locked
    if not bot_enabled: return

    message = update.message
    if not message or not message.text: return
    user = message.from_user
    text = message.text
    uid = str(user.id)

    # Перехват предсмертной записки Мафии в ЛС
    if message.chat.type == "private":
        for c_id, g in mafia_games.items():
            if g.get("last_word_user") == user.id:
                g["last_word_user"] = None
                mention_dead = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
                await context.bot.send_message(
                    chat_id=c_id,
                    text=f"✉️ <b>[Роковое послание] {mention_dead} жестоко убит, но успел написать:</b>\n« <i>{text}</i> »",
                    parse_mode="HTML"
                )
                await update.message.reply_text("✅ Ваша предсмертная записка успешно доставлена в чат группы.")
                return
        return

    if message.chat.type not in ("group", "supergroup"): return

    if chat_locked and user.id != OWNER_ID:
        try: await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        except Exception: pass
        return

    init_economy_fields(uid, user.first_name, user.username or "")

    if uid not in stats: stats[uid] = {"violations": 0, "name": user.first_name}
    stats[uid]["name"] = user.first_name
    user_info[uid]["name"] = user.first_name

    mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    # Антиспам
    if text == user_last_msg[user.id]:
        user_repeat[user.id] += 1
        if user_repeat[user.id] >= 3:
            user_repeat[user.id] = 0
            try: await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
            except Exception: pass
            log("СПАМ", f"user={user.first_name} ({uid}) | текст={text[:60]}")
            await do_mute(context, message.chat_id, user.id, mention, "спам", text)
            return
    else:
        user_repeat[user.id] = 0
        user_last_msg[user.id] = text

    # Фильтр оскорблений
    if not moderation_enabled or not contains_insult(text): return

    try: await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception: return

    log("ОСКОРБЛЕНИЕ", f"user={user.first_name} ({uid}) | текст={text[:80]}")
    await do_mute(context, message.chat_id, user.id, mention, "оскорбление", text)

# Команды модерации
async def toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global moderation_enabled
    if update.message.from_user.id != OWNER_ID: return
    moderation_enabled = not moderation_enabled
    await update.message.reply_text("✅ Фильтр оскорблений активен." if moderation_enabled else "❌ Фильтр оскорблений выключен.")

async def toggle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    if update.message.from_user.id != OWNER_ID: return
    bot_enabled = not bot_enabled
    await update.message.reply_text("✅ Бот включён." if bot_enabled else "❌ Бот выключен.")

async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global chat_locked

    if update.message.from_user.id != OWNER_ID:
        return

    chat_locked = not chat_locked

    try:
        if chat_locked:
            await context.bot.set_chat_permissions(
                chat_id=update.effective_chat.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                )
            )
            await update.message.reply_text("🔒 Чат полностью закрыт. Никто не может писать.")
        else:
            await context.bot.set_chat_permissions(
                chat_id=update.effective_chat.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await update.message.reply_text("🔓 Чат открыт.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    target = update.message.reply_to_message.from_user
    await do_mute(context, update.message.chat_id, target.id, f'<a href="tg://user?id={target.id}">{target.first_name}</a>', "решение админа")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    target = update.message.reply_to_message.from_user
    await context.bot.restrict_chat_member(chat_id=update.message.chat_id, user_id=target.id, permissions=ChatPermissions(can_send_messages=True))
    await update.message.reply_text(f"🔊 {target.first_name} размучен.")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await update.message.reply_text(f"🚫 {target.first_name} забанен.")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await context.bot.unban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await update.message.reply_text(f"👢 {target.first_name} кикнут.")

async def cmd_mute_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not context.args: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    raw = context.args[0].lower()
    if raw.endswith("m"): delta = timedelta(minutes=int(raw[:-1]))
    elif raw.endswith("h"): delta = timedelta(hours=int(raw[:-1]))
    else: return
    target = update.message.reply_to_message.from_user
    await context.bot.restrict_chat_member(chat_id=update.message.chat_id, user_id=target.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now(timezone.utc) + delta)
    await update.message.reply_text(f"🔇 Юзер замучен на {raw}.")

async def cmd_clearwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"): return
    target = update.message.reply_to_message.from_user
    uid = str(target.id)
    if uid in stats: stats[uid]["violations"] = 0
    if uid in user_info: user_info[uid]["violations"] = 0
    save_data()
    await update.message.reply_text(f"✅ Нарушения пользователя {target.first_name} сброшены.")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Всего нарушений поймано ботом: <b>{total_violations}</b>", parse_mode="HTML")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats: return
    sorted_users = sorted(stats.items(), key=lambda x: x[1]["violations"], reverse=True)[:5]
    text = "🏆 <b>Топ нарушителей:</b>\n\n"
    for i, (uid, data) in enumerate(sorted_users, 1): text += f"{i}. {data['name']} — <b>{data['violations']}</b>\n"
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    await update.message.reply_text("✅ Жалоба отправлена владельцу.")

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user
    uid = str(target.id)
    info = user_info.get(uid, {})
    await update.message.reply_text(f"👤 <b>Инфо:</b> {target.first_name}\nID: <code>{target.id}</code>\nМутов: {stats.get(uid, {}).get('violations', 0)}", parse_mode="HTML")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Твой ID: <code>{update.message.from_user.id}</code>", parse_mode="HTML")

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 <b>Правила:</b> Маты разрешены, оскорбления и спам запрещены.", parse_mode="HTML")

async def cmd_chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💬 Чат: {update.message.chat.title}\nID: <code>{update.message.chat.id}</code>", parse_mode="HTML")

# Активности / Игры
async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 Бросок кубика: <b>{random.randint(1, 6)}</b>", parse_mode="HTML")

async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🪙 Результат: <b>{random.choice(['🦅 Орёл', '🪙 Решка'])}</b>", parse_mode="HTML")

async def cmd_8ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = ["🟢 Да!", "🟡 Спроси позже.", "🔴 Нет."]
    await update.message.reply_text(f"🎱 Ответ: <b>{random.choice(answers)}</b>", parse_mode="HTML")

async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🌟 Твой рейтинг: <b>{random.randint(1, 10)}/10</b>", parse_mode="HTML")

async def cmd_casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    slots = ["🍒", "🍋", "🍊", "⭐", "💎", "7️⃣"]
    res = [random.choice(slots) for _ in range(3)]
    await update.message.reply_text(f"🎰 [ {' | '.join(res)} ]", parse_mode="HTML")

async def cmd_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    w = random.choice([update.message.from_user, update.message.reply_to_message.from_user])
    await update.message.reply_text(f"⚔️ В дуэли побеждает <b>{w.first_name}</b>!", parse_mode="HTML")

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Сегодня отличный день для партии в Мафию!")

async def cmd_anekdot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("😂 Шёл программист по улице, видит: баг висит. Взял и пофиксил.")

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID or not os.path.exists(LOG_FILE): return
    with open(LOG_FILE, "r", encoding="utf-8") as f: lines = f.readlines()
    await update.message.reply_text(f"<pre>{''.join(lines[-20:])}</pre>", parse_mode="HTML")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Список всех команд:</b>\n\n"
        "🎭 <b>Мафия:</b>\n"
        "/mafia — Запустить сбор лобби на Мафию в группе\n"
        "/profile — Проверить монеты, камни и купить бафф шанса ролей (в ЛС)\n\n"
        "👮 <b>Админы:</b> /mute, /mute_time, /unmute, /ban, /kick, /clearwarns\n"
        "🎮 <b>Мини-игры:</b> /roll, /flip, /8ball, /rate, /casino, /duel, /anekdot, /today"
    )

# ── Главная функция ───────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация перехватчиков Мафии и Диплинков
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("mafia", mafia_create))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CallbackQueryHandler(mafia_buttons, pattern="^mafia_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    
    # Модерация
    app.add_handler(CommandHandler("off", toggle_all))
    app.add_handler(CommandHandler("bot", toggle_bot))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("mute_time", cmd_mute_time))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("clearwarns", cmd_clearwarns))
    app.add_handler(CommandHandler("report", cmd_report))

    # Статистика и инфо
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("chatinfo", cmd_chatinfo))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("help", cmd_help))

    # Развлечения
    app.add_handler(CommandHandler("roll", cmd_roll))
    app.add_handler(CommandHandler("flip", cmd_flip))
    app.add_handler(CommandHandler("8ball", cmd_8ball))
    app.add_handler(CommandHandler("rate", cmd_rate))
    app.add_handler(CommandHandler("casino", cmd_casino))
    app.add_handler(CommandHandler("duel", cmd_duel))
    app.add_handler(CommandHandler("anekdot", cmd_anekdot))
    app.add_handler(CommandHandler("today", cmd_today))

    # Текстовые сообщения и вступления
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log("ЗАПУСК", "Бот запущен")
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
