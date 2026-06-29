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
    ApplicationHandlerStop,
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
locked_chats = set()              # chat_id групп с заглушкой
saved_chat_permissions = {}       # сохранённые права перед заглушкой

OPEN_CHAT_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)

LOCKED_CHAT_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

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

async def enforce_chat_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Блокирует любые сообщения в заглушённом чате, кроме владельца бота."""
    message = update.message
    if not message or message.chat.type not in ("group", "supergroup"):
        return
    if message.chat_id not in locked_chats:
        return
    user = message.from_user
    if user and user.id == OWNER_ID:
        return
    try:
        await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception:
        pass
    raise ApplicationHandlerStop

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
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return

    chat_id = update.message.chat_id
    if update.message.chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❌ Команда работает только в группах.")
        return

    if chat_id in locked_chats:
        locked_chats.discard(chat_id)
        restore_permissions = saved_chat_permissions.pop(chat_id, OPEN_CHAT_PERMISSIONS)
        try:
            await context.bot.set_chat_permissions(chat_id=chat_id, permissions=restore_permissions)
        except Exception as e:
            print(f"[ОШИБКА] Открытие чата: {e}")
        log("ЧАТ ОТКРЫТ", f"chat_id={chat_id} | владелец={update.message.from_user.first_name}")
        await update.message.reply_text("🔓 <b>Чат открыт!</b>\nВсе участники снова могут писать.", parse_mode="HTML")
        return

    try:
        chat = await context.bot.get_chat(chat_id)
        if chat.permissions:
            saved_chat_permissions[chat_id] = chat.permissions
    except Exception:
        pass

    locked_chats.add(chat_id)
    try:
        await context.bot.set_chat_permissions(chat_id=chat_id, permissions=LOCKED_CHAT_PERMISSIONS)
    except Exception as e:
        locked_chats.discard(chat_id)
        print(f"[ОШИБКА] Заглушка чата: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось заглушить чат. Дай боту права администратора с «Ограничение участников»."
        )
        return

    log("ЧАТ ЗАКРЫТ", f"chat_id={chat_id} | владелец={update.message.from_user.first_name}")
    await update.message.reply_text(
        "🔒 <b>Чат заглушён!</b>\n"
        "Участники не могут писать. Только владелец бота может отправлять сообщения.\n"
        "Используй /lock ещё раз, чтобы открыть чат.",
        parse_mode="HTML",
    )

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
        "📖 <b>Список всех команд:</b>\n"
        "👮 <b>Админы:</b> /mute, /mute_time, /unmute, /ban, /kick, /clearwarns\n"
        "🎮 <b>Мини-игры:</b> /roll, /flip, /8ball, /rate, /casino, /duel, /anekdot, /today"
    )

# ── Главная функция ───────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
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

    # Заглушка чата — перехват до всех остальных обработчиков
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, enforce_chat_lock), group=-1)

    # Текстовые сообщения и вступления
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log("ЗАПУСК", "Бот запущен")
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
