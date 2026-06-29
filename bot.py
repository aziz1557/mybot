import re
import asyncio
import json
import os
import random

from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
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

# ================== НАСТРОЙКИ МАФИИ ==================
mafia_games = {}

ROLES = {
    "mafia": "🔪 Глава мафии",
    "doctor": "❤️ Доктор",
    "civilian": "👤 Мирный житель",
}

MIN_PLAYERS = 4
MAX_PLAYERS = 20

# ── Логирование ───────────────────────────────────────────────────────────────
def log(action: str, details: str = ""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {action}"
    if details:
        line += f" | {details}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

async def send_owner_log(bot, text: str):
    try:
        await bot.send_message(chat_id=OWNER_ID, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"[ОШИБКА] Лог владельцу: {e}")

# ── Паттерны оскорблений ──────────────────────────────────────────────────────
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
        if pattern.search(text):
            return True
    return False

# ── Снятие мута ───────────────────────────────────────────────────────────────
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
    try:
        await bot.delete_message(chat_id=chat_id, message_id=mute_msg_id)
    except Exception:
        pass
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔊 {mention} — мут снят, можешь снова писать.\n⚠️ Следи за словами!",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[ОШИБКА] Сообщение о снятии мута: {e}")

# ── Выдача мута ───────────────────────────────────────────────────────────────
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
    except Exception as e:
        print(f"[ОШИБКА] Мут: {e}")

    total_violations += 1
    uid = str(user_id)
    if uid not in stats:
        stats[uid] = {"violations": 0, "name": ""}
    stats[uid]["violations"] += 1
    if uid in user_info:
        user_info[uid]["violations"] = user_info[uid].get("violations", 0) + 1
    save_data()

    name = stats[uid].get("name", uid)
    log("МУТ", f"user={name} ({uid}) | причина={reason} | сообщение={deleted_text[:80]}")
    await send_owner_log(
        context.bot,
        f"🔇 <b>МУТ</b>\n"
        f"👤 {mention} (ID: <code>{user_id}</code>)\n"
        f"📌 Причина: {reason}\n"
        + (f"💬 Сообщение: <i>{deleted_text[:200]}</i>\n" if deleted_text else "")
        + f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        mute_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔇 {mention} получил мут на <b>15 секунд</b> за {reason}.\n"
                f"❌ Сообщение удалено.\n"
                f"⏳ Писать снова можно будет через <b>15 секунд</b>."
            ),
            parse_mode="HTML",
        )
        asyncio.ensure_future(unmute_user(context.bot, chat_id, user_id, mention, mute_msg.message_id))
    except Exception as e:
        print(f"[ОШИБКА] Сообщение о муте: {e}")

# ── Приветствие новых участников ──────────────────────────────────────────────
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        uid = str(member.id)
        if uid not in user_info:
            user_info[uid] = {
                "name": member.first_name,
                "username": member.username or "",
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "violations": 0,
            }
            save_data()
        log("ВСТУПЛЕНИЕ", f"user={member.first_name} ({uid})")
        mention = f'<a href="tg://user?id={member.id}">{member.first_name}</a>'
        await update.message.reply_text(
            f"👋 Привет, {mention}! Добро пожаловать в группу!\n"
            f"📋 Маты разрешены, оскорбления — нет.\n"
            f"📌 Напиши /rules чтобы узнать правила.",
            parse_mode="HTML",
        )

# ── Основной обработчик сообщений ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global chat_locked
    if not bot_enabled:
        return

    message = update.message
    if not message or not message.text:
        return
    if message.chat.type not in ("group", "supergroup"):
        return

    user = message.from_user
    chat_id = message.chat_id
    text = message.text
    uid = str(user.id)

    if chat_locked and user.id != OWNER_ID:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception:
            pass
        return

    if uid not in user_info:
        user_info[uid] = {
            "name": user.first_name,
            "username": user.username or "",
            "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "violations": 0,
        }
        save_data()

    if uid not in stats:
        stats[uid] = {"violations": 0, "name": user.first_name}
    stats[uid]["name"] = user.first_name
    user_info[uid]["name"] = user.first_name

    mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    if text == user_last_msg[user.id]:
        user_repeat[user.id] += 1
        if user_repeat[user.id] >= 3:
            user_repeat[user.id] = 0
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except Exception:
                pass
            log("СПАМ", f"user={user.first_name} ({uid}) | текст={text[:60]}")
            await do_mute(context, chat_id, user.id, mention, "спам", text)
            return
    else:
        user_repeat[user.id] = 0
        user_last_msg[user.id] = text

    if not moderation_enabled or not contains_insult(text):
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        print(f"[ОШИБКА] Удаление: {e}")
        return

    log("ОСКОРБЛЕНИЕ", f"user={user.first_name} ({uid}) | текст={text[:80]}")
    await do_mute(context, chat_id, user.id, mention, "оскорбление", text)

