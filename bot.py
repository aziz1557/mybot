import re
import asyncio
import json
import os
import random
import aiohttp
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5742325054
WEATHER_API_KEY = "d7b634d924dc8c54a5b3eeeeb23a2cfc"
bot_enabled = True
chat_locked = False  # Заглушка чата

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

    # Заглушка чата — только владелец может писать
    if chat_locked and user.id != OWNER_ID:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception:
            pass
        return

    # Обновляем инфо о пользователе
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

    # Антиспам
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

    # Фильтр оскорблений
    if not contains_insult(text):
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
    global bot_enabled
    if update.message.from_user.id != OWNER_ID:
        return
    bot_enabled = not bot_enabled
    status = "✅ Бот включён — модерация активна." if bot_enabled else "❌ Бот выключен — модерация остановлена."
    log("ПЕРЕКЛЮЧЕНИЕ", f"bot_enabled={bot_enabled}")
    await update.message.reply_text(status)

async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global chat_locked
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return
    chat_locked = not chat_locked
    if chat_locked:
        log("ЧАТ ЗАКРЫТ", f"владелец={update.message.from_user.first_name}")
        await update.message.reply_text(
            "🔒 <b>Чат заглушён!</b>\n"
            "Только владелец может писать сообщения.\n"
            "Используй /lock снова чтобы открыть чат.",
            parse_mode="HTML",
        )
    else:
        log("ЧАТ ОТКРЫТ", f"владелец={update.message.from_user.first_name}")
        await update.message.reply_text(
            "🔓 <b>Чат открыт!</b>\n"
            "Все участники снова могут писать.",
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
        f"🔇 <b>МУТ (АДМИН)</b>\n"
        f"👮 Админ: {update.message.from_user.first_name}\n"
        f"👤 Цель: {mention} (ID: <code>{target.id}</code>)\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
        f"🚫 <b>БАН</b>\n"
        f"👮 Админ: {update.message.from_user.first_name}\n"
        f"👤 Цель: {mention} (ID: <code>{target.id}</code>)\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
        f"👢 <b>КИК</b>\n"
        f"👮 Админ: {update.message.from_user.first_name}\n"
        f"👤 Цель: {mention} (ID: <code>{target.id}</code>)\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
        f"🔇 <b>МУТ НА ВРЕМЯ</b>\n"
        f"👮 Админ: {update.message.from_user.first_name}\n"
        f"👤 Цель: {mention} (ID: <code>{target.id}</code>)\n"
        f"⏱ Время: {label}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(
        f"🔇 {mention} замучен на <b>{label}</b>.",
        parse_mode="HTML",
    )

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
        f"🚨 <b>ЖАЛОБА</b>\n"
        f"👤 От: {reporter.first_name} (ID: <code>{reporter.id}</code>)\n"
        f"👤 На: {target.first_name} (ID: <code>{target.id}</code>)\n"
        f"💬 Сообщение: <i>{reported_text[:300]}</i>\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text("✅ Жалоба отправлена владельцу. Спасибо!")

