import json
import asyncio
import re
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from aiogram.filters import Command, CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename="bot.log",
    filemode="a"
)

API_TOKEN = '8316022324:AAGzMYcAbYNPTKLQD92RmeqiEyth3D2WiJk'
ADMIN_ID = 5675745209  # ваш Telegram ID

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

SCHEDULE_FILE = 'schedule.json'
EVEN_DAYS = [1, 3, 5]  # вторник, четверг, суббота (0-пн)
ADMINS_FILE = 'admins.json'
LOG_CHAT_ID = -1002732362235

# Для хранения id сообщения с графиком каждого админа
ADMINS_LOG_MSGS_FILE = 'admins_log_msgs.json'

WEEKDAYS_RU = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье"
}

USERS_FILE = "users.json"

def load_admins():
    try:
        with open(ADMINS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_admins(data):
    with open(ADMINS_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_admin_log_msgs():
    try:
        with open(ADMINS_LOG_MSGS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_admin_log_msgs(data):
    with open(ADMINS_LOG_MSGS_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# --- FSM для записи ---
class UchStates(StatesGroup):
    waiting_for_day = State()
    waiting_for_time = State()
    waiting_for_topic = State()
    waiting_for_name = State()

class EditStates(StatesGroup):
    choosing_field = State()
    editing_topic = State()
    editing_time = State()
    editing_name = State()
    editing_join = State()

class WorkStates(StatesGroup):
    choosing_days = State()
    choosing_start_date = State()
    choosing_end_date = State()
    choosing_hours = State()
    confirming = State()

WORK_MODES = {
    "even": [1, 3, 5],      # вторник, четверг, суббота
    "odd": [0, 2, 4],       # понедельник, среда, пятница
    "all": [0, 1, 2, 3, 4, 5], # все кроме воскресенья
}

def get_schedule_file(user_id):
    return f"schedule_{user_id}.json"

def load_schedule(user_id=None):
    if user_id is None:
        user_id = ADMIN_ID
    fname = get_schedule_file(user_id)
    try:
        with open(fname, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_schedule(data, user_id=None):
    if user_id is None:
        user_id = ADMIN_ID
    fname = get_schedule_file(user_id)
    with open(fname, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_next_even_days():
    today = datetime.now()
    days = []
    for i in range(7):
        day = today + timedelta(days=i)
        if day.weekday() in EVEN_DAYS:
            days.append(day)
    return days

def sort_slots_by_time(slots):
    def time_key(slot):
        # Ожидается формат "HH:MM - HH:MM"
        try:
            return datetime.strptime(slot['time'].split('-')[0].strip(), "%H:%M")
        except Exception:
            return datetime.min
    return sorted(slots, key=time_key)

def format_schedule(user_id):
    data = load_schedule(user_id)
    days = get_next_even_days()
    result = "График работы:\n"
    for day in days:
        d_str = f"{WEEKDAYS_RU[day.weekday()]} ({day.strftime('%d.%m.%Y')})"
        result += f"\n<b>{d_str}</b>:\n"
        slots = sort_slots_by_time(data.get(day.strftime('%d.%m.%Y'), []))
        if not slots:
            result += "  Все слоты свободны✅\n"
        else:
            for slot in slots:
                result += (
                    f"  <b>📚Тема:</b> {slot['topic']}\n"
                    f"  <b>⏳Время:</b> {slot['time']}\n"
                    f"  <b>⭐️Имя:</b> {slot['name']}\n"
                    f"  <b>⚡️Присоединяются:</b> {', '.join(slot['join']) if slot['join'] else 'пока нету'}\n\n"
                )
    return result

def is_admin(msg):
    admins = load_admins()
    return str(msg.from_user.id) in admins

def is_owner(msg):
    return msg.from_user.id == ADMIN_ID


@dp.message(Command("new"))
async def new_entry(msg: types.Message, state: FSMContext):
    if not is_admin(msg):
        await msg.answer("Вы не добавлены как админ.")
        return
    kb = days_keyboard(str(msg.from_user.id))
    await msg.answer("Выберите день для записи:", reply_markup=kb)
    await state.set_state(UchStates.waiting_for_day)

def days_keyboard(admin_id=None):
    if admin_id is None:
        admin_id = ADMIN_ID
    work = load_work_settings(admin_id)
    mode = work['mode'] if work else "even"
    days = get_current_week_days(mode, admin_id)
    buttons = []
    for day in days:
        buttons.append([
            InlineKeyboardButton(
                text=f"{WEEKDAYS_RU[day.weekday()]} {day.strftime('%d.%m')}",
                callback_data=f"day_{day.strftime('%d.%m.%Y')}"
            )
        ])
    # Только кнопка "Назад"
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="new_back")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

# --- Меню администратора ---
@dp.message(Command("mymenu"))
async def admin_menu(msg: types.Message):
    if not is_admin(msg):
        await msg.answer("Вы не добавлены как админ.")
        return
    admin_id = str(msg.from_user.id)
    work = load_work_settings(admin_id)
    mode = work['mode'] if work else "even"
    days = get_current_week_days(mode, admin_id)
    buttons = []
    for day in days:
        buttons.append([
            InlineKeyboardButton(
                text=f"{WEEKDAYS_RU[day.weekday()]} {day.strftime('%d.%m')}",
                callback_data=f"admin_day_{day.strftime('%d.%m.%Y')}"
            )
        ])
    # Оставляем только кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await msg.answer("Выберите день для просмотра/редактирования:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "menu_back")
async def menu_back(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Действие отменено. Вы вернулись в главное меню.")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "menu_cancel")
async def menu_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Действие отменено.")
    await state.clear()
    await callback.answer()

# --- Просмотр и редактирование дня ---
@dp.callback_query(lambda c: c.data.startswith("admin_day_"))
async def admin_day_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    admin_id = str(callback.from_user.id)
    day = callback.data.replace("admin_day_", "")
    schedule = load_schedule(admin_id)
    slots = sort_slots_by_time(schedule.get(day, []))
    weekday_ru = WEEKDAYS_RU[datetime.strptime(day, "%d.%m.%Y").weekday()]
    text = f"<b>{weekday_ru} ({day})</b>:\n"
    buttons = []
    for idx, slot in enumerate(slots):
        text += (
            f"  📚Тема: {slot['topic']}\n"
            f"  ⏳Время: {slot['time']}\n"
            f"  ⭐️{slot['name']}\n"
            f"  ⚡️Присоединяются: {', '.join(slot['join']) if slot['join'] else 'пока нету'}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Редактировать {slot['time']}",
                callback_data=f"edit_{day}_{idx}"
            ),
            InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"delete_{day}_{idx}"
            )
        ])
    # Кнопка "Добавить ученика" над кнопкой "Назад"
    buttons.append([
        InlineKeyboardButton(
            text="➕ Добавить ученика",
            callback_data=f"add_student_{day}"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_menu"
        )
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await callback.message.edit_text(text or "Нет записей", parse_mode='HTML', reply_markup=kb)
    await callback.answer()
    
@dp.callback_query(lambda c: c.data.startswith("add_student_"))
async def add_student_start(callback: types.CallbackQuery, state: FSMContext):
    day = callback.data.replace("add_student_", "")
    await state.update_data(day=day)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_day_{day}")]
        ]
    )
    msg = await callback.message.edit_text(
        f"Добавление ученика в {day}\nВведите время (например, 12:00 - 13:00):",
        reply_markup=kb
    )
    await state.update_data(prev_msg_id=msg.message_id)
    await state.set_state(UchStates.waiting_for_time)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    admin_id = str(callback.from_user.id)
    work = load_work_settings(admin_id)
    mode = work['mode'] if work else "even"
    days = get_current_week_days(mode, admin_id)
    buttons = []
    for day in days:
        buttons.append([
            InlineKeyboardButton(
                text=f"{WEEKDAYS_RU[day.weekday()]} {day.strftime('%d.%m')}",
                callback_data=f"admin_day_{day.strftime('%d.%m.%Y')}"
            )
        ])
    # Оставляем только кнопку "Назад"
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await callback.message.edit_text("Выберите день для просмотра/редактирования:", reply_markup=kb)
    await callback.answer()

# --- Меню выбора поля для редактирования ---
@dp.callback_query(lambda c: re.fullmatch(r"edit_\d{2}\.\d{2}\.\d{4}_\d+", c.data))
async def edit_menu(callback: types.CallbackQuery, state: FSMContext):
    _, day, idx = callback.data.split("_", 2)
    await state.update_data(day=day, idx=int(idx))
    buttons = [
        [InlineKeyboardButton(text="Тема", callback_data="edit_field_topic")],
        [InlineKeyboardButton(text="Время", callback_data="edit_field_time")],
        [InlineKeyboardButton(text="Имя", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="Присоединяющиеся", callback_data="edit_field_join")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_day_{day}")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("Что редактировать?", reply_markup=kb)
    await state.set_state(EditStates.choosing_field)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_field_"))
async def choose_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_field_", "")
    data = await state.get_data()
    day = data['day']
    idx = data['idx']
    admin_id = str(callback.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(day)
    if not slots or idx >= len(slots):
        await callback.message.edit_text("Ошибка: запись не найдена.")
        await state.clear()
        await callback.answer()
        return
    slot = slots[idx]
    if field == "topic":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"edit_{day}_{idx}")]
            ]
        )
        msg = await callback.message.edit_text(
            f"Старая тема: {slot['topic']}\nВведите новую тему:",
            reply_markup=kb
        )
        await state.update_data(prev_msg_id=msg.message_id)
        await state.set_state(EditStates.editing_topic)
    elif field == "time":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"edit_{day}_{idx}")]
            ]
        )
        msg = await callback.message.edit_text(
            f"Старая время: {slot['time']}\nВведите новое время:",
            reply_markup=kb
        )
        await state.update_data(prev_msg_id=msg.message_id)
        await state.set_state(EditStates.editing_time)
    elif field == "name":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"edit_{day}_{idx}")]
            ]
        )
        msg = await callback.message.edit_text(
            f"Старая имя: {slot['name']}\nВведите новое имя:",
            reply_markup=kb
        )
        await state.update_data(prev_msg_id=msg.message_id)
        await state.set_state(EditStates.editing_name)
    elif field == "join":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"edit_{day}_{idx}")]
            ]
        )
        msg = await callback.message.edit_text(
            f"Старые присоединяющиеся: {', '.join(slot['join']) if slot['join'] else 'пока нету'}\n"
            "Введите новые имена через запятую:",
            reply_markup=kb
        )
        await state.update_data(prev_msg_id=msg.message_id)
        await state.set_state(EditStates.editing_join)
    await callback.answer()

