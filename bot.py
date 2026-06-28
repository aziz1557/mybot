import re
import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = "8422286281:AAFDqQ1xhPem2Bpc4D_b0I6aRF7zH0C1dFo"
OWNER_ID = 5742325054
bot_enabled = True

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
stats         = _data.get("stats", {})
total_violations = _data.get("total_violations", 0)
user_info     = _data.get("user_info", {})

# Антиспам (в памяти — не критично)
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

    # Антиспам — одно и то же сообщение 3 раза подряд
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


# ── Мут на время: /mute_time 10m / 1h / 1d ───────────────────────────────────
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

# ── Правила ───────────────────────────────────────────────────────────────────
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

# ── Активности ────────────────────────────────────────────────────────────────
async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.randint(1, 6)
    await update.message.reply_text(f"🎲 {update.message.from_user.first_name} бросил кубик: <b>{result}</b>", parse_mode="HTML")

async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(["🦅 Орёл", "🪙 Решка"])
    await update.message.reply_text(f"{update.message.from_user.first_name} подбросил монету: <b>{result}</b>", parse_mode="HTML")

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
    "— Как дела?\n— Нормально.\n— А подробнее?\n— Нормально, спасибо.",
    "Учитель:\n— Дети, кто может привести пример нервной системы?\n— Моя мама после родительского собрания!",
    "— Ты веришь в любовь с первого взгляда?\n— Нет, мне обычно нужно посмотреть в меню несколько раз.",
    "Программист и его жена:\n— Сходи в магазин, купи молоко. Если будут яйца — возьми десяток.\nПрограммист вернулся с десятью пакетами молока.",
    "— Доктор, у меня проблемы с памятью.\n— Давно это началось?\n— Что началось?",
    "Начальник говорит сотруднику:\n— Вы опоздали на работу уже пятый раз за неделю. Что вы о себе думаете?\n— Что сегодня пятница!",
    "— Папа, почему солнце встаёт на востоке?\n— Сынок, уже так заведено, не трогай.",
    "Мама говорит сыну:\n— Вася, иди спать!\n— Но мама, я не хочу!\n— Иди спать, говорю! Мне с папой поговорить надо.\n— Мама, я уже сплю!",
    "— Почему на свадьбах играет музыка?\n— Чтобы было не слышно плача родственников жениха.",
    "— Хочешь услышать анекдот про бумагу?\n— Да.\n— Он рвётся.",
    "Стоматолог пациенту:\n— Открывайте шире!\n— Но я уже открыл рот до упора!\n— Я говорю про кошелёк.",
    "— Почему программисты путают Хэллоуин и Рождество?\n— Потому что 31 Oct == 25 Dec.",
    "— Сынок, как прошёл день?\n— Нормально.\n— Что делал?\n— Ничего.\n— А вчера?\n— То же самое.\n— Вы с другом не устали делать одно и то же каждый день?\n— Мама, мы не успеваем!",
    "— Доктор, я слышу в ушах звон.\n— Не берите трубку.",
    "— Вы замужем?\n— Нет, просто устала.",
    "Учитель:\n— Петя, назови мне пять животных из Африки.\n— Три льва и два слона.",
    "— Мужик, ты чего в трёх шубах в такую жару?\n— Так в магазине написано: «Одевайтесь по сезону». Вот я и оделся по всем сезонам сразу.",
    "— Дорогой, ты меня любишь?\n— Да.\n— Докажи!\n— Я же здесь, а не где-то ещё.",
    "Кот залез на холодильник и смотрит вниз.\nХозяйка:\n— Что, жизнь с высоты кажется другой?\nКот:\n— Нет, просто сосиски на второй полке.",
    "— Дети, сегодня мы будем изучать дроби. Вася, сколько будет половина от восьми?\n— Сверху — ноль, снизу — три!\n— Это как?\n— Ну, если восьмёрку разрезать поперёк...",
    "— Алло, это скорая?\n— Да.\n— Приедете?\n— Да, а что случилось?\n— Ничего, просто спрашиваю.",
    "Муж жене:\n— Я читал, что мужчины принимают решения быстрее женщин.\n— Это неправда!\n— Видишь, ты уже согласна.",
    "— Вовочка, ты почему смеёшься на уроке?\n— Я не смеялся.\n— А что ты делал?\n— Улыбался изнутри.",
    "Диетолог пациенту:\n— Вам нужно исключить жирное, жареное, сладкое и мучное.\n— А что тогда есть?\n— Вы задаёте очень правильный вопрос.",
    "— Как называется страх перед длинными словами?\n— Гиппопотомомонстросесквиппедалиофобия.\n— Это издевательство.",
    "Сын спрашивает отца:\n— Пап, а что такое политика?\n— Смотри: я зарабатываю деньги — значит, я капитализм. Мама распределяет — она правительство. Бабушка следит за порядком — она закон. Ты хочешь всего — ты народ. А младший братик в памперсах — будущее.\nНочью сын просыпается от плача брата, заходит к родителям — они спят.\nУтром говорит отцу:\n— Пап, я понял политику. Пока капитализм и правительство отдыхают, закон спит, народ игнорируют, а будущее лежит в дерьме.",
    "— Доктор, у меня две проблемы: ожирение и забывчивость.\n— Давайте начнём со второй. Напомните, в чём ваша первая проблема?",
    "Жена мужу:\n— Дорогой, я разбила твою любимую чашку.\n— Ту, что мне подарила мама?!\n— Нет, ту, которую ты привёз из Японии.\n— Уф, слава богу. Подожди... что?!",
    "— Я такой невезучий! Вчера купил словарь, а половины слов там нет!\n— Каких слов?\n— Ну, вот например: «блиииин», «аааа», «йооо»...",
    "Учитель:\n— Маша, твоё сочинение про кошку слово в слово совпадает с сочинением Пети!\n— Так у нас одна кошка на двоих.",
    "— Почему ты такой грустный?\n— Вчера потерял кошелёк.\n— Много денег было?\n— Нет, но я так долго его искал...",
    "Мужик приходит к врачу:\n— Доктор, у меня болит всё. Покажу — голова болит, нога болит, живот болит...\nВрач:\n— У вас сломан палец.",
    "— Вы не подскажете, который час?\n— Без пятнадцати три.\n— Спасибо.\n— Пожалуйста.\n— ...Ладно, давайте познакомимся.",
    "— Сынок, ты уроки сделал?\n— Пап, я программист. У меня нет уроков, у меня задачи.",
    "Жена:\n— Ты меня слышишь?!\nМуж:\n— Не только слышу, но уже и вижу.",
    "— Как вы относитесь к алкоголю?\n— С уважением. Он старше меня.",
    "— Дорогой, у меня хорошая и плохая новость.\n— Говори хорошую.\n— Подушки безопасности работают.",
]