# ── Команды модерации ─────────────────────────────────────────────────────────
async def toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global moderation_enabled
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return
    moderation_enabled = not moderation_enabled
    status = "✅ Модерация включена — фильтр оскорблений активен." if moderation_enabled else "❌ Модерация выключена — фильтр оскорблений остановлен."
    log("МОДЕРАЦИЯ", f"moderation_enabled={moderation_enabled}")
    await update.message.reply_text(status)

async def toggle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return
    bot_enabled = not bot_enabled
    status = (
        "✅ <b>Бот полностью включён</b> — все команды и модерация активны."
        if bot_enabled else
        "❌ <b>Бот полностью выключен</b> — не реагирует ни на что."
    )
    log("БОТ", f"bot_enabled={bot_enabled}")
    await update.message.reply_text(status, parse_mode="HTML")

async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global chat_locked
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return
    chat_locked = not chat_locked
    if chat_locked:
        log("ЧАТ ЗАКРЫТ", f"владелец={update.message.from_user.first_name}")
        await update.message.reply_text(
            "🔒 <b>Чат заглушён!</b>\nТолько владелец может писать сообщения.\nИспользуй /lock снова чтобы открыть чат.",
            parse_mode="HTML",
        )
    else:
        log("ЧАТ ОТКРЫТ", f"владелец={update.message.from_user.first_name}")
        await update.message.reply_text(
            "🔓 <b>Чат открыт!</b>\nВсе участники снова могут писать.",
            parse_mode="HTML",
        )

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы замутить.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    mention = f'<a href="tg://user?id={target.id}">{target.first_name}</a>'
    log("МУТ (АДМИН)", f"admin={update.message.from_user.first_name} | target={target.first_name} ({target.id})")
    await send_owner_log(
        context.bot,
        f"🔇 <b>МУТ (АДМИН)</b>\n👮 Админ: {update.message.from_user.first_name}\n👤 Цель: {mention} (ID: <code>{target.id}</code>)\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await do_mute(context, update.message.chat_id, target.id, mention, "решение админа")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы размутить.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    await context.bot.restrict_chat_member(
        chat_id=update.message.chat_id, user_id=target.id,
        permissions=ChatPermissions(
            can_send_messages=True, can_send_polls=True,
            can_send_other_messages=True, can_add_web_page_previews=True,
        ),
    )
    log("РАЗМУТ (АДМИН)", f"admin={update.message.from_user.first_name} | target={target.first_name} ({target.id})")
    await update.message.reply_text(f"🔊 {target.first_name} размучен.")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы забанить.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    mention = f'<a href="tg://user?id={target.id}">{target.first_name}</a>'
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    log("БАН (АДМИН)", f"admin={update.message.from_user.first_name} | target={target.first_name} ({target.id})")
    await send_owner_log(
        context.bot,
        f"🚫 <b>БАН</b>\n👮 Админ: {update.message.from_user.first_name}\n👤 Цель: {mention} (ID: <code>{target.id}</code>)\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(f"🚫 {target.first_name} забанен.")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы кикнуть.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    mention = f'<a href="tg://user?id={target.id}">{target.first_name}</a>'
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await context.bot.unban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    log("КИК (АДМИН)", f"admin={update.message.from_user.first_name} | target={target.first_name} ({target.id})")
    await send_owner_log(
        context.bot,
        f"👢 <b>КИК</b>\n👮 Админ: {update.message.from_user.first_name}\n👤 Цель: {mention} (ID: <code>{target.id}</code>)\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(f"👢 {target.first_name} кикнут.")

async def cmd_mute_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение и укажи время: /mute_time 10m | 1h | 1d")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    args = context.args
    if not args:
        await update.message.reply_text("⏱ Укажи время: /mute_time 10m | 1h | 1d")
        return
    raw = args[0].lower()
    if raw.endswith("m"):
        delta = timedelta(minutes=int(raw[:-1]))
        label = f"{raw[:-1]} минут"
    elif raw.endswith("h"):
        delta = timedelta(hours=int(raw[:-1]))
        label = f"{raw[:-1]} часов"
    elif raw.endswith("d"):
        delta = timedelta(days=int(raw[:-1]))
        label = f"{raw[:-1]} дней"
    else:
        await update.message.reply_text("❌ Формат: 10m, 1h, 2d")
        return
    target = update.message.reply_to_message.from_user
    mute_until = datetime.now(timezone.utc) + delta
    await context.bot.restrict_chat_member(
        chat_id=update.message.chat_id, user_id=target.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=mute_until,
    )
    mention = f'<a href="tg://user?id={target.id}">{target.first_name}</a>'
    log("МУТ НА ВРЕМЯ", f"admin={update.message.from_user.first_name} | target={target.first_name} | время={label}")
    await send_owner_log(
        context.bot,
        f"🔇 <b>МУТ НА ВРЕМЯ</b>\n👮 Админ: {update.message.from_user.first_name}\n👤 Цель: {mention} (ID: <code>{target.id}</code>)\n⏱ Время: {label}\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(f"🔇 {mention} замучен на <b>{label}</b>.", parse_mode="HTML")

async def cmd_clearwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы сбросить нарушения.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    uid = str(target.id)
    if uid in stats:
        stats[uid]["violations"] = 0
    if uid in user_info:
        user_info[uid]["violations"] = 0
    save_data()
    log("СБРОС НАРУШЕНИЙ", f"admin={update.message.from_user.first_name} | target={target.first_name} ({uid})")
    await update.message.reply_text(f"✅ Нарушения пользователя <b>{target.first_name}</b> сброшены.", parse_mode="HTML")

# ── Статистика и топ ──────────────────────────────────────────────────────────
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Всего нарушений поймано ботом: <b>{total_violations}</b>", parse_mode="HTML")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Нарушений пока не было.")
        return
    sorted_users = sorted(stats.items(), key=lambda x: x[1]["violations"], reverse=True)[:5]
    text = "🏆 <b>Топ нарушителей:</b>\n\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        text += f"{i}. {data['name']} — <b>{data['violations']}</b> нарушений\n"
    await update.message.reply_text(text, parse_mode="HTML")

# ── Информация о пользователе ─────────────────────────────────────────────────
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение чтобы пожаловаться.")
        return
    reporter = update.message.from_user
    target = update.message.reply_to_message.from_user
    reported_text = update.message.reply_to_message.text or "[медиа]"
    log("ЖАЛОБА", f"от={reporter.first_name} | на={target.first_name} | текст={reported_text[:80]}")
    await send_owner_log(
        context.bot,
        f"🚨 <b>ЖАЛОБА</b>\n👤 От: {reporter.first_name} (ID: <code>{reporter.id}</code>)\n👤 На: {target.first_name} (ID: <code>{target.id}</code>)\n💬 Сообщение: <i>{reported_text[:300]}</i>\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text("✅ Жалоба отправлена владельцу. Спасибо!")
    
async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user
    uid = str(target.id)
    info = user_info.get(uid, {})
    viol = stats.get(uid, {}).get("violations", 0)
    joined = info.get("joined", "неизвестно")
    username = f"@{info.get('username')}" if info.get("username") else "нет"
    await update.message.reply_text(
        f"👤 <b>Информация о пользователе</b>\n\n🔹 Имя: {target.first_name}\n🔹 Username: {username}\n🔹 ID: <code>{target.id}</code>\n🔹 Вступил: {joined}\n🔹 Мутов/нарушений: <b>{viol}</b>",
        parse_mode="HTML",
    )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text(f"🆔 Твой Telegram ID: <code>{user.id}</code>", parse_mode="HTML")

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Правила группы:</b>\n\n✅ Маты — разрешены\n❌ Оскорбления участников — запрещены\n❌ Спам и флуд — запрещены\n❌ Реклама без разрешения — запрещена\n\n⚠️ За нарушения: мут → бан\n👮 Решение админов — окончательное.",
        parse_mode="HTML",
    )

async def cmd_chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.message.chat
    try:
        count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        count = "?"
    chat_type = {"group": "Группа", "supergroup": "Супергруппа", "channel": "Канал"}.get(chat.type, chat.type)
    username = f"@{chat.username}" if chat.username else "нет"
    lock_status = "🔒 Закрыт" if chat_locked else "🔓 Открыт"
    await update.message.reply_text(
        f"💬 <b>Информация о чате</b>\n\n🔹 Название: {chat.title}\n🔹 Тип: {chat_type}\n🔹 ID: <code>{chat.id}</code>\n🔹 Username: {username}\n🔹 Участников: <b>{count}</b>\n🔹 Статус: {lock_status}",
        parse_mode="HTML",
    )

# ── Активности ────────────────────────────────────────────────────────────────
async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.randint(1, 6)
    await update.message.reply_text(f"🎲 {update.message.from_user.first_name} бросил кубик: <b>{result}</b>", parse_mode="HTML")

async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(["🦅 Орёл", "🪙 Решка"])
    await update.message.reply_text(f"{update.message.from_user.first_name} подбросил монету: <b>{result}</b>", parse_mode="HTML")

async def cmd_8ball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answers = [
        "🟢 Однозначно да!", "🟢 Без сомнений!", "🟢 Скорее всего да.",
        "🟢 Всё указывает на это.", "🟢 Можешь рассчитывать на это.",
        "🟡 Спроси снова.", "🟡 Лучше не говорить сейчас.", "🟡 Сложно сказать.",
        "🔴 Не рассчитывай на это.", "🔴 Мой ответ — нет.", "🔴 Всё указывает на нет.",
        "🔴 Очень сомнительно.", "🔴 Перспективы не очень.",
    ]
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text("🎱 Задай вопрос: <b>/8ball твой вопрос</b>", parse_mode="HTML")
        return
    await update.message.reply_text(f"🎱 <b>Вопрос:</b> {question}\n\n<b>Ответ:</b> {random.choice(answers)}", parse_mode="HTML")

async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user
    score = random.randint(1, 10)
    bars = "█" * score + "░" * (10 - score)
    emoji = "🌟" if score >= 8 else "😐" if score >= 5 else "💀"
    await update.message.reply_text(f"{emoji} <b>Оценка для {target.first_name}:</b>\n\n[{bars}] <b>{score}/10</b>", parse_mode="HTML")

async def cmd_casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    slots = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
    result = [random.choice(slots) for _ in range(3)]
    line = " | ".join(result)
    if result[0] == result[1] == result[2]:
        verdict = "🎉 <b>ДЖЕКПОТ! Три одинаковых!</b>"
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        verdict = "✨ <b>Два одинаковых — почти!</b>"
    else:
        verdict = "😢 <b>Не повезло, попробуй снова!</b>"
    await update.message.reply_text(f"🎰 <b>Казино</b>\n\n[ {line} ]\n\n{verdict}", parse_mode="HTML")

async def cmd_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    challenger = update.message.from_user
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы вызвать на дуэль.")
        return
    opponent = update.message.reply_to_message.from_user
    if opponent.id == challenger.id:
        await update.message.reply_text("🤦 Нельзя вызвать на дуэль самого себя!")
        return
    if opponent.is_bot:
        await update.message.reply_text("🤖 Нельзя вызвать на дуэль бота!")
        return
    winner = random.choice([challenger, opponent])
    loser = opponent if winner.id == challenger.id else challenger
    mention_w = f'<a href="tg://user?id={winner.id}">{winner.first_name}</a>'
    mention_l = f'<a href="tg://user?id={loser.id}">{loser.first_name}</a>'
    phrases = [
        f"🔫 Дуэль! {mention_w} выстрелил первым и победил {mention_l}!",
        f"⚔️ Дуэль! {mention_w} оказался быстрее и уложил {mention_l}!",
        f"🏆 Дуэль завершена! {mention_w} одержал победу над {mention_l}!",
        f"💥 {mention_l} даже не успел достать оружие — {mention_w} уже победил!",
        f"🎯 Меткий выстрел! {mention_w} побеждает {mention_l}!",
    ]
    await update.message.reply_text(random.choice(phrases), parse_mode="HTML")
    
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    day_name = days_ru[now.weekday()]
    date_str = f"{now.day} {months_ru[now.month - 1]} {now.year}"
    time_str = now.strftime("%H:%M")
    facts = [
        "🌍 Каждый день на Земле происходит около 100 молний в секунду.",
        "🧠 Мозг человека содержит около 86 миллиардов нейронов.",
        "🐝 Пчела посещает около 2000 цветов в день.",
        "🌊 Тихий океан больше всех континентов вместе взятых.",
        "🦋 Бабочки ощущают вкус ногами.",
        "🐬 Дельфины спят с одним открытым глазом.",
        "🍯 Мёд никогда не портится — его находили в египетских пирамидах.",
        "🐙 У осьминога три сердца и голубая кровь.",
    ]
    await update.message.reply_text(f"📅 <b>Сегодня:</b> {day_name}, {date_str}\n🕐 <b>Время:</b> {time_str}\n\n<b>Факт дня:</b> {random.choice(facts)}", parse_mode="HTML")

ANEKDOTS = [
    "— Доктор, я умру?\n— Обязательно. Мы все умрём.\n— Но мне страшно!\n— Ничего, я тоже боюсь.",
    "Программист зашёл в магазин. Жена попросила: «Купи хлеб, и если будут яйца — возьми десяток».\nОн купил десять батонов.",
    "Оптимист говорит: стакан наполовину полон.\nПессимист говорит: стакан наполовину пуст.\nИнженер говорит: стакан в два раза больше, чем нужно.",
]

async def cmd_anekdot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😂 <b>Анекдот:</b>\n\n{random.choice(ANEKDOTS)}", parse_mode="HTML")

# ── Помощь ────────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Список всех команд:</b>\n\n"
        "🎮 <b>Мафия:</b>\n"
        "/mafia — создать игру в группе\n\n"
        "👮 <b>Модерация (только админы):</b>\n"
        "/mute — замутить пользователя (15 сек)\n"
        "/mute_time 10m|1h|1d — мут на время\n"
        "/unmute — размутить пользователя\n"
        "/ban — забанить пользователя\n"
        "/kick — кикнуть пользователя\n"
        "/clearwarns — сбросить нарушения\n\n"
        "🔒 <b>Только владелец:</b>\n"
        "/off — выключить/включить весь бот\n"
        "/bot — выключить/включить модерацию\n"
        "/lock — заглушить/открыть весь чат\n"
        "/logs — последние 30 событий\n\n"
        "📊 <b>Статистика:</b>\n"
        "/stats — всего нарушений\n"
        "/top — топ нарушителей\n\n"
        "ℹ️ <b>Информация:</b>\n"
        "/report — пожаловаться владельцу\n"
        "/info — инфо о пользователе\n"
        "/id — твой Telegram ID\n"
        "/chatinfo — инфо о группе\n"
        "/rules — правила группы\n\n"
        "🎮 <b>Активности:</b>\n"
        "/roll — бросить кубик 🎲\n"
        "/flip — орёл или решка 🪙\n"
        "/8ball — шар предсказаний 🎱\n"
        "/rate — оценить пользователя ⭐\n"
        "/casino — однорукий бандит 🎰\n"
        "/duel — дуэль ⚔️\n"
        "/anekdot — анекдот 😂\n"
        "/today — дата дня 📅",
        parse_mode="HTML",
    )

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        return
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("📭 Лог-файл пуст.")
        return
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    last = "".join(lines[-30:])
    await update.message.reply_text(f"📋 <b>Последние события:</b>\n\n<pre>{last}</pre>", parse_mode="HTML")

# ==============================================================================
# ================================= МАФИЯ =====================================
# ==============================================================================

async def mafia_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❌ Запускать мафию можно только в группе.")
        return

    if chat_id in mafia_games:
        await update.message.reply_text("❌ В этом чате уже идёт или регистрируется игра.")
        return

    mafia_games[chat_id] = {
        "owner": update.effective_user.id,
        "players": {
            update.effective_user.id: update.effective_user.first_name
        },
        "started": False,
        "message_id": None,
        "roles": {},
        "alive": [],
        "phase": "lobby",
        "night_actions": {"kill": None, "heal": None},
        "votes": {}
    }

    keyboard = [
        [
            InlineKeyboardButton("➕ Присоединиться", callback_data="mafia_join"),
            InlineKeyboardButton("➖ Выйти", callback_data="mafia_leave")
        ],
        [InlineKeyboardButton("▶ Начать", callback_data="mafia_start")],
        [InlineKeyboardButton("❌ Отменить", callback_data="mafia_cancel")]
    ]

    text = (
        "🎭 <b>Регистрация в игру Мафия!</b>\n\n"
        f"Игроков: 1/{MAX_PLAYERS}\n"
        f"Минимум: {MIN_PLAYERS}\n\n"
        "<i>Игроки, обязательно нажмите /start в ЛС с ботом, чтобы он смог выдать вам роль!</i>"
    )

    msg = await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    mafia_games[chat_id]["message_id"] = msg.message_id


async def mafia_send_roles(context, chat_id):
    game = mafia_games[chat_id]
    players = list(game["players"].items())
    random.shuffle(players)
    count = len(players)

    # Динамическое распределение ролей в зависимости от количества участников
    if count <= 5:
        mafia_count = 1
    elif count <= 8:
        mafia_count = 2
    else:
        mafia_count = 3

    roles_pool = ["mafia"] * mafia_count + ["doctor"]
    while len(roles_pool) < count:
        roles_pool.append("civilian")
    random.shuffle(roles_pool)

    game["roles"] = {}
    game["alive"] = []

    for (uid, name), role in zip(players, roles_pool):
        game["roles"][uid] = role
        game["alive"].append(uid)

        try:
            if role == "mafia":
                text = "🔪 <b>Ты Глава мафии!</b>\n\nНочью твоя задача уничтожать мирных жителей. Жди наступления ночи, бот пришлет тебе кнопки."
            elif role == "doctor":
                text = "❤️ <b>Ты Доктор!</b>\n\nКаждую ночь ты можешь спасти одного человека (включая себя). Жди наступления ночи, бот пришлет кнопки."
            else:
                text = "👤 <b>Ты Мирный житель!</b>\n\nТвоя задача — вычислить мафию на дневном обсуждении и проголосовать против неё."

            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Ошибка! Игрок <b>{name}</b> не запустил бота в личных сообщениях.\nИгра отменена. Все игроки должны нажать /start у бота в ЛС!"
            )
            del mafia_games[chat_id]
            return False
    return True