@dp.message(EditStates.editing_topic)
async def edit_topic(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    admin_id = str(msg.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(data['day'])
    if not slots or data['idx'] >= len(slots):
        await msg.answer("Ошибка: запись не найдена.")
        await state.clear()
        return
    slots[data['idx']]['topic'] = msg.text
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    new_msg = await msg.answer("Тема обновлена!")
    await state.update_data(prev_msg_id=new_msg.message_id)
    await state.clear()

@dp.message(EditStates.editing_time)
async def edit_time(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    admin_id = str(msg.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(data['day'])
    if not slots or data['idx'] >= len(slots):
        await msg.answer("Ошибка: запись не найдена.")
        await state.clear()
        return
    # Проверка формата времени
    start, end = parse_time_range(msg.text)
    if not start or not end:
        await msg.answer("Ошибка! Введите время в формате: 12:00 - 13:00")
        return
    slots[data['idx']]['time'] = msg.text
    # Пересортировать слоты по времени
    slots_sorted = sort_slots_by_time(slots)
    schedule[data['day']] = slots_sorted
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    new_msg = await msg.answer("Время обновлено!")
    await state.update_data(prev_msg_id=new_msg.message_id)
    await state.clear()

@dp.message(EditStates.editing_name)
async def edit_name(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    admin_id = str(msg.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(data['day'])
    if not slots or data['idx'] >= len(slots):
        await msg.answer("Ошибка: запись не найдена.")
        await state.clear()
        return
    slots[data['idx']]['name'] = msg.text
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    new_msg = await msg.answer("Имя обновлено!")
    await state.update_data(prev_msg_id=new_msg.message_id)
    await state.clear()

@dp.message(EditStates.editing_join)
async def edit_join(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    idx = data['idx']
    day = data['day']
    names = [n.strip() for n in msg.text.split(",") if n.strip()]
    admin_id = str(msg.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(day)
    if not slots or idx >= len(slots):
        await msg.answer("Ошибка: запись не найдена.")
        await state.clear()
        return
    slot = slots[idx]
    slot['join'] = names
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)  # <-- добавлено
    new_msg = await msg.answer("Список присоединяющихся обновлён!")
    await state.update_data(prev_msg_id=new_msg.message_id)
    await state.clear()

def save_work_settings(admin_id, mode, intervals):
    fname = f"work_{admin_id}.json"
    with open(fname, "w") as f:
        json.dump({
            "mode": mode,
            "intervals": intervals  # список пар (start, end)
        }, f)

def load_work_settings(admin_id):
    fname = f"work_{admin_id}.json"
    try:
        with open(fname, "r") as f:
            return json.load(f)
    except Exception:
        return None

def get_days_by_mode(mode):
    days = []
    today = datetime.now()
    for i in range(7):
        day = today + timedelta(days=i)
        if day.weekday() in WORK_MODES[mode]:
            days.append(day)
    return days

def get_free_slots(slots, intervals):
    busy = []
    for slot in slots:
        s, e = parse_time_range(slot['time'])
        busy.append((s, e))
    free = []
    for start_hour, end_hour in intervals:
        current = datetime.strptime(start_hour, "%H:%M").time()
        end = datetime.strptime(end_hour, "%H:%M").time()
        for s, e in busy:
            if current < s and s < end:
                free.append((current, s))
            current = max(current, e)
        if current < end:
            free.append((current, end))
    return free

def format_day_with_free(day, slots, intervals):
    """
    Формирует текст для одного дня, показывая свободные интервалы между занятиями и рабочими интервалами.
    """
    text = ""
    slots = sort_slots_by_time(slots)
    # Собираем все busy интервалы
    busy = []
    for slot in slots:
        s, e = parse_time_range(slot['time'])
        busy.append((s, e))
    # Собираем все рабочие интервалы в один список
    all_intervals = []
    for start_hour, end_hour in intervals:
        start = datetime.strptime(start_hour, "%H:%M").time()
        end = datetime.strptime(end_hour, "%H:%M").time()
        all_intervals.append((start, end))
    # Собираем все события (начало/конец рабочего интервала и занятого слота)
    events = []
    for start, end in all_intervals:
        events.append(('work_start', start))
        events.append(('work_end', end))
    for s, e in busy:
        events.append(('busy_start', s))
        events.append(('busy_end', e))
    # Сортируем события по времени
    events.sort(key=lambda x: x[1])
    # Теперь проходим по рабочим интервалам и слотам, выводим свободные окна и записи
    for start, end in all_intervals:
        prev_end = start
        for slot in slots:
            s, e = parse_time_range(slot['time'])
            # Если слот внутри текущего рабочего интервала
            if s >= start and e <= end:
                if prev_end < s:
                    text += f"  🟢 Свободно: {prev_end.strftime('%H:%M')} - {s.strftime('%H:%M')}\n\n"
                text += (
                    f"  <b>📚Тема:</b> {slot['topic']}\n"
                    f"  <b>⏳Время:</b> {slot['time']}\n"
                    f"  <b>⭐️Имя:</b> {slot['name']}\n"
                    f"  <b>⚡️Присоединяются:</b> {', '.join(slot['join']) if slot['join'] else 'пока нету'}\n\n"
                )
                prev_end = max(prev_end, e)
        if prev_end < end:
            text += f"  🟢 Свободно: {prev_end.strftime('%H:%M')} - {end.strftime('%H:%M')}\n\n"
    return text

def format_schedule_with_free(user_id):
    data = load_schedule(user_id)
    work = load_work_settings(user_id)
    if not work:
        return "График не настроен."
    days = get_current_week_days(work['mode'], user_id)
    intervals = work.get('intervals', [])
    result = "График работы:\n"
    for day in days:
        d_str = f"{WEEKDAYS_RU[day.weekday()]} ({day.strftime('%d.%m.%Y')})"
        result += f"\n<b>{d_str}</b>:\n"
        slots = sort_slots_by_time(data.get(day.strftime('%d.%m.%Y'), []))
        result += format_day_with_free(day.strftime('%d.%m.%Y'), slots, intervals)
    return result

async def send_or_update_admin_schedule(admin_id, admin_name, bot):
    text = (
        f"<b>График кругляшка</b> <a href=\"tg://user?id={admin_id}\">{admin_name}</a>:\n\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Написать для записи", url=f"tg://user?id={admin_id}")]
        ]
    )
    text += format_schedule_with_free(admin_id).replace("График работы:\n", "")
    log_msgs = load_admin_log_msgs()
    msg_id = log_msgs.get(str(admin_id))
    try:
        if msg_id:
            # Получаем текущее сообщение
            # Если текст и клавиатура не изменились — не редактируем
            # (Можно просто обернуть edit_message_text в try/except и игнорировать эту ошибку)
            try:
                await bot.edit_message_text(
                    chat_id=LOG_CHAT_ID,
                    message_id=msg_id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=kb    
                )
            except Exception as e:
                if "message is not modified" not in str(e):
                    logging.error(f"Ошибка при обновлении сообщения: {e}")
        else:
            msg = await bot.send_message(
                chat_id=LOG_CHAT_ID,
                text=text,
                parse_mode='HTML',
                reply_markup=kb
            )
            log_msgs[str(admin_id)] = msg.message_id
            save_admin_log_msgs(log_msgs)
    except Exception as e:
        logging.error(f"Ошибка при обновлении сообщения: {e}")
        try:
            await bot.send_message(
                admin_id,
                f"Ошибка при отправке графика: {e}"
            )
        except Exception:
            pass

@dp.message(Command("addadmin"))
async def add_admin(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("Нет доступа.")
        return
    parts = msg.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer("Используй: /addadmin <id> <имя>")
        return
    admin_id, admin_name = parts[1], parts[2]
    admins = load_admins()
    admins[admin_id] = admin_name
    save_admins(admins)
    # Очищаем расписание
    schedule_file = get_schedule_file(admin_id)
    if os.path.exists(schedule_file):
        os.remove(schedule_file)
    save_schedule({}, admin_id)
    # Удаляем старое сообщение в лог-чате, если было
    log_msgs = load_admin_log_msgs()
    msg_id = log_msgs.pop(admin_id, None)
    if msg_id:
        try:
            await bot.delete_message(LOG_CHAT_ID, msg_id)
        except Exception:
            pass
    save_admin_log_msgs(log_msgs)
    await msg.answer(f"Админ {admin_name} (id={admin_id}) добавлен!")
    # Отправить админу инструкцию
    await bot.send_message(
        int(admin_id),
        "Вы добавлены как админ!\nДля настройки графика работы используйте команду /work."
    )

@dp.callback_query(lambda c: c.data.startswith("work_"))
async def choose_work_mode(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.replace("work_", "")
    await state.update_data(mode=mode)
    await callback.message.edit_text(
        "Введите дату начала недели (например, 19.08.2025):"
    )
    await state.set_state(WorkStates.choosing_start_date)
    await callback.answer()

@dp.message(WorkStates.choosing_start_date)
async def choose_start_date(msg: types.Message, state: FSMContext):
    try:
        start_date = datetime.strptime(msg.text.strip(), "%d.%m.%Y")
    except Exception:
        await msg.answer("Ошибка! Введите дату в формате: 19.08.2025")
        return
    await state.update_data(start_date=start_date.strftime("%Y-%m-%d"))
    await msg.answer("Введите дату конца недели (например, 25.08.2025):")
    await state.set_state(WorkStates.choosing_end_date)

@dp.message(WorkStates.choosing_end_date)
async def choose_end_date(msg: types.Message, state: FSMContext):
    try:
        end_date = datetime.strptime(msg.text.strip(), "%d.%m.%Y")
    except Exception:
        await msg.answer("Ошибка! Введите дату в формате: 25.08.2025")
        return
    await state.update_data(end_date=end_date.strftime("%Y-%m-%d"))
    await msg.answer("Введите рабочие часы в формате: HH:MM - HH:MM\nНапример: 10:00 - 18:00")
    await state.set_state(WorkStates.choosing_hours)

@dp.message(WorkStates.choosing_hours)
async def choose_work_hours(msg: types.Message, state: FSMContext):
    # Пример: "12:00-16:00, 18:00-19:30"
    intervals = [s.strip() for s in msg.text.split(",") if s.strip()]
    parsed = []
    for interval in intervals:
        try:
            start, end = interval.split('-')
            start = datetime.strptime(start.strip(), "%H:%M").time()
            end = datetime.strptime(end.strip(), "%H:%M").time()
            parsed.append((start.strftime("%H:%M"), end.strftime("%H:%M")))
        except Exception:
            await msg.answer("Ошибка! Введите интервалы в формате: 12:00-16:00, 18:00-19:30")
            return
    data = await state.get_data()
    mode = data.get('mode')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    if not (mode and start_date and end_date):
        await msg.answer("Сначала выберите режим работы и даты.")
        return
    admin_id = str(msg.from_user.id)
    # Сохраняем интервалы!
    save_work_settings(admin_id, mode, parsed)
    save_week_start(admin_id, datetime.strptime(start_date, "%Y-%m-%d"))
    with open(f"week_{admin_id}.json", "w") as f:
        json.dump({"start": start_date, "end": end_date}, f)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    intervals_str = ', '.join([f"{s}-{e}" for s, e in parsed])
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    await msg.answer(
        f"Режим работы: {mode}\nЧасы: {intervals_str}\n"
        f"Неделя: {start_date} — {end_date}\n\nГрафик сохранён и отправлен!\nДля изменения используйте /work."
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "work_confirm")
async def confirm_work(callback: types.CallbackQuery, state: FSMContext):
    admin_id = str(callback.from_user.id)
    admins = load_admins()
    if admin_id not in admins:
        await callback.message.edit_text(
            "Вы не добавлены как админ. Используйте /addadmin <id> <имя> чтобы добавить себя.",
            reply_markup=None
        )
        await state.clear()
        await callback.answer()
        return
    data = await state.get_data()
    mode = data.get('mode')
    start_hour = data.get('start_hour')
    end_hour = data.get('end_hour')
    if not (mode and start_hour and end_hour):
        await callback.message.edit_text(
            "Ошибка: не выбраны режим и часы работы. Начните заново с /work.",
            reply_markup=None
        )
        await state.clear()
        await callback.answer()
        return
    save_work_settings(admin_id, mode, start_hour, end_hour)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    # Удаляем клавиатуру и делаем сообщение финальным
    await callback.message.edit_text(
        "График сохранён и отправлен!\n\nЕсли хотите изменить режим работы, используйте команду /work.",
        reply_markup=None
    )
    await state.clear()
    await callback.answer()

@dp.message(Command("work"))
async def change_work(msg: types.Message, state: FSMContext):
    if not is_admin(msg):
        await msg.answer("Нет доступа.")
        return
    await msg.answer(
        "Выберите режим работы:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Чётные дни (Вт, Чт, Сб)", callback_data="work_even")],
                [InlineKeyboardButton(text="Нечётные дни (Пн, Ср, Пт)", callback_data="work_odd")],
                [InlineKeyboardButton(text="Каждый день кроме вс", callback_data="work_all")]
            ]
        )
    )
    await state.set_state(WorkStates.choosing_days)

@dp.message(Command("admins"))
async def show_admins(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("Нет доступа.")
        return
    admins = load_admins()
    if not admins:
        await msg.answer("Админы не добавлены.")
        return
    text = "Список админов:\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for admin_id, admin_name in admins.items():
        text += f"{admin_name} — <code>{admin_id}</code> — <a href=\"tg://user?id={admin_id}\">профиль</a>\n"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"deladmin_{admin_id}")
        ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="addadmin_btn")
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("deladmin_"))
async def delete_admin(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.")
        return
    admin_id = callback.data.replace("deladmin_", "")
    admins = load_admins()
    if admin_id in admins:
        admins.pop(admin_id)
        save_admins(admins)
        await callback.answer("Админ удалён!")
        # Показываем обновлённый список админов
        text = "Список админов:\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for aid, aname in admins.items():
            text += f"{aname} — <code>{aid}</code> — <a href=\"tg://user?id={aid}\">профиль</a>\n"
            kb.inline_keyboard.append([
                InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"deladmin_{aid}")
            ])
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="➕ Добавить", callback_data="addadmin_btn")
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await callback.answer("Админ не найден.")

