# survivor_bot.py
import asyncio
import logging
import os
import random
import time
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

# -------- CONFIG ----------
load_dotenv()
API_TOKEN =  "8404293329:AAEvjbpPfYb_uDaAIakvym06kSOaNkUn9ME"  # <-- вставь токен или в .env
DB_PATH = "survivor.db"
DAY_SECONDS = 60  # длительность "дня" в секундах (для теста). Для реальной игры поставь 300-3600
MAX_DAYS = 50
# --------------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ---------- DB init ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
        CREATE TABLE IF NOT EXISTS games (
            chat_id INTEGER PRIMARY KEY,
            day INTEGER DEFAULT 0,
            running INTEGER DEFAULT 0,
            max_days INTEGER DEFAULT {MAX_DAYS}
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS players (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            hp INTEGER,
            food INTEGER,
            energy INTEGER,
            points INTEGER,
            alive INTEGER,
            alliance_with INTEGER,
            last_action_day INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            chat_id INTEGER,
            day INTEGER,
            user_id INTEGER,
            action TEXT,
            target_user_id INTEGER,
            timestamp INTEGER
        )
        """)
        await db.commit()

# ---------- DB helpers ----------
async def get_game(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id, day, running, max_days FROM games WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        return row  # None or tuple

async def create_game(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO games(chat_id, day, running, max_days) VALUES(?, ?, ?, ?)",
                         (chat_id, 0, 0, MAX_DAYS))
        await db.commit()

async def set_game_running(chat_id: int, running: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE games SET running = ? WHERE chat_id = ?", (1 if running else 0, chat_id))
        await db.commit()

async def set_game_day(chat_id: int, day: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE games SET day = ? WHERE chat_id = ?", (day, chat_id))
        await db.commit()

async def inc_day(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE games SET day = day + 1 WHERE chat_id = ?", (chat_id,))
        await db.commit()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT day FROM games WHERE chat_id = ?", (chat_id,))
        r = await cur.fetchone()
        return r[0] if r else 0

# Players
async def add_player(chat_id: int, user: types.User):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT OR IGNORE INTO players(chat_id, user_id, username, hp, food, energy, points, alive, alliance_with, last_action_day)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (chat_id, user.id, user.username or user.full_name, 10, 3, 5, 0, 1, None, -1))
        await db.commit()

async def remove_player(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM players WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await db.commit()

async def get_player(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id,user_id,username,hp,food,energy,points,alive,alliance_with,last_action_day FROM players WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return await cur.fetchone()

async def update_player_stat(chat_id: int, user_id: int, **kwargs):
    if not kwargs:
        return
    pairs = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [chat_id, user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE players SET {pairs} WHERE chat_id = ? AND user_id = ?", values)
        await db.commit()

async def list_alive_players(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, username, hp, food, energy, points FROM players WHERE chat_id = ? AND alive = 1", (chat_id,))
        return await cur.fetchall()

# Actions
async def record_action(chat_id: int, day: int, user_id: int, action: str, target_user_id: Optional[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO actions(chat_id, day, user_id, action, target_user_id, timestamp) VALUES(?,?,?,?,?,?)",
                         (chat_id, day, user_id, action, target_user_id, int(time.time())))
        await db.commit()

async def get_actions_for_day(chat_id: int, day: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, action, target_user_id FROM actions WHERE chat_id = ? AND day = ?", (chat_id, day))
        return await cur.fetchall()

async def clear_actions_for_day(chat_id: int, day: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM actions WHERE chat_id = ? AND day = ?", (chat_id, day))
        await db.commit()

# ---------- Game logic ----------
async def process_day(chat_id: int):
    game = await get_game(chat_id)
    if not game or game[2] == 0:
        return
    # advance day
    day = await inc_day(chat_id)
    actions = await get_actions_for_day(chat_id, day)
    actions_map = {a[0]: (a[1], a[2]) for a in actions}
    alive = await list_alive_players(chat_id)
    announce_lines = [f"🌴 День {day} — итоги:"]

    # participation points
    for p in alive:
        uid = p[0]
        # add +1 participation point
        await update_player_stat(chat_id, uid, points=p[5] + 1)

    # process each alive player's action
    for p in alive:
        uid, username, hp, food, energy, points = p
        act = actions_map.get(uid)
        if not act:
            announce_lines.append(f"• @{username} бездействовал(а).")
            continue
        action, target = act
        # fetch fresh row for target checks
        row = await get_player(chat_id, uid)
        cur_hp = row[3]; cur_food = row[4]; cur_energy = row[5]; cur_points = row[6]
        if action == "hunt":
            success_chance = 0.5 + (cur_energy - 3) * 0.05
            success_chance = max(0.2, min(success_chance, 0.9))
            if random.random() < success_chance:
                found = random.randint(1, 3)
                cur_food += found
                cur_points += 5
                announce_lines.append(f"🎯 @{username} удачно охотился(ась) и нашёл(ла) {found} еды.")
            else:
                inj = random.randint(1, 3)
                cur_hp -= inj
                announce_lines.append(f"⚠️ @{username} неудачно охотился(ась) и получил(а) ранение −{inj} HP.")
            cur_energy = max(0, cur_energy - 2)
            await update_player_stat(chat_id, uid, hp=cur_hp, food=cur_food, energy=cur_energy, points=cur_points, last_action_day=day)
        elif action == "gather":
            if random.random() < 0.8:
                found = random.randint(1, 2)
                cur_food += found
                cur_points += 4
                announce_lines.append(f"🌿 @{username} собрал(а) {found} еды/ресурсов.")
            else:
                announce_lines.append(f"🌿 @{username} ничего не нашёл(ла).")
            cur_energy = max(0, cur_energy - 1)
            await update_player_stat(chat_id, uid, food=cur_food, energy=cur_energy, points=cur_points, last_action_day=day)
        elif action == "build":
            cur_points += 2
            cur_energy = max(0, cur_energy - 2)
            # mark 'built' by giving a tiny flag: we'll rely on last_action_day==day and action recorded to infer shelter
            announce_lines.append(f"🏗️ @{username} построил(а) убежище — повышена защита ночью.")
            await update_player_stat(chat_id, uid, points=cur_points, energy=cur_energy, last_action_day=day)
        elif action == "sleep":
            cur_energy = min(10, cur_energy + 3)
            if cur_food > 0:
                cur_hp = min(10, cur_hp + 1)
                cur_food = max(0, cur_food - 1)
                announce_lines.append(f"😴 @{username} спал(а), восстановил(а) энергию и немного HP (съел(а) 1 еду).")
            else:
                announce_lines.append(f"😴 @{username} спал(а), но у него(неё) не было еды — восстановлено только энергия.")
            await update_player_stat(chat_id, uid, energy=cur_energy, hp=cur_hp, food=cur_food, last_action_day=day)
        elif action == "steal":
            if not target:
                announce_lines.append(f"🫣 @{username} попытался(ась) украсть, но не указал(а) цель.")
                continue
            target_row = await get_player(chat_id, target)
            if not target_row or target_row[7] == 0:
                announce_lines.append(f"🫣 @{username} попытался(ась) украсть у несуществующего/мертвого игрока.")
                continue
            if random.random() < 0.5:
                stolen = min(target_row[4], random.randint(1, 3))
                if stolen <= 0:
                    announce_lines.append(f"👀 @{username} попытался(ась) украсть у @{target_row[2]}, но у того не было еды.")
                else:
                    # apply changes
                    await update_player_stat(chat_id, target, food=target_row[4] - stolen)
                    cur_food += stolen
                    cur_points += 3
                    announce_lines.append(f"💥 @{username} успешно украл(а) {stolen} еды у @{target_row[2]}!")
                    await update_player_stat(chat_id, uid, food=cur_food, points=cur_points, energy=max(0, cur_energy - 1), last_action_day=day)
            else:
                lost = random.randint(0, 2)
                cur_food = max(0, cur_food - lost)
                cur_hp = max(0, cur_hp - 1)
                announce_lines.append(f"❌ @{username} провалил(а) кражу и потерял(а) {lost} еды и −1 HP.")
                await update_player_stat(chat_id, uid, food=cur_food, hp=cur_hp, energy=max(0, cur_energy - 1), last_action_day=day)
        elif action == "ally":
            if not target:
                announce_lines.append(f"🤝 @{username} хотел(а) создать альянс, но не указал(а) цель.")
                continue
            target_row = await get_player(chat_id, target)
            if not target_row or target_row[7] == 0:
                announce_lines.append(f"🤝 @{username} попытался(ась) создать альянс с несуществующим/мертвым игроком.")
                continue
            await update_player_stat(chat_id, uid, alliance_with=target, last_action_day=day)
            announce_lines.append(f"🤝 @{username} создал(а) временный альянс с @{target_row[2]}.")
        else:
            announce_lines.append(f"❓ @{username} выполнил(а) неизвестное действие: {action}")

    # Night random event:
    event_roll = random.random()
    if event_roll < 0.12:
        potential = await list_alive_players(chat_id)
        if potential:
            victim = random.choice(potential)
            victim_row = await get_player(chat_id, victim[0])
            inj = random.randint(2, 4)
            new_hp = victim_row[3] - inj
            if new_hp <= 0:
                await update_player_stat(chat_id, victim[0], hp=0, alive=0)
                announce_lines.append(f"🦈 Ночью @{victim_row[2]} был(а) атакован(а) зверем и погиб(ла).")
            else:
                await update_player_stat(chat_id, victim[0], hp=new_hp)
                announce_lines.append(f"🦈 Ночью @{victim_row[2]} был(а) атакован(а) зверем и потерял(а) {inj} HP.")
    elif event_roll < 0.30:
        announce_lines.append("🌧️ Ночь была дождливой — некоторые игроки потеряли еду/здоровье.")
        potential = await list_alive_players(chat_id)
        for victim in random.sample(potential, k=min(3, len(potential))):
            uid = victim[0]
            # victim tuple: user_id, username, hp, food, energy, points
            new_food = max(0, victim[3] - 1)
            new_hp = max(0, victim[2] - 1)
            await update_player_stat(chat_id, uid, food=new_food, hp=new_hp)
            announce_lines.append(f"• @{victim[1]} промок(ла) и потерял(а) 1 еду и 1 HP.")
    else:
        announce_lines.append("🌙 Ночь прошла мирно.")

    # finalize: hunger damage and deaths
    alive_after = await list_alive_players(chat_id)
    for p in alive_after:
        uid, username, hp, food, energy, points = p
        if food <= 0:
            hp -= 1
            await update_player_stat(chat_id, uid, hp=hp)
            announce_lines.append(f"⚠️ @{username} голодает — −1 HP.")
        if hp <= 0:
            await update_player_stat(chat_id, uid, alive=0)
            announce_lines.append(f"💀 @{username} умер(ла) от последствий.")

    # clear actions for this day
    await clear_actions_for_day(chat_id, day)

    # send announcement
    text = "\n".join(announce_lines)
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        logging.exception("Failed to send day summary")

    # check victory
    survivors = await list_alive_players(chat_id)
    if len(survivors) <= 1:
        if survivors:
            winner = survivors[0]
            await bot.send_message(chat_id, f"🏆 Игра окончена! Победитель: @{winner[1]} (очки: {winner[5]})")
        else:
            await bot.send_message(chat_id, "🪦 Все вымерли — игра окончена.")
        await set_game_running(chat_id, False)
        return

    # check max days
    game = await get_game(chat_id)
    if game and game[1] >= game[3]:
        ranking = sorted(await list_alive_players(chat_id), key=lambda x: x[5], reverse=True)
        lines = ["🏁 Игра завершена по максимуму дней. Итоговый рейтинг:"]
        for i, p in enumerate(ranking[:10], start=1):
            lines.append(f"{i}. @{p[1]} — {p[5]} очков")
        await bot.send_message(chat_id, "\n".join(lines))
        await set_game_running(chat_id, False)

# ---------- Command handlers ----------
@dp.message(Command(commands=["start"]))
async def cmd_start(message: types.Message):
    text = (
        "🌴 Добро пожаловать в Survivor Chat!\n\n"
        "Команды:\n"
        "/join - присоединиться к игре\n"
        "/leave - выйти из игры\n"
        "/begin_game - начать игру (только админ или кто создал)\n"
        "/action <hunt|gather|build|sleep|steal|ally> [@user] - выполнить действие в текущем дне\n"
        "/status - показать свой статус\n"
        "/leaderboard - топ игроков\n"
        "/end - остановить игру\n"
    )
    await message.reply(text)

@dp.message(Command(commands=["join"]))
async def cmd_join(message: types.Message):
    chat_id = message.chat.id
    user = message.from_user
    await create_game(chat_id)  # ensure game row exists
    await add_player(chat_id, user)
    await message.reply(f"✅ @{user.username or user.full_name} присоединился(ась) к игре!")

@dp.message(Command(commands=["leave"]))
async def cmd_leave(message: types.Message):
    chat_id = message.chat.id
    user = message.from_user
    await remove_player(chat_id, user.id)
    await message.reply(f"❌ @{user.username or user.full_name} вышел(ла) из игры.")

@dp.message(Command(commands=["begin_game"]))
async def cmd_begin_game(message: types.Message):
    chat_id = message.chat.id
    # simple permission: allow anyone to start if game not running
    game = await get_game(chat_id)
    if not game:
        await create_game(chat_id)
        game = await get_game(chat_id)
    if game[2] == 1:
        await message.reply("Игра уже запущена.")
        return
    # require at least 2 players
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM players WHERE chat_id = ?", (chat_id,))
        c = await cur.fetchone()
    if c and c[0] < 2:
        await message.reply("Нужно как минимум 2 игрока, чтобы начать.")
        return
    # set running and day 0 (day will increment on first tick)
    await set_game_day(chat_id, 0)
    await set_game_running(chat_id, True)
    await message.reply("🎮 Игра начата! Каждый день длится " + str(DAY_SECONDS) + " секунд. Используйте /action чтобы действовать.")

@dp.message(Command(commands=["status"]))
async def cmd_status(message: types.Message):
    chat_id = message.chat.id
    user = message.from_user
    row = await get_player(chat_id, user.id)
    if not row:
        await message.reply("Ты не в игре. Напиши /join чтобы присоединиться.")
        return
    _, _, username, hp, food, energy, points, alive, alliance, last_action_day = row
    text = (f"📊 Статус @{username}:\nHP: {hp}\nFood: {food}\nEnergy: {energy}\nPoints: {points}\nAlive: {'Да' if alive else 'Нет'}\n"
            f"Alliance with: {alliance if alliance else '—'}\nLast action day: {last_action_day}")
    await message.reply(text)

@dp.message(Command(commands=["leaderboard"]))
async def cmd_leaderboard(message: types.Message):
    chat_id = message.chat.id
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, points FROM players WHERE chat_id = ? ORDER BY points DESC LIMIT 10", (chat_id,))
        rows = await cur.fetchall()
    if not rows:
        await message.reply("Нет игроков в игре.")
        return
    lines = ["🏆 Топ игроков:"]
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. @{r[0]} — {r[1]} очков")
    await message.reply("\n".join(lines))

@dp.message(Command(commands=["end"]))
async def cmd_end(message: types.Message):
    chat_id = message.chat.id
    await set_game_running(chat_id, False)
    await message.reply("Игра остановлена админом / окончена.")

# Catch action messages via /action or short forms
@dp.message()
async def catch_action(message: types.Message):
    txt = (message.text or "").strip()
    if not txt.startswith("/"):
        return
    parts = txt.split()
    cmd = parts[0][1:].lower()
    chat_id = message.chat.id
    user = message.from_user
    game = await get_game(chat_id)
    if not game or game[2] == 0:
        # no running game
        return
    day = game[1]  # current day number (before increment)
    # allowed commands: /action, or short: /hunt /gather etc.
    if cmd == "action":
        if len(parts) < 2:
            await message.reply("Укажи действие: /action hunt|gather|build|sleep|steal|ally [@user]")
            return
        action = parts[1].lower()
        target = None
        if action in ("steal", "ally") and len(parts) >= 3:
            mention = parts[2]
            if mention.startswith("@"):
                mention = mention[1:]
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT user_id FROM players WHERE chat_id = ? AND username = ?", (chat_id, mention))
                rr = await cur.fetchone()
                if rr:
                    target = rr[0]
            if not target and message.reply_to_message:
                target = message.reply_to_message.from_user.id
    else:
        # short commands like /hunt /gather ...
        action = cmd
        target = None
        if action in ("steal", "ally"):
            # try reply
            if message.reply_to_message:
                target = message.reply_to_message.from_user.id
            elif len(parts) >= 2:
                mention = parts[1]
                if mention.startswith("@"):
                    mention = mention[1]
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("SELECT user_id FROM players WHERE chat_id = ? AND username = ?", (chat_id, mention))
                    rr = await cur.fetchone()
                    if rr:
                        target = rr[0]

    allowed = {"hunt", "gather", "build", "sleep", "steal", "ally"}
    if action not in allowed:
        return

    # ensure player exists
    row = await get_player(chat_id, user.id)
    if not row:
        await add_player(chat_id, user)
        row = await get_player(chat_id, user.id)

    last_action_day = row[9]
    if last_action_day == day:
        await message.reply("Ты уже сделал(а) действие в этом дне.")
        return

    await record_action(chat_id, day, user.id, action, target)
    await update_player_stat(chat_id, user.id, last_action_day=day)
    await message.reply(f"Действие '{action}' зафиксировано на День {day}.")

# ---------- Background day loop ----------
async def day_loop():
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT chat_id FROM games WHERE running = 1")
                rows = await cur.fetchall()
            chats = [r[0] for r in rows] if rows else []
            for chat_id in chats:
                await process_day(chat_id)
        except Exception:
            logging.exception("Error in day loop")
        await asyncio.sleep(DAY_SECONDS)

# ---------- Startup ----------
async def main():
    await init_db()
    # start day loop
    asyncio.create_task(day_loop())
    # start polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())



 
