import os
import random
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ==================== КОНФИГУРАЦИЯ ====================
TOKEN ='8404293329:AAEvjbpPfYb_uDaAIakvym06kSOaNkUn9ME'
DB_NAME = 'gamebot.db'

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        coins INTEGER DEFAULT 100,
        total_score INTEGER DEFAULT 0,
        games_played INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Таблица игровых сессий
    c.execute('''CREATE TABLE IF NOT EXISTS game_sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        game_type TEXT,
        score INTEGER,
        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    conn.close()

def update_coins(user_id, amount):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE users SET coins = coins + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def save_game_score(user_id, game_type, score):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO game_sessions (user_id, game_type, score) VALUES (?, ?, ?)', 
              (user_id, game_type, score))
    c.execute('UPDATE users SET total_score = total_score + ?, games_played = games_played + 1 WHERE user_id = ?',
              (score, user_id))
    conn.commit()
    conn.close()

def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT username, total_score, games_played FROM users ORDER BY total_score DESC LIMIT ?', (limit,))
    board = c.fetchall()
    conn.close()
    return board

# ==================== ДАННЫЕ ИГР ====================

# Викторина
QUIZ_QUESTIONS = [
    {"q": "Какая планета самая большая в Солнечной системе?", "options": ["Марс", "Юпитер", "Сатурн", "Нептун"], "answer": 1},
    {"q": "Сколько костей в теле взрослого человека?", "options": ["156", "206", "256", "306"], "answer": 1},
    {"q": "Какой элемент имеет химический символ 'Au'?", "options": ["Серебро", "Золото", "Медь", "Железо"], "answer": 1},
    {"q": "В каком году закончилась Вторая мировая война?", "options": ["1943", "1944", "1945", "1946"], "answer": 2},
    {"q": "Кто написал 'Гарри Поттера'?", "options": ["Дж. Р. Р. Толкин", "Дж. К. Роулинг", "Стивен Кинг", "Джордж Мартин"], "answer": 1},
    {"q": "Какая страна самая большая по площади?", "options": ["Канада", "Китай", "США", "Россия"], "answer": 3},
    {"q": "Сколько струн у стандартной гитары?", "options": ["4", "6", "8", "12"], "answer": 1},
    {"q": "Какое животное самое быстрое на суше?", "options": ["Лев", "Гепард", "Антилопа", "Лошадь"], "answer": 1},
    {"q": "Какой океан самый большой?", "options": ["Атлантический", "Индийский", "Северный Ледовитый", "Тихий"], "answer": 3},
    {"q": "Кто изобрел телефон?", "options": ["Томас Эдисон", "Никола Тесла", "Александр Белл", "Генри Форд"], "answer": 2},
]

# Виселица
HANGMAN_WORDS = {
    "фильмы": ["МАТРИЦА", "АВАТАР", "ТИТАНИК", "НАЧАЛО", "ГЛАДИАТОР", "ИНТЕРСТЕЛЛАР"],
    "игры": ["МАЙНКРАФТ", "ФОРТНАЙТ", "ДОТА", "КОНТРСТРАЙК", "ВАЛОРАНТ", "РОБЛОКС"],
    "животные": ["ЖИРАФ", "КРОКОДИЛ", "ПИНГВИН", "ДЕЛЬФИН", "МЕДВЕДЬ", "КЕНГУРУ"],
    "страны": ["ФРАНЦИЯ", "ЯПОНИЯ", "БРАЗИЛИЯ", "АВСТРАЛИЯ", "ЕГИПЕТ", "КАНАДА"],
}

# Слова из слова
WORD_GAME_WORDS = [
    {"word": "ПРОГРАММИРОВАНИЕ", "min_words": 15},
    {"word": "КОМПЬЮТЕР", "min_words": 10},
    {"word": "ТЕЛЕФОН", "min_words": 8},
]

# ==================== ИГРОВАЯ ЛОГИКА ====================

# Хранилище игровых сессий в памяти
user_games = {}

def get_game_state(user_id):
    return user_games.get(user_id, {})

def set_game_state(user_id, state):
    user_games[user_id] = state

def clear_game_state(user_id):
    if user_id in user_games:
        del user_games[user_id]

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username or user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🎯 Играть", callback_data="menu_games")],
        [InlineKeyboardButton("🏆 Рейтинг", callback_data="leaderboard"),
         InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎮 <b>Добро пожаловать в GameBox!</b>\n\n"
        f"Привет, {user.first_name}! Готов сыграть?\n\n"
        f"🪙 Начальный баланс: 100 монет\n"
        f"🎯 Играй, зарабатывай монеты и попади в топ!",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # ===== ГЛАВНОЕ МЕНЮ =====
    if data == "menu_main":
        keyboard = [
            [InlineKeyboardButton("🎯 Играть", callback_data="menu_games")],
            [InlineKeyboardButton("🏆 Рейтинг", callback_data="leaderboard"),
             InlineKeyboardButton("👤 Профиль", callback_data="profile")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎮 <b>GameBox - Главное меню</b>\n\n"
            "Выбери действие:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    # ===== МЕНЮ ИГР =====
    elif data == "menu_games":
        keyboard = [
            [InlineKeyboardButton("❓ Викторина", callback_data="game_quiz")],
            [InlineKeyboardButton("🎯 Виселица", callback_data="game_hangman")],
            [InlineKeyboardButton("🧮 Математика", callback_data="game_math")],
            [InlineKeyboardButton("📝 Слова из слова", callback_data="game_words")],
            [InlineKeyboardButton("✊✋✌️ К-Н-Б", callback_data="game_rps")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎯 <b>Выбери игру:</b>\n\n"
            "❓ <b>Викторина</b> - проверь эрудицию\n"
            "🎯 <b>Виселица</b> - угадай слово\n"
            "🧮 <b>Математика</b> - реши примеры\n"
            "📝 <b>Слова из слова</b> - составь слова\n"
            "✊✋✌️ <b>К-Н-Б</b> - играй против бота",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    # ===== ПРОФИЛЬ =====
    elif data == "profile":
        user = get_user(user_id)
        if user:
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"👤 <b>Твой профиль</b>\n\n"
                f"🆔 ID: {user[0]}\n"
                f"👤 Имя: {user[1]}\n"
                f"🪙 Монеты: {user[2]}\n"
                f"⭐ Общий счет: {user[3]}\n"
                f"🎮 Игр сыграно: {user[4]}\n",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
    
    # ===== РЕЙТИНГ =====
    elif data == "leaderboard":
        board = get_leaderboard(10)
        text = "🏆 <b>ТОП-10 игроков</b>\n\n"
        for i, (username, score, games) in enumerate(board, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} {username} - ⭐{score} ({games} игр)\n"
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    # ===== ПОМОЩЬ =====
    elif data == "help":
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "ℹ️ <b>Как играть?</b>\n\n"
            "🎯 Выбирай игры из меню\n"
            "🪙 Зарабатывай монеты за победы\n"
            "⭐ Набирай очки и попадай в топ\n"
            "🏆 Соревнуйся с другими игроками\n\n"
            "💡 <b>Награды:</b>\n"
            "❓ Викторина: +10 монет за вопрос\n"
            "🎯 Виселица: +20 монет за слово\n"
            "🧮 Математика: +5 монет за пример\n"
            "📝 Слова: +2 монеты за слово\n"
            "✊✋✌️ К-Н-Б: +15 монет за победу",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    # ===== ИГРА: ВИКТОРИНА =====
    elif data == "game_quiz":
        question = random.choice(QUIZ_QUESTIONS)
        set_game_state(user_id, {"game": "quiz", "question": question, "score": 0})
        
        keyboard = []
        for i, option in enumerate(question["options"]):
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_answer_{i}")])
        keyboard.append([InlineKeyboardButton("❌ Выход", callback_data="menu_games")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"❓ <b>Викторина</b>\n\n{question['q']}",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    elif data.startswith("quiz_answer_"):
        answer_idx = int(data.split("_")[-1])
        state = get_game_state(user_id)
        
        if state.get("game") == "quiz":
            question = state["question"]
            correct = answer_idx == question["answer"]
            
            if correct:
                update_coins(user_id, 10)
                save_game_score(user_id, "quiz", 10)
                text = "✅ <b>Правильно! +10 монет</b>\n\nИграем дальше?"
            else:
                text = f"❌ <b>Неверно!</b>\nПравильный ответ: {question['options'][question['answer']]}\n\nПопробуешь еще?"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Еще вопрос", callback_data="game_quiz")],
                [InlineKeyboardButton("⬅️ К играм", callback_data="menu_games")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    # ===== ИГРА: ВИСЕЛИЦА =====
    elif data == "game_hangman":
        category = random.choice(list(HANGMAN_WORDS.keys()))
        word = random.choice(HANGMAN_WORDS[category])
        
        set_game_state(user_id, {
            "game": "hangman",
            "word": word,
            "category": category,
            "guessed": set(),
            "attempts": 6
        })
        
        keyboard = [[InlineKeyboardButton("❌ Выход", callback_data="menu_games")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎯 <b>Виселица</b>\n\n"
            f"Категория: {category}\n"
            f"Слово: {' '.join(['_' for _ in word])}\n"
            f"Попыток осталось: 6\n\n"
            f"Отправь букву в чат!",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    # ===== ИГРА: МАТЕМАТИКА =====
    elif data == "game_math":
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        operation = random.choice(['+', '-', '*'])
        
        if operation == '+':
            answer = num1 + num2
        elif operation == '-':
            answer = num1 - num2
        else:
            answer = num1 * num2
        
        set_game_state(user_id, {
            "game": "math",
            "answer": answer,
            "score": 0
        })
        
        keyboard = [[InlineKeyboardButton("❌ Выход", callback_data="menu_games")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🧮 <b>Математика</b>\n\n"
            f"Реши пример:\n"
            f"<code>{num1} {operation} {num2} = ?</code>\n\n"
            f"Отправь ответ числом!",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    # ===== ИГРА: СЛОВА ИЗ СЛОВА =====
    elif data == "game_words":
        word_data = random.choice(WORD_GAME_WORDS)
        
        set_game_state(user_id, {
            "game": "words",
            "main_word": word_data["word"],
            "found_words": set(),
            "min_words": word_data["min_words"]
        })
        
        keyboard = [
            [InlineKeyboardButton("✅ Завершить", callback_data="words_finish")],
            [InlineKeyboardButton("❌ Выход", callback_data="menu_games")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📝 <b>Слова из слова</b>\n\n"
            f"Составь слова из букв:\n"
            f"<b>{word_data['word']}</b>\n\n"
            f"Минимум букв в слове: 3\n"
            f"Цель: найти {word_data['min_words']} слов\n\n"
            f"Отправляй слова в чат!",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    elif data == "words_finish":
        state = get_game_state(user_id)
        if state.get("game") == "words":
            found = len(state["found_words"])
            coins = found * 2
            update_coins(user_id, coins)
            save_game_score(user_id, "words", coins)
            
            keyboard = [
                [InlineKeyboardButton("🔄 Новое слово", callback_data="game_words")],
                [InlineKeyboardButton("⬅️ К играм", callback_data="menu_games")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📝 <b>Результаты</b>\n\n"
                f"Найдено слов: {found}\n"
                f"Награда: +{coins} монет\n\n"
                f"Слова: {', '.join(state['found_words'])}",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            clear_game_state(user_id)
    
    # ===== ИГРА: КАМЕНЬ-НОЖНИЦЫ-БУМАГА =====
    elif data == "game_rps":
        keyboard = [
            [InlineKeyboardButton("✊ Камень", callback_data="rps_rock")],
            [InlineKeyboardButton("✋ Бумага", callback_data="rps_paper")],
            [InlineKeyboardButton("✌️ Ножницы", callback_data="rps_scissors")],
            [InlineKeyboardButton("❌ Выход", callback_data="menu_games")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✊✋✌️ <b>Камень-Ножницы-Бумага</b>\n\n"
            "Выбери свой ход:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    elif data.startswith("rps_"):
        choice = data.split("_")[1]
        bot_choice = random.choice(["rock", "paper", "scissors"])
        
        choices_emoji = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
        choices_ru = {"rock": "Камень", "paper": "Бумага", "scissors": "Ножницы"}
        
        result = ""
        coins = 0
        
        if choice == bot_choice:
            result = "🤝 Ничья!"
        elif (choice == "rock" and bot_choice == "scissors") or \
             (choice == "scissors" and bot_choice == "paper") or \
             (choice == "paper" and bot_choice == "rock"):
            result = "🎉 Ты победил! +15 монет"
            coins = 15
            update_coins(user_id, coins)
            save_game_score(user_id, "rps", 15)
        else:
            result = "😢 Ты проиграл!"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Еще раз", callback_data="game_rps")],
            [InlineKeyboardButton("⬅️ К играм", callback_data="menu_games")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✊✋✌️ <b>Результат</b>\n\n"
            f"Ты: {choices_emoji[choice]} {choices_ru[choice]}\n"
            f"Бот: {choices_emoji[bot_choice]} {choices_ru[bot_choice]}\n\n"
            f"{result}",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().upper()
    state = get_game_state(user_id)
    
    if not state:
        return
    
    # ===== ОБРАБОТКА ВИСЕЛИЦЫ =====
    if state.get("game") == "hangman":
        if len(text) != 1 or not text.isalpha():
            await update.message.reply_text("Отправь одну букву!")
            return
        
        word = state["word"]
        guessed = state["guessed"]
        guessed.add(text)
        
        if text not in word:
            state["attempts"] -= 1
        
        display_word = ' '.join([letter if letter in guessed else '_' for letter in word])
        
        if '_' not in display_word:
            update_coins(user_id, 20)
            save_game_score(user_id, "hangman", 20)
            clear_game_state(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🔄 Новое слово", callback_data="game_hangman")],
                [InlineKeyboardButton("⬅️ К играм", callback_data="menu_games")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🎉 <b>Победа!</b>\n\n"
                f"Слово: {word}\n"
                f"Награда: +20 монет",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        elif state["attempts"] <= 0:
            clear_game_state(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="game_hangman")],
                [InlineKeyboardButton("⬅️ К играм", callback_data="menu_games")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"💀 <b>Проигрыш!</b>\n\n"
                f"Слово было: {word}",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            set_game_state(user_id, state)
            await update.message.reply_text(
                f"🎯 <b>Виселица</b>\n\n"
                f"Слово: {display_word}\n"
                f"Попыток осталось: {state['attempts']}\n"
                f"Использованные буквы: {', '.join(sorted(guessed))}",
                parse_mode='HTML'
            )
    
    # ===== ОБРАБОТКА МАТЕМАТИКИ =====
    elif state.get("game") == "math":
        try:
            user_answer = int(text)
            correct_answer = state["answer"]
            
            if user_answer == correct_answer:
                update_coins(user_id, 5)
                save_game_score(user_id, "math", 5)
                state["score"] += 1
                
                # Новый пример
                num1 = random.randint(1, 20)
                num2 = random.randint(1, 20)
                operation = random.choice(['+', '-', '*'])
                
                if operation == '+':
                    answer = num1 + num2
                elif operation == '-':
                    answer = num1 - num2
                else:
                    answer = num1 * num2
                
                state["answer"] = answer
                set_game_state(user_id, state)
                
                await update.message.reply_text(
                    f"✅ <b>Правильно! +5 монет</b>\n\n"
                    f"Следующий пример:\n"
                    f"<code>{num1} {operation} {num2} = ?</code>",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    f"❌ <b>Неверно!</b>\n"
                    f"Правильный ответ: {correct_answer}",
                    parse_mode='HTML'
                )
        except ValueError:
            await update.message.reply_text("Отправь число!")
    
    # ===== ОБРАБОТКА СЛОВ ИЗ СЛОВА =====
    elif state.get("game") == "words":
        main_word = state["main_word"]
        
        # Проверка что слово состоит из букв основного слова
        if len(text) < 3:
            await update.message.reply_text("Слово должно быть минимум из 3 букв!")
            return
        
        if not all(text.count(letter) <= main_word.count(letter) for letter in set(text)):
            await update.message.reply_text("Используй только буквы из основного слова!")
            return
        
        if text in state["found_words"]:
            await update.message.reply_text("Это слово уже найдено!")
            return
        
        state["found_words"].add(text)
        set_game_state(user_id, state)
        
        await update.message.reply_text(
            f"✅ <b>Слово принято!</b>\n\n"
            f"Найдено слов: {len(state['found_words'])}\n"
            f"Цель: {state['min_words']}",
            parse_mode='HTML'
        )

# ==================== ЗАПУСК БОТА ====================

def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("🤖 Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()