@dp.callback_query(lambda c: c.data == "addadmin_btn")
async def add_admin_btn(callback: types.CallbackQuery):
    await callback.message.answer("Используйте команду:\n/addadmin <id> <имя>")
    await callback.answer()

@dp.message(Command("restart"))
async def restart_all(msg: types.Message):
    if not is_owner(msg):
        await msg.answer("Нет доступа.")
        return

    admins = load_admins()
    log_msgs = load_admin_log_msgs()
    result = []

    # Удалить сообщения графиков в лог-чате
    for admin_id, msg_id in log_msgs.items():
        try:
            await bot.delete_message(LOG_CHAT_ID, msg_id)
            result.append(f"Удалено сообщение графика {msg_id} для админа {admin_id}")
        except Exception as e:
            result.append(f"Ошибка удаления сообщения {msg_id}: {e}")

    # Удалить все файлы расписаний и рабочих часов
    for admin_id in admins.keys():
        schedule_file = get_schedule_file(admin_id)
        if os.path.exists(schedule_file):
            os.remove(schedule_file)
            result.append(f"Удалён файл расписания {schedule_file}")
        work_file = f"work_{admin_id}.json"
        if os.path.exists(work_file):
            os.remove(work_file)
            result.append(f"Удалён файл рабочих часов {work_file}")

    # Очистить файлы
    save_admin_log_msgs({})

    # Создать пустые расписания
    for admin_id in admins.keys():
        save_schedule({}, admin_id)

    # Отправить каждому админу личное сообщение с просьбой настроить график
    for admin_id, admin_name in admins.items():
        asyncio.create_task(
            bot.send_message(
                int(admin_id),
                "Ваш график был сброшен! Пожалуйста, заново настройте рабочие дни и часы через команду /work."
            )
        )
        result.append(f"Запланировано сообщение админу {admin_id}")

    await msg.answer(
        "Все графики админов сброшены! Каждый админ должен заново настроить график через команду /work.\n\n" +
        "\n".join(result)
    )