async def cmd_anekdot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😂 <b>Анекдот:</b>\n\n{random.choice(ANEKDOTS)}", parse_mode="HTML")

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

async def cmd_chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.message.chat
    try:
        count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        count = "?"
    chat_type = {"group": "Группа", "supergroup": "Супергруппа", "channel": "Канал"}.get(chat.type, chat.type)
    username = f"@{chat.username}" if chat.username else "нет"
    await update.message.reply_text(
        f"💬 <b>Информация о чате</b>\n\n"
        f"🔹 Название: {chat.title}\n"
        f"🔹 Тип: {chat_type}\n"
        f"🔹 ID: <code>{chat.id}</code>\n"
        f"🔹 Username: {username}\n"
        f"🔹 Участников: <b>{count}</b>",
        parse_mode="HTML",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Список всех команд:</b>\n\n"
        "👮 <b>Модерация (только админы):</b>\n"
        "/mute — замутить пользователя (15 сек)\n"
        "/mute_time 10m|1h|1d — мут на время\n"
        "/unmute — размутить пользователя\n"
        "/ban — забанить пользователя\n"
        "/kick — кикнуть пользователя\n"
        "/bot — включить/выключить модерацию\n\n"
        "📊 <b>Статистика:</b>\n"
        "/stats — всего нарушений\n"
        "/top — топ нарушителей\n"
        "/logs — последние события (владелец)\n\n"
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
        "/anekdot — случайный анекдот 😂",
        parse_mode="HTML",
    )

# ── Просмотр логов (только владелец) ─────────────────────────────────────────
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
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("mute_time", cmd_mute_time))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("kick", cmd_kick))

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
    app.add_handler(CommandHandler("anekdot", cmd_anekdot))

    # Сообщения
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log("ЗАПУСК", "Бот запущен")
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