async def start_night(context, chat_id):
    game = mafia_games.get(chat_id)
    if not game:
        return
    game["phase"] = "night"
    game["night_actions"] = {"kill": None, "heal": None}

    await context.bot.send_message(
        chat_id=chat_id,
        text="🌃 <b>Наступила ночь... Город засыпает.</b>\n\nМафия и Доктор делают свой выбор в личных сообщениях с ботом. Проверьте ЛС!",
        parse_mode="HTML"
    )

    # Рассылка кнопок действий в ЛС
    for uid in game["alive"]:
        role = game["roles"][uid]
        
        # Создаем список кнопок живых игроков для выбора
        keyboard = []
        for target_uid in game["alive"]:
            target_name = game["players"][target_uid]
            if role == "mafia" and target_uid == uid:
                continue  # Мафия обычно не убивает себя сама
            
            prefix = "mafia_pm_kill" if role == "mafia" else "mafia_pm_heal"
            keyboard.append([InlineKeyboardButton(target_name, callback_data=f"{prefix}:{target_uid}")])

        try:
            if role == "mafia":
                await context.bot.send_message(
                    chat_id=uid,
                    text="🔪 <b>Кого вы хотите убить этой ночью?</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
            elif role == "doctor":
                await context.bot.send_message(
                    chat_id=uid,
                    text="❤️ <b>Кого вы хотите вылечить этой ночью?</b>",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
            elif role == "civilian":
                await context.bot.send_message(
                    chat_id=uid,
                    text="👤 Вы мирный житель. Сейчас ночь, вы крепко спите и ждете утра...",
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"[ОШИБКА МАФИИ] Не удалось отправить ночной выбор в ЛС {uid}: {e}")

    await check_night_end(context, chat_id)


async def check_night_end(context, chat_id):
    game = mafia_games.get(chat_id)
    if not game or game["phase"] != "night":
        return

    mafia_alive = any(game["roles"][uid] == "mafia" for uid in game["alive"])
    doctor_alive = any(game["roles"][uid] == "doctor" for uid in game["alive"])

    mafia_acted = game["night_actions"]["kill"] is not None or not mafia_alive
    doctor_acted = game["night_actions"]["heal"] is not None or not doctor_alive

    if mafia_acted and doctor_acted:
        await start_day(context, chat_id)


async def start_day(context, chat_id):
    game = mafia_games.get(chat_id)
    if not game:
        return
    game["phase"] = "day"
    game["votes"] = {}

    kill_id = game["night_actions"]["kill"]
    heal_id = game["night_actions"]["heal"]

    text = "🌅 <b>Наступило утро! Город просыпается...</b>\n\n"

    if kill_id and kill_id != heal_id:
        victim_name = game["players"].get(kill_id, "Кто-то")
        role_ru = {"mafia": "Мафия", "doctor": "Доктор", "civilian": "Мирный житель"}.get(game["roles"][kill_id])
        text += f"💀 Ночью мафия коварно убила игрока: <b>{victim_name}</b>. Он был: <i>{role_ru}</i>.\n"
        if kill_id in game["alive"]:
            game["alive"].remove(kill_id)
    elif kill_id and kill_id == heal_id:
        victim_name = game["players"].get(kill_id, "Кто-то")
        text += f"❤️ Ночью мафия совершила нападение, но <b>Доктор успел спасти {victim_name}</b>! Никто не погиб.\n"
    else:
        text += "🕊 Ночь прошла совершенно спокойно, жертв нет.\n"

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    if await check_game_over(context, chat_id):
        return

    # Запуск дневного голосования в группе
    voting_text = "⚖️ <b>Время дневного голосования!</b>\n\nОбсудите, кто по вашему мнению мафия, и отдайте свой голос, нажав кнопку под сообщением:"
    keyboard = []
    for uid in game["alive"]:
        name = game["players"][uid]
        keyboard.append([InlineKeyboardButton(f"Голосовать против {name}", callback_data=f"mafia_vote:{uid}")])

    await context.bot.send_message(
        chat_id=chat_id,
        text=voting_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def check_game_over(context, chat_id):
    game = mafia_games.get(chat_id)
    if not game:
        return True

    mafia_count = sum(1 for uid in game["alive"] if game["roles"][uid] == "mafia")
    civilian_count = sum(1 for uid in game["alive"] if game["roles"][uid] != "mafia")

    if mafia_count == 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 <b>Мирные жители победили!</b>\nВся преступность и мафия полностью искоренены из города.",
            parse_mode="HTML"
        )
        del mafia_games[chat_id]
        return True
    elif mafia_count >= civilian_count:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔪 <b>Мафия победила!</b>\nПреступники захватили контроль над городом, мирных жителей больше некому защищать.",
            parse_mode="HTML"
        )
        del mafia_games[chat_id]
        return True

    return False


async def mafia_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    name = query.from_user.first_name
    data = query.data

    # Обработка выбора ролей в ЛС
    if data.startswith("mafia_pm_"):
        chat_id = None
        for cid, g in mafia_games.items():
            if uid in g.get("alive", []):
                chat_id = cid
                break

        if not chat_id:
            await query.edit_message_text("❌ Вы не участвуете в активной игре или вас уже убили.")
            return

        game = mafia_games[chat_id]
        target_id = int(data.split(":")[1])
        target_name = game["players"].get(target_id, "Неизвестный")

        if data.startswith("mafia_pm_kill:"):
            game["night_actions"]["kill"] = target_id
            await query.edit_message_text(f"👌 Выбор принят. Ваша цель на уничтожение: <b>{target_name}</b>.", parse_mode="HTML")
        elif data.startswith("mafia_pm_heal:"):
            game["night_actions"]["heal"] = target_id
            await query.edit_message_text(f"👌 Выбор принят. Этой ночью вы лечите: <b>{target_name}</b>.", parse_mode="HTML")

        await check_night_end(context, chat_id)
        return

    # Обработка дневного голосования в группе
    if data.startswith("mafia_vote:"):
        chat_id = query.message.chat.id
        if chat_id not in mafia_games:
            return
        game = mafia_games[chat_id]

        if uid not in game["alive"]:
            await query.answer("❌ Вы не участвуете в игре или мертвы!", show_alert=True)
            return

        if game["phase"] != "day":
            await query.answer("❌ Сейчас не фаза голосования!", show_alert=True)
            return

        target_id = int(data.split(":")[1])
        game["votes"][uid] = target_id
        await query.answer(f"Вы проголосовали против игрока {game['players'][target_id]}!")

        # Если проголосовали все выжившие участники
        if len(game["votes"]) >= len(game["alive"]):
            vote_counts = Counter(game["votes"].values())
            most_voted_id, _ = vote_counts.most_common(1)[0]

            executed_name = game["players"][most_voted_id]
            role_ru = {"mafia": "Мафия", "doctor": "Доктор", "civilian": "Мирный житель"}.get(game["roles"][most_voted_id])

            game["alive"].remove(most_voted_id)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚖️ <b>Голосование завершено!</b>\n\nБольшинство жителей проголосовало против: <b>{executed_name}</b>. Он отправляется на виселицу!\nЕго роль была: <i>{role_ru}</i>.",
                parse_mode="HTML"
            )

            if await check_game_over(context, chat_id):
                return

            # Наступает следующая ночь
            await start_night(context, chat_id)
        return

    # Логика регистрации в группе (лобби)
    chat_id = query.message.chat.id
    if chat_id not in mafia_games:
        return
    game = mafia_games[chat_id]

    if data == "mafia_join":
        if uid in game["players"]:
            return
        if len(game["players"]) >= MAX_PLAYERS:
            await query.answer("Лобби заполнено.", show_alert=True)
            return
        game["players"][uid] = name

    elif data == "mafia_leave":
        if uid not in game["players"]:
            return
        if uid == game["owner"]:
            await query.answer("Создатель не может выйти. Отмените игру кнопкой.", show_alert=True)
            return
        del game["players"][uid]

    elif data == "mafia_cancel":
        if uid != game["owner"]:
            await query.answer("Только создатель лобби может отменить игру.", show_alert=True)
            return
        del mafia_games[chat_id]
        await query.edit_message_text("❌ Игра отменена создателем.")
        return

    elif data == "mafia_start":
        if uid != game["owner"]:
            await query.answer("Только создатель лобби может запустить игру.", show_alert=True)
            return
        if len(game["players"]) < MIN_PLAYERS:
            await query.answer(f"Необходимо как минимум {MIN_PLAYERS} игрока для старта.", show_alert=True)
            return

        game["started"] = True
        players_list = "\n".join(f"• {p}" for p in game["players"].values())
        
        await query.edit_message_text(
            f"🎭 <b>Игра началась!</b>\n\nВсего игроков: {len(game['players'])}\n\n<b>Список участников:</b>\n{players_list}\n\n🎲 <i>Раздаю роли в ЛС...</i>",
            parse_mode="HTML"
        )

        success = await mafia_send_roles(context, chat_id)
        if success:
            await start_night(context, chat_id)
        return

    # Обновление текста лобби при входе/выходе игроков
    players_list = "\n".join(f"• {p}" for p in game["players"].values())
    keyboard = [
        [
            InlineKeyboardButton("➕ Присоединиться", callback_data="mafia_join"),
            InlineKeyboardButton("➖ Выйти", callback_data="mafia_leave")
        ],
        [InlineKeyboardButton("▶ Начать", callback_data="mafia_start")],
        [InlineKeyboardButton("❌ Отменить", callback_data="mafia_cancel")]
    ]

    await query.edit_message_text(
        f"🎭 <b>Мафия</b>\n\nИгроков: {len(game['players'])}/{MAX_PLAYERS}\nМинимум: {MIN_PLAYERS}\n\n<b>Список игроков:</b>\n{players_list}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ── Основная функция ─────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики Мафии
    app.add_handler(CommandHandler("mafia", mafia_create))
    app.add_handler(CallbackQueryHandler(mafia_buttons, pattern="^mafia_"))
    
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

    # Статистика
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("logs", cmd_logs))

    # Информация
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("chatinfo", cmd_chatinfo))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("help", cmd_help))

    # Активности
    app.add_handler(CommandHandler("roll", cmd_roll))
    app.add_handler(CommandHandler("flip", cmd_flip))
    app.add_handler(CommandHandler("8ball", cmd_8ball))
    app.add_handler(CommandHandler("rate", cmd_rate))
    app.add_handler(CommandHandler("casino", cmd_casino))
    app.add_handler(CommandHandler("duel", cmd_duel))
    app.add_handler(CommandHandler("anekdot", cmd_anekdot))
    app.add_handler(CommandHandler("today", cmd_today))

    # Сообщения
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log("ЗАПУСК", "Бот запущен")
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