def get_current_week_days(mode, admin_id=None):
    if admin_id is None:
        admin_id = ADMIN_ID
    start = load_week_start(admin_id)
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        if day.weekday() in WORK_MODES[mode]:
            days.append(day)
    return days

def save_week_start(admin_id, date):
    fname = f"week_{admin_id}.json"
    with open(fname, "w") as f:
        json.dump({"start": date.strftime("%Y-%m-%d")}, f)

def load_week_start(admin_id):
    fname = f"week_{admin_id}.json"
    try:
        with open(fname, "r") as f:
            data = json.load(f)
            return datetime.strptime(data["start"], "%Y-%m-%d")
    except Exception:
        # По умолчанию — текущая неделя
        today = datetime.now()
        return today - timedelta(days=today.weekday())

@dp.callback_query(lambda c: re.fullmatch(r"delete_\d{2}\.\d{2}\.\d{4}_\d+", c.data))
async def delete_slot(callback: types.CallbackQuery, state: FSMContext):
    _, day, idx = callback.data.split("_", 2)
    idx = int(idx)
    admin_id = str(callback.from_user.id)
    schedule = load_schedule(admin_id)
    slots = schedule.get(day, [])
    if not slots or idx >= len(slots):
        await callback.answer("Ошибка: запись не найдена.", show_alert=True)
        return
    slots.pop(idx)
    schedule[day] = slots
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    await callback.answer("Запись удалена!")
    # Показываем обновлённый день
    slots = sort_slots_by_time(schedule.get(day, []))
    text = f"<b>{day}</b>:\n"
    buttons = []
    for idx, slot in enumerate(slots):
        text += (
            f"  📚Тема: {slot['topic']}\n"
            f"  ⏳Время: {slot['time']}\n"
            f"  ⭐️{slot['name']}\n"
            f"  ⚡️Присоединяются: {', '.join(slot['join']) if slot['join'] else 'пока нету'}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Редактировать {slot['time']}",
                callback_data=f"edit_{day}_{idx}"
            ),
            InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"delete_{day}_{idx}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_menu"
        )
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await callback.message.edit_text(text or "Нет записей", parse_mode='HTML', reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("day_"))
async def uch_choose_day(callback: types.CallbackQuery, state: FSMContext):
    day = callback.data.replace("day_", "")
    await state.update_data(day=day)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="new_back")]
        ]
    )
    msg = await callback.message.edit_text(
        f"Выбран день: {day}\nВведите время (например, 12:00 - 13:00):",
        reply_markup=kb
    )
    await state.update_data(prev_msg_id=msg.message_id)
    await state.set_state(UchStates.waiting_for_time)
    await callback.answer()

