"""
Модуль игры «Мафия» для встраивания в существующего telegram-бота (python-telegram-bot v21).

Команды:
  /mafia        — открыть набор в игру (лобби) в групповом чате
  /startmafia   — досрочно начать игру (только админ), если набралось минимум игроков
  /stopmafia    — принудительно остановить игру (только админ)

Роли: Дон (мафия), Доктор, Мирный житель.
Ночь: Дон выбирает, кого убить (ЛС), Доктор — кого лечить (ЛС).
День: объявление итогов ночи -> обсуждение по таймеру -> голосование кнопками -> казнь.
Фазы дня/ночи переключаются автоматически по таймеру.

Состояние хранится в памяти процесса (GAMES). При перезапуске бота активные игры теряются —
это осознанное упрощение, чтобы не городить БД поверх уже работающего JSON-хранилища бота.
"""

import asyncio
import os
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, Forbidden
from telegram.ext import ContextTypes

# ── Настройки (можно переопределить переменными окружения) ──────────────────
MIN_PLAYERS = int(os.getenv("MAFIA_MIN_PLAYERS", "4"))
MAX_PLAYERS = int(os.getenv("MAFIA_MAX_PLAYERS", "12"))
NIGHT_DURATION = int(os.getenv("MAFIA_NIGHT_SECONDS", "45"))
DAY_DISCUSSION_DURATION = int(os.getenv("MAFIA_DAY_SECONDS", "60"))
VOTING_DURATION = int(os.getenv("MAFIA_VOTING_SECONDS", "30"))

ROLE_DON = "don"
ROLE_DOCTOR = "doctor"
ROLE_CIVILIAN = "civilian"
ROLE_NAMES = {
    ROLE_DON: "🔪 Дон (Мафия)",
    ROLE_DOCTOR: "💊 Доктор",
    ROLE_CIVILIAN: "👤 Мирный житель",
}

# chat_id -> game state dict
GAMES: dict[int, dict] = {}


async def _is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False


def _alive_players(game: dict) -> list[dict]:
    return [p for p in game["players"].values() if p["alive"]]


def _players_by_role(game: dict, role: str) -> list[dict]:
    return [p for p in _alive_players(game) if p["role"] == role]


def _players_keyboard(players: list[dict], prefix: str, chat_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(p["name"], callback_data=f"{prefix}:{chat_id}:{p['id']}")]
        for p in players
    ]
    return InlineKeyboardMarkup(rows)


def _lobby_text(game: dict) -> str:
    players = list(game["players"].values())
    lines = [
        "🎭 <b>Набор в игру «Мафия»!</b>",
        "",
        f"Игроков: <b>{len(players)}</b> (минимум {MIN_PLAYERS}, максимум {MAX_PLAYERS})",
        "",
    ]
    if players:
        lines.append("👥 <b>Участники:</b>")
        lines += [f"• {p['name']}" for p in players]
    else:
        lines.append("Пока никто не присоединился.")
    lines.append("")
    lines.append("Жми кнопку, чтобы войти/выйти. Когда наберётся минимум — админ запускает игру: /startmafia")
    return "\n".join(lines)


def _lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Присоединиться / 🚪 Покинуть", callback_data="mafia_toggle")]]
    )


# ────────────────────────── Команды ──────────────────────────

async def cmd_mafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.message.chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("🎭 Игру можно начать только в групповом чате.")
        return

    existing = GAMES.get(chat.id)
    if existing and existing["status"] != "finished":
        await update.message.reply_text("🎭 Игра уже идёт или набор уже открыт в этом чате.")
        return

    GAMES[chat.id] = {
        "status": "lobby",
        "players": {},
        "day_number": 0,
        "night_actions": {},
        "votes": {},
        "lobby_message_id": None,
        "phase_message_id": None,
        "task": None,
    }
    msg = await update.message.reply_text(
        _lobby_text(GAMES[chat.id]), parse_mode="HTML", reply_markup=_lobby_keyboard()
    )
    GAMES[chat.id]["lobby_message_id"] = msg.message_id