# ── Статистика и топ ──────────────────────────────────────────────────────────
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Всего нарушений поймано ботом: <b>{total_violations}</b>",
        parse_mode="HTML",
    )

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
async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user
    uid = str(target.id)
    info = user_info.get(uid, {})
    viol = stats.get(uid, {}).get("violations", 0)
    joined = info.get("joined", "неизвестно")
    username = f"@{info.get('username')}" if info.get("username") else "нет"
    await update.message.reply_text(
        f"👤 <b>Информация о пользователе</b>\n\n"
        f"🔹 Имя: {target.first_name}\n"
        f"🔹 Username: {username}\n"
        f"🔹 ID: <code>{target.id}</code>\n"
        f"🔹 Вступил: {joined}\n"
        f"🔹 Мутов/нарушений: <b>{viol}</b>",
        parse_mode="HTML",
    )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text(
        f"🆔 Твой Telegram ID: <code>{user.id}</code>",
        parse_mode="HTML",
    )

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Правила группы:</b>\n\n"
        "✅ Маты — разрешены\n"
        "❌ Оскорбления участников — запрещены\n"
        "❌ Спам и флуд — запрещены\n"
        "❌ Реклама без разрешения — запрещена\n\n"
        "⚠️ За нарушения: мут → бан\n"
        "👮 Решение админов — окончательное.",
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
        f"💬 <b>Информация о чате</b>\n\n"
        f"🔹 Название: {chat.title}\n"
        f"🔹 Тип: {chat_type}\n"
        f"🔹 ID: <code>{chat.id}</code>\n"
        f"🔹 Username: {username}\n"
        f"🔹 Участников: <b>{count}</b>\n"
        f"🔹 Статус: {lock_status}",
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
        "🟡 Не уверен, попробуй позже.", "🟡 Спроси снова.", "🟡 Лучше не говорить сейчас.",
        "🟡 Сложно сказать.", "🟡 Сосредоточься и спроси снова.",
        "🔴 Не рассчитывай на это.", "🔴 Мой ответ — нет.", "🔴 Всё указывает на нет.",
        "🔴 Очень сомнительно.", "🔴 Перспективы не очень.",
    ]
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text("🎱 Задай вопрос: <b>/8ball твой вопрос</b>", parse_mode="HTML")
        return
    await update.message.reply_text(
        f"🎱 <b>Вопрос:</b> {question}\n\n<b>Ответ:</b> {random.choice(answers)}",
        parse_mode="HTML",
    )

async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.message.from_user
    score = random.randint(1, 10)
    bars = "█" * score + "░" * (10 - score)
    emoji = "🌟" if score >= 8 else "😐" if score >= 5 else "💀"
    await update.message.reply_text(
        f"{emoji} <b>Оценка для {target.first_name}:</b>\n\n"
        f"[{bars}] <b>{score}/10</b>",
        parse_mode="HTML",
    )

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
    await update.message.reply_text(
        f"🎰 <b>Казино</b>\n\n[ {line} ]\n\n{verdict}",
        parse_mode="HTML",
    )

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

QUOTES = [
    "💡 «Успех — это не конец, неудача — не смерть. Важна лишь смелость продолжать.» — У. Черчилль",
    "💡 «Единственный способ делать великую работу — любить то, что делаешь.» — С. Джобс",
    "💡 «Жизнь — это то, что происходит, пока ты строишь другие планы.» — Дж. Леннон",
    "💡 «Будь изменением, которое хочешь видеть в мире.» — М. Ганди",
    "💡 «Всё, что вы можете себе представить — реально.» — П. Пикассо",
    "💡 «Мечтай масштабно. Начинай с малого. Действуй сейчас.» — Р. Бренсон",
    "💡 «Твой самый недовольный клиент — твой лучший источник знаний.» — Б. Гейтс",
    "💡 «Успех — плохой учитель. Он соблазняет умных людей думать, что они не могут проиграть.» — Б. Гейтс",
    "💡 «В середине каждой трудности лежит возможность.» — А. Эйнштейн",
    "💡 «Человек, который никогда не ошибался, никогда не пробовал ничего нового.» — А. Эйнштейн",
    "💡 «Будущее принадлежит тем, кто верит в красоту своих мечтаний.» — Э. Рузвельт",
    "💡 «Не важно, как медленно ты идёшь, главное — не останавливаться.» — Конфуций",
    "💡 «Падай семь раз — вставай восемь.» — Японская пословица",
    "💡 «Жизнь измеряется не количеством вдохов, а моментами, которые захватывают дух.» — М. Анджелоу",
    "💡 «Если ты хочешь идти быстро — иди один. Если хочешь идти далеко — идите вместе.» — Африканская пословица",
]