@dp.message(UchStates.waiting_for_time)
async def uch_get_time(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    start, end = parse_time_range(msg.text)
    kb = uch_cancel_keyboard()
    admin_id = str(msg.from_user.id)
    work = load_work_settings(admin_id)
    intervals = work.get('intervals', []) if work else []
    # Проверка: входит ли выбранное время в рабочие интервалы
    in_work_time = False
    for interval_start, interval_end in intervals:
        interval_start = datetime.strptime(interval_start, "%H:%M").time()
        interval_end = datetime.strptime(interval_end, "%H:%M").time()
        if start and end and start >= interval_start and end <= interval_end:
            in_work_time = True
            break
    if not start or not end:
        new_msg = await msg.answer("Ошибка! Введите время в формате: 12:00 - 13:00", reply_markup=kb)
        await state.update_data(prev_msg_id=new_msg.message_id)
        return
    if not in_work_time:
        new_msg = await msg.answer("Ошибка! Выбранное время не входит в рабочие часы администратора.", reply_markup=kb)
        await state.update_data(prev_msg_id=new_msg.message_id)
        return
    new_msg = await msg.answer("Введите тему занятия:", reply_markup=kb)
    await state.update_data(time=msg.text, prev_msg_id=new_msg.message_id)
    await state.set_state(UchStates.waiting_for_topic)

@dp.message(UchStates.waiting_for_topic)
async def uch_get_topic(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    new_msg = await msg.answer("Введите имя ученика:", reply_markup=uch_cancel_keyboard())
    await state.update_data(topic=msg.text, prev_msg_id=new_msg.message_id)
    await state.set_state(UchStates.waiting_for_name)

@dp.message(UchStates.waiting_for_name)
async def uch_get_name(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    prev_msg_id = data.get('prev_msg_id')
    if prev_msg_id:
        try:
            await bot.delete_message(msg.chat.id, prev_msg_id)
        except Exception:
            pass
    admin_id = str(msg.from_user.id)
    schedule = load_schedule(admin_id)
    day = data['day']
    slot = {
        "topic": data['topic'],
        "time": data['time'],
        "name": msg.text,
        "join": []
    }
    # Проверка на совпадение времени
    for existing in schedule.get(day, []):
        if existing['time'] == slot['time']:
            await msg.answer("Запись с таким временем уже существует! Измените время или отредактируйте существующую запись.")
            await state.clear()
            return
    if day not in schedule:
        schedule[day] = []
    schedule[day].append(slot)
    logging.info(f"Добавлена запись: {slot} для дня {day} пользователем {admin_id}")
    schedule[day] = sort_slots_by_time(schedule[day])
    save_schedule(schedule, admin_id)
    admins = load_admins()
    admin_name = admins.get(admin_id, "Без имени")
    await send_or_update_admin_schedule(admin_id, admin_name, bot)
    await msg.answer("Запись добавлена!")
    await state.clear()

def uch_cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="new_back")]
        ]
    )

