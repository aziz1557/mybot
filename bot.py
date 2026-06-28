import re
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8422286281:AAFDqQ1xhPem2Bpc4D_b0I6aRF7zH0C1dFo"

INSULT_PATTERNS = [
    # даун и обходы
    r"\bдаун\b",
    r"\bдауна\b",
    r"\bдауны\b",
    r"д[аa][уy]н",

    # эблан и обходы
    r"\bэблан\b",
    r"\bэблана\b",
    r"[эe]бл[аa]н",
    r"[эe]б[лl][аa4]н",
    r"иди\s*на[хx\*х]+",
    r"иди\s*н[4а][хx\*х]",
    r"ид[и1]\s*на[хx\*х]",
    r"пошёл?\s*на[хx\*х]",
    r"пош[её]л\s*на[хx\*х]",
    r"вали\s*на[хx\*х]",
    r"\b(ты|вы|он|она)\s*(тупой|тупая|тупые|тупо[ей])",
    r"\b(ты|вы|он|она)\s*(идиот|идиотка|дебил|дебилка|кретин|кретинка)",
    r"\b(ты|вы|он|она)\s*(урод|уродина|урода)",
    r"\b(ты|вы|он|она)\s*(лох|лоха|лошара|лохушка)",
    r"\b(ты|вы|он|она)\s*(мразь|тварь|скотина|ублюдок|ублюдка)",
    r"\b(ты|вы|он|она)\s*(придурок|придурка|даун|дауна)",
    r"\b(ты|вы|он|она)\s*(нуб|нубас|нубик)",
    r"\bтупица\b",
    r"\bдебил[аку]?\b",
    r"\bидиот[аку]?\b",
    r"\bкретин[аку]?\b",
    r"\bурод(ина|а)?\b",
    r"\bлошара\b",
    r"\bлохушка\b",
    r"\bмразь\b",
    r"\bтварь\b",
    r"\bскотина\b",
    r"\bублюдок\b",
    r"\bублюдка\b",
    r"\bпридурок\b",
    r"\bпридурка\b",
    r"д[еe3]б[иi1]л",
    r"[иi1]д[иi1][оo0]т",
    r"кр[еe3]т[иi1]н",
    r"т[уy][пп][оo0][йеея]",
    r"[уу]р[оo0]д",
    r"[уу]б[лл][юу]д[оo0]к",
    r"пр[иi1]д[уу]р[оo0]к",
    r"ид[иi1]\s*[её]б",
    r"[её]б[иись]\s*(отсюда|нах)",
    r"за[тт]кни[сс]ь",
    r"за[тт]кни\s*рот",
    r"убью\s*(тебя|вас|его|её)",
    r"прибью\s*(тебя|вас|его|её)",
    r"н[аa]х[уy][иi]",
    r"[пp][иi1][зz3][дd][аa]",
]

COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.UNICODE) for p in INSULT_PATTERNS
]

def contains_insult(text):
    for pattern in COMPILED_PATTERNS:
        if pattern.search(text):
            return True
    return False

async def unmute_user(bot, chat_id, user_id, mention, mute_msg_id):
    await asyncio.sleep(30)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    if message.chat.type not in ("group", "supergroup"):
        return

    text = message.text
    if not contains_insult(text):
        return

    user = message.from_user
    chat_id = message.chat_id

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    except Exception as e:
        print(f"[ОШИБКА] Удаление: {e}")
        return

    mute_until = datetime.now(timezone.utc) + timedelta(seconds=35)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=mute_until,
        )
    except Exception as e:
        print(f"[ОШИБКА] Мут: {e}")

    mention = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

    try:
        mute_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔇 {mention} получил мут на <b>30 секунд</b> за оскорбление 🖕\n"
                f"❌ Сообщение удалено.\n"
                f"⏳ Писать снова можно будет через <b>30 секунд</b>."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[ОШИБКА] Сообщение о муте: {e}")
        return

    asyncio.ensure_future(
        unmute_user(context.bot, chat_id, user.id, mention, mute_msg.message_id)
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен.")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