MEMES = [
    "😂 Когда починил баг в 3 ночи и сам не понимаешь как:\n*танцует в темноте*",
    "😂 Понедельник: я буду продуктивным всю неделю!\nПятница: *смотрит в потолок уже 4 часа*",
    "😂 Я: посплю 5 минут\nЯ через 3 часа: кто я? где я? какой год?",
    "😂 Программист открывает холодильник:\n— Null pointer exception: еда не найдена",
    "😂 Когда написал 200 строк кода и забыл сохранить:\n*стадии принятия горя*",
    "😂 Мозг в 2 часа ночи: а помнишь как ты облажался в 2015 году?",
    "😂 Я в магазине: возьму только хлеб\nЯ на кассе: *2 пакета вещей, которых не планировал*",
    "😂 Кот в 3 ночи: БЕГИ\nКот в 3 дня: не трогай меня, я сплю",
    "😂 Диета: день 1 — начинается!\nДиета: день 1 вечер — уже закончилась",
    "😂 Когда говоришь 'я скоро' и проходит 3 часа:\n*время — иллюзия*",
    "😂 Wi-Fi у соседей сильнее чем моя воля к жизни",
    "😂 Встреча в 9 утра:\nОрганизатор: все бодрые?\nВсе: *зомби с кофе*",
    "😂 Я: завтра точно встану в 7!\nЯ в 7: отложить на 5 минут × 6 = проснулся в 10",
    "😂 Когда читаешь старый код и не понимаешь, кто это написал...\n*смотришь на дату* — это был я",
    "😂 Телефон: 1% заряда\nЯ: *пробегаю марафон до розетки*",
]

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(QUOTES), parse_mode="HTML")

async def cmd_mem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MEMES))

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                 "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    day_name = days_ru[now.weekday()]
    date_str = f"{now.day} {months_ru[now.month - 1]} {now.year}"
    time_str = now.strftime("%H:%M")
    facts = [
        "🌍 Каждый день на Земле происходит около 100 молний в секунду.",
        "🧠 Мозг человека содержит около 86 миллиардов нейронов.",
        "🐝 Пчела посещает около 2000 цветов в день.",
        "🌊 Тихий океан больше всех континентов вместе взятых.",
        "🦋 Бабочки ощущают вкус ногами.",
        "🎵 Музыка активирует те же зоны мозга, что и еда и секс.",
        "🐬 Дельфины спят с одним открытым глазом.",
        "🍯 Мёд никогда не портится — его находили в египетских пирамидах.",
        "🌙 На Луне нет ветра, поэтому следы астронавтов сохранятся миллионы лет.",
        "🐙 У осьминога три сердца и голубая кровь.",
    ]
    await update.message.reply_text(
        f"📅 <b>Сегодня:</b> {day_name}, {date_str}\n"
        f"🕐 <b>Время:</b> {time_str}\n\n"
        f"<b>Факт дня:</b> {random.choice(facts)}",
        parse_mode="HTML",
    )

async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🌤 Укажи город: <b>/погода Москва</b>", parse_mode="HTML")
        return
    city = " ".join(context.args)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await update.message.reply_text(f"❌ Город <b>{city}</b> не найден. Проверь название.", parse_mode="HTML")
                    return
                data = await resp.json()
        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        desc = data["weather"][0]["description"].capitalize()
        wind = data["wind"]["speed"]
        city_name = data["name"]
        country = data["sys"]["country"]

        # Иконка погоды
        weather_id = data["weather"][0]["id"]
        if weather_id < 300:
            icon = "⛈"
        elif weather_id < 400:
            icon = "🌧"
        elif weather_id < 600:
            icon = "🌧"
        elif weather_id < 700:
            icon = "❄️"
        elif weather_id < 800:
            icon = "🌫"
        elif weather_id == 800:
            icon = "☀️"
        elif weather_id < 803:
            icon = "🌤"
        else:
            icon = "☁️"

        await update.message.reply_text(
            f"{icon} <b>Погода в {city_name}, {country}</b>\n\n"
            f"🌡 Температура: <b>{temp:.1f}°C</b>\n"
            f"🤔 Ощущается как: <b>{feels:.1f}°C</b>\n"
            f"💧 Влажность: <b>{humidity}%</b>\n"
            f"💨 Ветер: <b>{wind} м/с</b>\n"
            f"📝 Описание: <b>{desc}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[ОШИБКА] Погода: {e}")
        await update.message.reply_text("❌ Не удалось получить данные о погоде. Попробуй позже.")