@dp.callback_query(lambda c: c.data == "uch_cancel")
async def uch_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Действие отменено.")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "new_back")
async def uch_back(callback: types.CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    data = await state.get_data()
    admin_id = str(callback.from_user.id)
    kb = days_keyboard(admin_id)
    if current_state == UchStates.waiting_for_time.state:
        # Возврат к выбору дня
        await callback.message.edit_text("Выберите день для записи:", reply_markup=kb)
        await state.set_state(UchStates.waiting_for_day)
    elif current_state == UchStates.waiting_for_topic.state:
        # Возврат к выбору времени
        day = data.get('day')
        kb_time = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="new_back")]
            ]
        )
        await callback.message.edit_text(
            f"Выбран день: {day}\nВведите время (например, 12:00 - 13:00):",
            reply_markup=kb_time
        )
        await state.set_state(UchStates.waiting_for_time)
    elif current_state == UchStates.waiting_for_name.state:
        # Возврат к выбору темы
        kb_topic = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="new_back")]
            ]
        )
        await callback.message.edit_text(
            "Введите тему занятия:",
            reply_markup=kb_topic
        )
        await state.set_state(UchStates.waiting_for_topic)
    else:
        # Если уже на выборе дня или состояние сброшено
        await callback.message.edit_text("Вы вернулись назад.")
        await state.clear()
    await callback.answer()

