import random
import os
import re
import asyncio
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

from aiogram import Bot, Dispatcher, types

# ===================== НАСТРОЙКИ =====================
TOKEN = os.getenv("BOT_TOKEN")
FILENAME = "ewords.txt"
ACCESS_PASSWORD = "12345"  # пароль для входа
authorized_users = set()    # user_id с доступом

bot = Bot(TOKEN)
dp = Dispatcher()

# ===================== ОНЛАЙН СИНОНИМЫ =====================
ONLINE_CACHE = {}

def get_online_synonyms(word: str, timeout=5):
    """Парсим синонимы с how-to-all.com"""
    if word in ONLINE_CACHE:
        return ONLINE_CACHE[word]

    try:
        url = "https://how-to-all.com/" + requests.utils.quote(f"синонимы:{word}")
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.select("#table1 tbody tr")
        words = []
        for i, row in enumerate(table):
            if i > 1:
                text = row.get_text(strip=True)
                if text:
                    words.append(text.split(" (")[0].lower())

        ONLINE_CACHE[word] = words
        return words
    except:
        return []

# ===================== ТРЕНАЖЁР =====================
class VocabularyTrainer:
    def __init__(self, filename=FILENAME):
        self.filename = filename
        self.vocabulary = {}
        self.load_vocabulary()

    def load_vocabulary(self):
        if not os.path.exists(self.filename):
            raise FileNotFoundError("Нет ewords.txt")
        with open(self.filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if '"' in line:
                    parts = re.findall(r'"[^"]*"|\S+', line)
                    eng = parts[0].strip('"')
                    rus = " ".join(parts[1:])
                else:
                    eng, rus = line.split(" ", 1)
                self.vocabulary[eng] = rus

    def check(self, answer, correct):
        a = answer.lower().strip()
        c = correct.lower().strip()

        # 1. точное совпадение
        if a == c:
            return True, "✓ Правильно"

        # 2. частичные совпадения
        if a in c or c in a:
            return True, f"✓ Почти (частичное совпадение)"

        # 3. похожесть строк
        sim = SequenceMatcher(None, a, c).ratio()
        if sim > 0.65:
            return True, f"✓ Почти ({sim:.0%} совпадение)"

        # 4. Онлайн-синонимы
        online_syns = get_online_synonyms(c)
        if a in online_syns:
            return True, f"✓ Правильно (онлайн-синоним)"

        return False, f"✗ Неправильно\nПравильный ответ: {correct}"

trainer = VocabularyTrainer()

# ===================== СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЕЙ =====================
users = {}  # user_id -> состояние {mode, words, i, correct, awaiting_password}

# ===================== МЕНЮ =====================
def menu():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(text="📘 Учить", callback_data="learn")
    )
    keyboard.add(
        types.InlineKeyboardButton(text="📝 Тест", callback_data="test")
    )
    keyboard.add(
        types.InlineKeyboardButton(text="🎓 Экзамен", callback_data="exam")
    )
    return keyboard

# ===================== ОБРАБОТЧИКИ =====================
@dp.message()
async def start_handler(msg: types.Message):
    uid = msg.from_user.id

    # ----------------- ПРОВЕРКА ПАРОЛЯ -----------------
    if uid in users and users[uid].get("awaiting_password"):
        if msg.text.strip() == ACCESS_PASSWORD:
            authorized_users.add(uid)
            users[uid].pop("awaiting_password")
            await msg.answer("Пароль верный! Добро пожаловать.", reply_markup=menu())
        else:
            await msg.answer("Неверный пароль. Попробуйте ещё раз:")
        return

    # ----------------- ОБРАБОТКА /start -----------------
    if msg.text == "/start":
        if uid in authorized_users:
            await msg.answer("Тренажёр слов. Выбирай режим:", reply_markup=menu())
        else:
            await msg.answer("Введите пароль для доступа:")
            users[uid] = {"awaiting_password": True}
        return

    # ----------------- ОБРАБОТКА ОТВЕТОВ -----------------
    if uid not in users or "mode" not in users[uid]:
        await msg.answer("Введите /start для начала.")
        users[uid] = {}
        return

    u = users[uid]
    if u["i"] >= len(u["words"]):
        await msg.answer(f"Готово.\nПравильных: {u['correct']}/{len(u['words'])}")
        return

    eng, rus = u["words"][u["i"]]
    correct = rus if u["mode"] == "test" else eng
    ok, text = trainer.check(msg.text, correct)
    if ok:
        u["correct"] += 1
    await msg.answer(text)
    u["i"] += 1
    await ask(uid)

# ===================== КОЛБЭКИ =====================
@dp.callback_query()
async def mode_handler(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if uid not in authorized_users:
        await cb.message.answer("Сначала введите правильный пароль через /start")
        return

    if cb.data not in ["learn", "test", "exam"]:
        return

    words = list(trainer.vocabulary.items())
    random.shuffle(words)
    users[uid] = {"mode": cb.data, "words": words, "i": 0, "correct": 0}
    await cb.message.answer("Поехали.")
    await ask(uid)

# ===================== ФУНКЦИЯ ВЫДАЧИ СЛОВ =====================
async def ask(user_id):
    u = users[user_id]
    if u["i"] >= len(u["words"]):
        await bot.send_message(
            user_id,
            f"Готово.\nПравильных: {u['correct']}/{len(u['words'])}"
        )
        return

    eng, rus = u["words"][u["i"]]
    if u["mode"] == "learn":
        await bot.send_message(user_id, f"{eng} — {rus}")
        u["i"] += 1
        await ask(user_id)
    elif u["mode"] == "test":
        await bot.send_message(user_id, f"{eng} — ?")
    else:  # exam
        await bot.send_message(user_id, f"{rus} — ?")

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("Бот запущен...")
    try:
        asyncio.run(dp.start_polling(bot))
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