ANEKDOTS = [
    "— Доктор, я умру?\n— Обязательно. Мы все умрём.\n— Но мне страшно!\n— Ничего, я тоже боюсь.",
    "Программист зашёл в магазин. Жена попросила: «Купи хлеб, и если будут яйца — возьми десяток».\nОн купил десять батонов.",
    "— Ты умеешь хранить секреты?\n— Не знаю, мне их никогда не доверяли.",
    "Оптимист говорит: стакан наполовину полон.\nПессимист говорит: стакан наполовину пуст.\nИнженер говорит: стакан в два раза больше, чем нужно.",
    "— Сколько тебе лет?\n— Двадцать пять.\n— Ты так хорошо выглядишь!\n— Я знаю. Я так говорю уже десять лет.",
    "— Почему ты опоздал на работу?\n— Я шёл по улице и увидел знак «Стоп, школа».\n— И что?\n— Я остановился и подождал, пока она закончится.",
    "Муж звонит жене:\n— Дорогая, я выиграл в лотерею миллион! Собирай вещи!\n— Ура! Что взять, летнее или зимнее?\n— Всё равно, лишь бы к вечеру тебя дома не было.",
    "— Вовочка, почему ты принёс в школу кота?\n— Вы сами сказали: «Не забудьте дневник, а то съем!»",
    "Жена мужу:\n— Ты меня совсем не слушаешь!\n— Прости, что ты сказала?",
    "— Доктор, у меня проблемы с памятью.\n— Давно это началось?\n— Что началось?",
    "Начальник говорит сотруднику:\n— Вы опоздали на работу уже пятый раз за неделю. Что вы о себе думаете?\n— Что сегодня пятница!",
    "— Почему на свадьбах играет музыка?\n— Чтобы было не слышно плача родственников жениха.",
    "— Доктор, я слышу в ушах звон.\n— Не берите трубку.",
    "Стоматолог пациенту:\n— Открывайте шире!\n— Но я уже открыл рот до упора!\n— Я говорю про кошелёк.",
    "— Почему программисты путают Хэллоуин и Рождество?\n— Потому что 31 Oct == 25 Dec.",
]

async def cmd_anekdot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😂 <b>Анекдот:</b>\n\n{random.choice(ANEKDOTS)}", parse_mode="HTML")

# ── Помощь ────────────────────────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Список всех команд:</b>\n\n"
        "👮 <b>Модерация (только админы):</b>\n"
        "/mute — замутить пользователя (15 сек)\n"
        "/mute_time 10m|1h|1d — мут на время\n"
        "/unmute — размутить пользователя\n"
        "/ban — забанить пользователя\n"
        "/kick — кикнуть пользователя\n"
        "/clearwarns — сбросить нарушения\n"
        "/report — пожаловаться владельцу\n"
        "/bot — включить/выключить модерацию\n\n"
        "🔒 <b>Только владелец:</b>\n"
        "/lock — заглушить/открыть весь чат\n"
        "/logs — последние 30 событий\n\n"
        "📊 <b>Статистика:</b>\n"
        "/stats — всего нарушений\n"
        "/top — топ нарушителей\n\n"
        "ℹ️ <b>Информация:</b>\n"
        "/info — инфо о пользователе\n"
        "/id — твой Telegram ID\n"
        "/chatinfo — инфо о группе\n"
        "/rules — правила группы\n\n"
        "🎮 <b>Активности:</b>\n"
        "/roll — бросить кубик 🎲\n"
        "/flip — орёл или решка 🪙\n"
        "/8ball вопрос — шар предсказаний 🎱\n"
        "/rate — оценить пользователя ⭐\n"
        "/casino — однорукий бандит 🎰\n"
        "/duel — дуэль с пользователем ⚔️\n"
        "/anekdot — случайный анекдот 😂\n"
        "/цитата — мотивирующая цитата 💡\n"
        "/мем — случайный мем 😂\n"
        "/today — факт и дата дня 📅\n"
        "/погода Город — текущая погода 🌤",
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

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Модерация
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
    app.add_handler(CommandHandler("цитата", cmd_quote))
    app.add_handler(CommandHandler("мем", cmd_mem))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("погода", cmd_weather))

    # Сообщения
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log("ЗАПУСК", "Бот запущен")
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