def parse_time_range(time_str):
    """
    Парсит строку времени формата "HH:MM - HH:MM" и возвращает кортеж (start, end) как объекты времени.
    Если формат неверный, возвращает (None, None).
    """
    try:
        parts = re.split(r"\s*-\s*", time_str)
        if len(parts) != 2:
            return None, None
        start = datetime.strptime(parts[0], "%H:%M").time()
        end = datetime.strptime(parts[1], "%H:%M").time()
        return start, end
    except Exception:
        return None, None

@dp.message(Command("help"))
async def help_command(msg: types.Message):
    text = (
        "<b>Инструкция для админов:</b>\n\n"
        "1️⃣ <b>/mymenu</b> — открыть меню редактирования своего расписания:\n"
        "• Выберите день недели.\n"
        "• Редактируйте, удаляйте или добавляйте записи.\n"
        "• Можно добавить ученика прямо в выбранный день.\n"
        "• Для каждой записи доступны редактирование темы, времени, имени и списка присоединяющихся.\n"
        "2️⃣ <b>/new</b> — добавить новую запись в расписание:\n"
        "• Выберите день, время, тему и имя ученика.\n"
        "• Проверяется рабочее время и занятость слота.\n"
        "3️⃣ <b>/work</b> — настроить рабочие дни и интервалы времени.\n"
        "• Выберите режим (чётные/нечётные/все дни).\n"
        "• Укажите даты недели и рабочие часы.\n"
        "4️⃣ <b>Кнопка \"Назад\"</b> — возвращает на предыдущий шаг в любом меню.\n\n"
        "<b>Прочее:</b>\n"
        "• Все действия автоматически обновляют график в лог-чате.\n"
        "• При добавлении записи вне рабочего времени появится ошибка.\n"
        "• Для связи с админом используйте кнопку \"📝 Написать для записи\" в графике.\n"
        "• Если возникли вопросы — обратитесь к владельцу бота.\n"
    )
    await msg.answer(text, parse_mode="HTML")