async def cb_lobby_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = GAMES.get(chat_id)
    if not game or game["status"] != "lobby":
        await query.answer("Набор в игру сейчас не идёт.", show_alert=True)
        return

    user = query.from_user
    if user.id in game["players"]:
        del game["players"][user.id]
        await query.answer("🚪 Вы вышли из игры.")
    else:
        if len(game["players"]) >= MAX_PLAYERS:
            await query.answer("Мест больше нет.", show_alert=True)
            return
        game["players"][user.id] = {
            "id": user.id,
            "name": user.first_name,
            "username": user.username,
            "role": None,
            "alive": True,
        }
        await query.answer("✅ Вы в игре!")

    try:
        await query.edit_message_text(
            _lobby_text(game), parse_mode="HTML", reply_markup=_lobby_keyboard()
        )
    except TelegramError:
        pass


async def cmd_startmafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.message.chat
    game = GAMES.get(chat.id)
    if not game or game["status"] != "lobby":
        await update.message.reply_text("🎭 Сейчас нет открытого набора. Начните его командой /mafia")
        return
    if not await _is_admin(context, chat.id, update.message.from_user.id):
        await update.message.reply_text("⛔ Запускать игру может только администратор.")
        return
    if len(game["players"]) < MIN_PLAYERS:
        await update.message.reply_text(
            f"❌ Недостаточно игроков: {len(game['players'])}/{MIN_PLAYERS} минимум."
        )
        return

    await _begin_game(chat.id, context)


async def cmd_stopmafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.message.chat
    game = GAMES.get(chat.id)
    if not game:
        await update.message.reply_text("🎭 Игра сейчас не запущена.")
        return
    if not await _is_admin(context, chat.id, update.message.from_user.id):
        await update.message.reply_text("⛔ Останавливать игру может только администратор.")
        return

    task = game.get("task")
    if task:
        task.cancel()
    GAMES.pop(chat.id, None)
    await update.message.reply_text("🛑 Игра остановлена администратором.")


# ────────────────────────── Запуск игры и раздача ролей ──────────────────────────

