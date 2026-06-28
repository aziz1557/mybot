import re
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes, ChatMemberHandler

BOT_TOKEN = "8422286281:AAFDqQ1xhPem2Bpc4D_b0I6aRF7zH0C1dFo"
OWNER_ID = 123456789  # замени на свой Telegram ID
bot_enabled = True

# ── Статистика ────────────────────────────────────────────────────────────────
stats = defaultdict(lambda: {"violations": 0, "name": ""})
total_violations = 0

# ── Антифлуд ──────────────────────────────────────────────────────────────────
user_messages = defaultdict(list)   # {user_id: [timestamps]}
user_last_msg = defaultdict(str)    # {user_id: last_message}
user_repeat = defaultdict(int)      # {user_id: repeat_count}

# ── Предупреждения ────────────────────────────────────────────────────────────
warnings = defaultdict(int)         # {user_id: count}
WARN_LIMIT = 3

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
    r"т[уy][пп][оo0][йеея]", r"[уу]р[оo0]д", r"[уу]б[лл][юу]д[оo0]к",
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
    r"[хx][уy][иiй]\s*[тt][её][бb][её]",
    r"[хx][уy][иiй]\s*[тt][её][бb][яa]",
    r"[хx][уy][иiй]\s*[тt][яy]",
    r"[хx][уy][иiй]\s*[вv][аa][мm]",
    r"[хx][уy][иiй]\s*[тt][её][бb][её]\s*в\s*р[оo][тt]",
    r"[хx][уy][иiй]\s*в\s*р[оo][тt]",
    r"в\s*р[оo][тt]\s*[тt][её][бb][её]",
    r"в\s*р[оo][тt]\s*[её][бb][уy]",
    r"[тt][её][бb][яa]\s*[её][бb][аa][лл]",
    r"[тt][её][бb][яa]\s*[эe][бb][аa][лл]",
    r"[тt][её][бb][яa]\s*[её][бb][уy]",
    r"[тt][её][бb][яa]\s*[её][бb][аa][тт][ьъ]",
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

COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.UNICODE) for p in INSULT_PATTERNS
]

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
async def do_mute(context, chat_id, user_id, mention, reason="оскорбление"):
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
    stats[user_id]["violations"] += 1

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
        mention = f'<a href="tg://user?id={member.id}">{member.first_name}</a>'
        await update.message.reply_text(
            f"👋 Привет, {mention}! Добро пожаловать в группу!\n"
            f"📋 Маты разрешены, оскорбления — нет.",
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
    now = datetime.now(timezone.utc)

    stats[user.id]["name"] = user.first_name
    mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    # Антифлуд — больше 5 сообщений за 5 секунд
    user_messages[user.id] = [t for t in user_messages[user.id] if (now - t).seconds < 5]
    user_messages[user.id].append(now)
    if len(user_messages[user.id]) > 5:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception:
            pass
        await do_mute(context, chat_id, user.id, mention, "флуд")
        return

    # Антиспам — одно и то же сообщение 3 раза подряд
    if text == user_last_msg[user.id]:
        user_repeat[user.id] += 1
        if user_repeat[user.id] >= 3:
            user_repeat[user.id] = 0
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except Exception:
                pass
            await do_mute(context, chat_id, user.id, mention, "спам")
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

    # Система предупреждений
    warnings[user.id] += 1
    warn_count = warnings[user.id]

    if warn_count < WARN_LIMIT:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ {mention}, предупреждение <b>{warn_count}/{WARN_LIMIT}</b> за оскорбление.\n"
                    f"❌ Сообщение удалено.\n"
                    f"{'🔇 На следующем нарушении получишь мут!' if warn_count == WARN_LIMIT - 1 else ''}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"[ОШИБКА] Предупреждение: {e}")
    else:
        warnings[user.id] = 0
        await do_mute(context, chat_id, user.id, mention, "оскорбление")

# ── Команды ───────────────────────────────────────────────────────────────────
async def toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    if update.message.from_user.id != OWNER_ID:
        return
    bot_enabled = not bot_enabled
    status = "✅ Бот включён — модерация активна." if bot_enabled else "❌ Бот выключен — модерация остановлена."
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
    await update.message.reply_text(f"🔊 {target.first_name} размучен.")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы забанить.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await update.message.reply_text(f"🚫 {target.first_name} забанен.")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы кикнуть.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await context.bot.unban_chat_member(chat_id=update.message.chat_id, user_id=target.id)
    await update.message.reply_text(f"👢 {target.first_name} кикнут.")

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Ответь на сообщение пользователя чтобы выдать предупреждение.")
        return
    member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
    if member.status not in ("administrator", "creator"):
        return
    target = update.message.reply_to_message.from_user
    warnings[target.id] += 1
    mention = f'<a href="tg://user?id={target.id}">{target.first_name}</a>'
    await update.message.reply_text(
        f"⚠️ {mention} получил предупреждение <b>{warnings[target.id]}/{WARN_LIMIT}</b>.",
        parse_mode="HTML",
    )

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

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("bot", toggle_bot))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