@dp.message(Command("users"))
async def show_users(msg: types.Message):
    users = load_users()
    if not users:
        await msg.answer("Пользователи не найдены.")
        return
    text = "<b>Пользователи бота:</b>\n\n"
    for uid, info in users.items():
        username = info.get('username', '')
        first_name = info.get('first_name', '')
        last_name = info.get('last_name', '')
        started = info.get('started', 'неизвестно')
        profile_link = f'<a href="tg://user?id={uid}">профиль</a>'
        text += (
            f"👤 <b>{first_name} {last_name}</b>\n"
            f"🆔 <code>{uid}</code>\n"
            f"🔗 @{username if username else 'нет'} | {profile_link}\n"
            f"📅 Первый запуск: <code>{started}</code>\n\n"
        )
    await msg.answer(text, parse_mode="HTML")

@dp.message()
async def register_user(msg: types.Message):
    users = load_users()
    uid = str(msg.from_user.id)
    if uid not in users:
        users[uid] = {
            "username": msg.from_user.username if msg.from_user.username else "",
            "first_name": msg.from_user.first_name,
            "last_name": msg.from_user.last_name,
            "started": datetime.now().strftime("%d.%m.%Y %H:%M")
        }
        save_users(users)
    else:
        # Обновляем данные, если вдруг username появился или изменился
        updated = False
        if users[uid].get("username", "") != (msg.from_user.username if msg.from_user.username else ""):
            users[uid]["username"] = msg.from_user.username if msg.from_user.username else ""
            updated = True
        if users[uid].get("first_name", "") != msg.from_user.first_name:
            users[uid]["first_name"] = msg.from_user.first_name
            updated = True
        if users[uid].get("last_name", "") != msg.from_user.last_name:
            users[uid]["last_name"] = msg.from_user.last_name
            updated = True
        if updated:
            save_users(users)

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