async def _begin_game(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES[chat_id]
    players = list(game["players"].values())

    # Проверяем, что все игроки писали боту в ЛС (иначе не сможем отправить роль/ночные кнопки)
    unreachable = []
    for p in players:
        try:
            await context.bot.send_message(
                p["id"], "🎭 Игра начинается! Роль придёт следующим сообщением."
            )
        except Forbidden:
            unreachable.append(p["name"])
        except TelegramError:
            unreachable.append(p["name"])

    if unreachable:
        await context.bot.send_message(
            chat_id,
            "❌ Не получилось начать игру — эти игроки не открывали ЛС с ботом:\n"
            + "\n".join(f"• {n}" for n in unreachable)
            + "\n\nПопросите их написать боту /start в личку и запустите /startmafia снова.",
        )
        return

    random.shuffle(players)
    roles = [ROLE_DON, ROLE_DOCTOR] + [ROLE_CIVILIAN] * (len(players) - 2)
    for p, role in zip(players, roles):
        p["role"] = role
        game["players"][p["id"]]["role"] = role

    for p in players:
        try:
            await context.bot.send_message(
                p["id"],
                f"🎭 Ваша роль: <b>{ROLE_NAMES[p['role']]}</b>",
                parse_mode="HTML",
            )
        except TelegramError:
            pass

    game["status"] = "night"
    game["day_number"] = 0
    await context.bot.send_message(
        chat_id,
        f"🎭 Игра началась! Игроков: {len(players)}.\n"
        f"🌙 Наступает первая ночь ({NIGHT_DURATION} сек)...",
    )
    game["task"] = asyncio.create_task(_game_loop(chat_id, context))


# ────────────────────────── Основной игровой цикл ──────────────────────────

async def _game_loop(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        while True:
            game = GAMES.get(chat_id)
            if not game:
                return

            winner = _check_win(game)
            if winner:
                await _announce_winner(chat_id, context, winner)
                GAMES.pop(chat_id, None)
                return

            # ── Ночь ──
            game["day_number"] += 1
            game["night_actions"] = {}
            await _send_night_actions(chat_id, context)
            await asyncio.sleep(NIGHT_DURATION)
            await _resolve_night(chat_id, context)

            game = GAMES.get(chat_id)
            if not game:
                return
            winner = _check_win(game)
            if winner:
                await _announce_winner(chat_id, context, winner)
                GAMES.pop(chat_id, None)
                return

            # ── День: обсуждение ──
            game["status"] = "day_discussion"
            await context.bot.send_message(
                chat_id, f"💬 Обсуждение ({DAY_DISCUSSION_DURATION} сек). Кто, по-вашему, Дон?"
            )
            await asyncio.sleep(DAY_DISCUSSION_DURATION)

            # ── День: голосование ──
            game = GAMES.get(chat_id)
            if not game:
                return
            game["status"] = "voting"
            game["votes"] = {}
            await _send_voting(chat_id, context)
            await asyncio.sleep(VOTING_DURATION)
            await _resolve_voting(chat_id, context)

            game = GAMES.get(chat_id)
            if not game:
                return
            game["status"] = "night"
    except asyncio.CancelledError:
        return
    except Exception as e:
        print(f"[МАФИЯ ОШИБКА] chat_id={chat_id}: {e}")
        try:
            await context.bot.send_message(
                chat_id, "⚠️ В игре произошла ошибка, она была остановлена."
            )
        except TelegramError:
            pass
        GAMES.pop(chat_id, None)


# ────────────────────────── Ночь ──────────────────────────

async def _send_night_actions(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES[chat_id]
    alive = _alive_players(game)

    don = _players_by_role(game, ROLE_DON)
    doctor = _players_by_role(game, ROLE_DOCTOR)

    if don:
        targets = [p for p in alive if p["id"] != don[0]["id"]]
        if targets:
            try:
                await context.bot.send_message(
                    don[0]["id"],
                    "🔪 Ночь. Кого убить?",
                    reply_markup=_players_keyboard(targets, "kill", chat_id),
                )
            except TelegramError:
                pass

    if doctor:
        try:
            await context.bot.send_message(
                doctor[0]["id"],
                "💊 Ночь. Кого лечить?",
                reply_markup=_players_keyboard(alive, "heal", chat_id),
            )
        except TelegramError:
            pass


async def cb_night_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    prefix, chat_id_str, target_id_str = query.data.split(":")
    chat_id = int(chat_id_str)
    target_id = int(target_id_str)

    game = GAMES.get(chat_id)
    if not game or game["status"] != "night":
        await query.answer("Ночь уже закончилась.", show_alert=True)
        return

    role = ROLE_DON if prefix == "kill" else ROLE_DOCTOR
    actor = game["players"].get(query.from_user.id)
    if not actor or actor["role"] != role or not actor["alive"]:
        await query.answer("Это действие не для вас.", show_alert=True)
        return

    game["night_actions"][role] = target_id
    await query.answer("Выбор принят ✅")
    try:
        await query.edit_message_text("Выбор успешно сделан ✅")
    except TelegramError:
        pass


async def _resolve_night(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game:
        return

    kill_target = game["night_actions"].get(ROLE_DON)
    heal_target = game["night_actions"].get(ROLE_DOCTOR)

    if kill_target and kill_target == heal_target:
        await context.bot.send_message(
            chat_id, "🌅 Наступает утро. Этой ночью доктор спас жертву мафии! Никто не погиб."
        )
    elif kill_target and kill_target in game["players"]:
        victim = game["players"][kill_target]
        victim["alive"] = False
        await context.bot.send_message(
            chat_id,
            f"🌅 Наступает утро. Этой ночью был убит: <b>{victim['name']}</b> "
            f"({ROLE_NAMES[victim['role']]}).",
            parse_mode="HTML",
        )
    else:
        await context.bot.send_message(chat_id, "🌅 Наступает утро. Этой ночью никто не погиб.")


# ────────────────────────── День / голосование ──────────────────────────

def _voting_text(game: dict) -> str:
    votes = game["votes"]
    counts: dict[int, int] = {}
    for target in votes.values():
        counts[target] = counts.get(target, 0) + 1
    lines = ["🗳 <b>Голосование за казнь.</b> Кого казним?", ""]
    if counts:
        lines.append("Текущие голоса:")
        for uid, c in sorted(counts.items(), key=lambda x: -x[1]):
            name = game["players"].get(uid, {}).get("name", "?")
            lines.append(f"• {name}: {c}")
    else:
        lines.append("Голосов пока нет.")
    return "\n".join(lines)


async def _send_voting(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES[chat_id]
    alive = _alive_players(game)
    msg = await context.bot.send_message(
        chat_id,
        _voting_text(game),
        parse_mode="HTML",
        reply_markup=_players_keyboard(alive, "vote", chat_id),
    )
    game["phase_message_id"] = msg.message_id


async def cb_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, chat_id_str, target_id_str = query.data.split(":")
    chat_id = int(chat_id_str)
    target_id = int(target_id_str)

    game = GAMES.get(chat_id)
    if not game or game["status"] != "voting":
        await query.answer("Голосование сейчас не идёт.", show_alert=True)
        return

    voter = game["players"].get(query.from_user.id)
    if not voter or not voter["alive"]:
        await query.answer("Голосовать могут только живые игроки.", show_alert=True)
        return

    game["votes"][voter["id"]] = target_id
    await query.answer("Голос учтён ✅")

    alive = _alive_players(game)
    try:
        await query.edit_message_text(
            _voting_text(game),
            parse_mode="HTML",
            reply_markup=_players_keyboard(alive, "vote", chat_id),
        )
    except TelegramError:
        pass


async def _resolve_voting(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game:
        return

    counts: dict[int, int] = {}
    for target in game["votes"].values():
        counts[target] = counts.get(target, 0) + 1

    if not counts:
        await context.bot.send_message(chat_id, "🗳 Никто не проголосовал. Никого не казнили.")
        return

    max_votes = max(counts.values())
    top = [uid for uid, c in counts.items() if c == max_votes]
    if len(top) > 1:
        await context.bot.send_message(chat_id, "🗳 Голоса разделились поровну. Никого не казнили.")
        return

    victim_id = top[0]
    victim = game["players"].get(victim_id)
    if victim:
        victim["alive"] = False
        await context.bot.send_message(
            chat_id,
            f"⚖️ Большинством голосов казнён: <b>{victim['name']}</b> "
            f"({ROLE_NAMES[victim['role']]}).",
            parse_mode="HTML",
        )


# ────────────────────────── Победа ──────────────────────────

def _check_win(game: dict) -> str | None:
    alive = _alive_players(game)
    dons_alive = [p for p in alive if p["role"] == ROLE_DON]
    others_alive = [p for p in alive if p["role"] != ROLE_DON]

    if not dons_alive:
        return "civilians"
    if len(dons_alive) >= len(others_alive):
        return "mafia"
    return None


async def _announce_winner(chat_id: int, context: ContextTypes.DEFAULT_TYPE, winner: str):
    game = GAMES.get(chat_id)
    roles_reveal = ""
    if game:
        roles_reveal = "\n".join(
            f"• {p['name']} — {ROLE_NAMES[p['role']]}" for p in game["players"].values()
        )
    if winner == "civilians":
        text = "🎉 <b>Мирные жители победили!</b> Дон был найден и казнён."
    else:
        text = "🔪 <b>Мафия победила!</b> Дону удалось одолеть мирных жителей."
    await context.bot.send_message(
        chat_id, f"{text}\n\n<b>Роли всех игроков:</b>\n{roles_reveal}", parse_mode="HTML"
    )


# ────────────────────────── Роутер callback-запросов ──────────────────────────

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data or ""
    if data == "mafia_toggle":
        await cb_lobby_toggle(update, context)
    elif data.startswith("kill:") or data.startswith("heal:"):
        await cb_night_action(update, context)
    elif data.startswith("vote:"):
        await cb_vote(update, context)
