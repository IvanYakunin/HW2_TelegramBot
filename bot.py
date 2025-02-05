import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import matplotlib.pyplot as plt
import io
import os
from datetime import datetime


# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранение данных пользователей (в реальном проекте лучше использовать базу данных)
users = {}

# Константы для расчетов
WATER_BASE_MULTIPLIER = 30  # мл на кг веса
ACTIVITY_WATER_BONUS = 500  # мл за каждые 30 минут активности
HOT_WEATHER_WATER_BONUS = 500  # мл при температуре > 25°C
CALORIE_ACTIVITY_BONUS = 200  # ккал за каждые 30 минут активности

WORKOUTS = {
    "бег": {
        "emoji": "🏃‍♂️",
        "cal_per_min": 10,
        "water_bonus_per_30min": 200
    },
    "ходьба": {
        "emoji": "🚶‍♂️",
        "cal_per_min": 4,
        "water_bonus_per_30min": 100
    },
    "велосипед": {
        "emoji": "🚴‍♂️",
        "cal_per_min": 8,
        "water_bonus_per_30min": 200
    },
    "плавание": {
        "emoji": "🏊‍♂️",
        "cal_per_min": 9,
        "water_bonus_per_30min": 200
    },
    "йога": {
        "emoji": "🧘‍♂️",
        "cal_per_min": 3,
        "water_bonus_per_30min": 100
    },
}

# Функция для расчета нормы воды
def calculate_water_goal(weight, activity_minutes, temperature):
    water_goal = weight * WATER_BASE_MULTIPLIER
    water_goal += (activity_minutes // 30) * ACTIVITY_WATER_BONUS
    if temperature > 25:
        water_goal += HOT_WEATHER_WATER_BONUS
    return water_goal

# Функция для расчета нормы калорий
def calculate_calorie_goal(weight, height, age, activity_minutes):
    calorie_goal = 10 * weight + 6.25 * height - 5 * age
    calorie_goal += (activity_minutes // 30) * CALORIE_ACTIVITY_BONUS
    return calorie_goal

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я помогу вам отслеживать потребление воды и калорий. "
                                    "Используйте /set_profile для настройки профиля.")

# Команда /set_profile
async def set_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    users[user_id] = {"step": "weight"}
    await update.message.reply_text("Введите ваш вес (в кг):")

# Обработка текстовых сообщений для настройки профиля
async def handle_profile_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id not in users:
        await update.message.reply_text("Сначала используйте /set_profile для настройки профиля.")
        return

    step = users[user_id].get("step")
    if step == "weight":
        try:
            weight = float(text)
            users[user_id]["weight"] = weight
            users[user_id]["step"] = "height"
            await update.message.reply_text("Введите ваш рост (в см):")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число для веса.")
    elif step == "height":
        try:
            height = float(text)
            users[user_id]["height"] = height
            users[user_id]["step"] = "age"
            await update.message.reply_text("Введите ваш возраст:")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число для роста.")
    elif step == "age":
        try:
            age = int(text)
            users[user_id]["age"] = age
            users[user_id]["step"] = "activity"
            await update.message.reply_text("Сколько минут активности у вас в день?")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число для возраста.")
    elif step == "activity":
        try:
            activity = int(text)
            users[user_id]["activity"] = activity
            users[user_id]["step"] = "city"
            await update.message.reply_text("В каком городе вы находитесь? (en)")
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число для активности.")
    elif step == "city":
        city = text
        users[user_id]["city"] = city
        users[user_id]["step"] = None

        # Получаем температуру для города
        temperature = get_weather(city)
        if temperature is None:
            await update.message.reply_text("Не удалось получить данные о погоде. Попробуйте позже.")
            return

        # Рассчитываем нормы
        weight = users[user_id]["weight"]
        height = users[user_id]["height"]
        age = users[user_id]["age"]
        activity = users[user_id]["activity"]

        water_goal = calculate_water_goal(weight, activity, temperature)
        calorie_goal = calculate_calorie_goal(weight, height, age, activity)

        users[user_id]["water_goal"] = water_goal
        users[user_id]["calorie_goal"] = calorie_goal
        users[user_id]["logged_water"] = 0
        users[user_id]["logged_calories"] = 0
        users[user_id]["burned_calories"] = 0
        users[user_id]["water_logs"] = []
        users[user_id]["food_logs"] = []

        await update.message.reply_text(f"Настройка завершена!\n"
                                        f"Ваша норма воды: {water_goal} мл\n"
                                        f"Ваша норма калорий: {calorie_goal} ккал")

# Получение погоды через OpenWeatherMap API
def get_weather(city):
    API_KEY = "openweathermap_key"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data["main"]["temp"]
    return None

def log_water_entry(user_id, amount):
    """Логируем воду (с точным временем)."""
    # Обновляем суммарное значение
    users[user_id]["logged_water"] += amount
    
    # Пишем в историю
    users[user_id]["water_logs"].append({
        "datetime": datetime.now(),
        "amount": amount
    })

def log_food_entry(user_id, calories):
    """Логируем еду (с точным временем)."""
    users[user_id]["logged_calories"] += calories
    users[user_id]["food_logs"].append({
        "datetime": datetime.now(),
        "calories": calories
    })

# Команда /log_water
async def log_water(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in users or "water_goal" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return

    try:
        amount = int(context.args[0])
        log_water_entry(user_id, amount)
        remaining = users[user_id]["water_goal"] - users[user_id]["logged_water"]
        await update.message.reply_text(f"Добавлено {amount} мл воды.\n"
                                        f"Осталось выпить: {remaining} мл.")
    except (IndexError, ValueError):
        await update.message.reply_text("Используйте формат: /log_water <количество>")

# Команда /check_progress
async def check_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in users or "water_goal" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return

    water_goal = users[user_id]["water_goal"]
    logged_water = users[user_id]["logged_water"]
    calorie_goal = users[user_id]["calorie_goal"]
    logged_calories = users[user_id]["logged_calories"]
    burned_calories = users[user_id]["burned_calories"]

    remaining_water = water_goal - logged_water
    remaining_calories = logged_calories - burned_calories

    await update.message.reply_text(f"📊 Прогресс:\n"
                                    f"Вода:\n"
                                    f"- Выпито: {logged_water} мл из {water_goal} мл.\n"
                                    f"- Осталось: {remaining_water} мл.\n"
                                    f"Калории:\n"
                                    f"- Потреблено: {logged_calories} ккал из {calorie_goal} ккал.\n"
                                    f"- Сожжено: {burned_calories} ккал.\n"
                                    f"- Баланс: {remaining_calories} ккал.")
    
# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Список доступных команд:\n\n"
        "/start - Начать работу с ботом.\n"
        "/set_profile - Настроить профиль (вес, рост, возраст, активность, город).\n"
        "/log_water <количество> - Записать количество выпитой воды (в мл).\n"
        "/log_food <название продукта> - Записать потребление пищи.\n"
        "/log_workout <тип тренировки> <время (мин)> - Записать тренировку.\n"
        "/check_progress - Проверить текущий прогресс по воде и калориям.\n"
        "/show_graph - Вывести графики с потреблением воды и калорий.\n"
        "/recommend - Рекомендации по поведению относительно текущих показателей.\n"
        "/help - Показать это сообщение с описанием команд."
    )
    await update.message.reply_text(help_text)

# Команда /log_food
async def log_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in users or "calorie_goal" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return

    try:
        product_name = " ".join(context.args)
        if not product_name:
            await update.message.reply_text("Используйте формат: /log_food <название продукта>")
            return

        # Ищем продукт через OpenFoodFacts API
        product_data = search_product(product_name)
        if not product_data:
            await update.message.reply_text(f"Продукт '{product_name}' не найден. Попробуйте другой запрос.")
            return

        # Получаем калорийность продукта
        calories_per_100g = product_data.get("calories", None)
        if calories_per_100g is None:
            await update.message.reply_text(f"Не удалось получить информацию о калориях для '{product_name}'.")
            return

        # Запрашиваем у пользователя количество съеденного
        await update.message.reply_text(
            f"{product_data['emoji']} {product_data['name']} — {calories_per_100g} ккал на 100 г. "
            "Сколько грамм вы съели?"
        )
        users[user_id]["pending_food"] = {
            "calories_per_100g": calories_per_100g,
            "name": product_data["name"],
        }
    except Exception as e:
        logger.error(f"Ошибка при выполнении /log_food: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

# Поиск продукта через OpenFoodFacts API
def search_product(query):
    url = f"https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "search_terms": query,
        "search_simple": 1,
        "action": "process",
        "json": 1,
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        products = data.get("products", [])
        if products:
            product = products[0]
            name = product.get("product_name", "Неизвестный продукт")
            emoji = "🍴" 
            calories = None
            nutriments = product.get("nutriments", {})
            if "energy-kcal_100g" in nutriments:
                calories = float(nutriments["energy-kcal_100g"])
            return {"name": name, "calories": calories, "emoji": emoji}
    return None

# Обработка текстовых сообщений для завершения логирования еды
async def handle_food_logging(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    if user_id not in users or "pending_food" not in users[user_id]:
        return

    try:
        grams = float(text)
        pending_food = users[user_id]["pending_food"]
        calories_per_100g = pending_food["calories_per_100g"]
        name = pending_food["name"]

        # Рассчитываем потребленные калории
        consumed_calories = (calories_per_100g / 100) * grams
        log_food_entry(user_id, consumed_calories)

        del users[user_id]["pending_food"]

        await update.message.reply_text(f"Записано: {consumed_calories:.1f} ккал ({grams} г {name}).")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число для количества грамм.")

async def log_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # Проверяем, есть ли у пользователя профиль
    if user_id not in users or "calorie_goal" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return

    # Если пользователь не указал параметры (или указал недостаточно)
    if len(context.args) < 2:
        available_workouts = "\n".join([f"- {w}" for w in WORKOUTS.keys()])
        await update.message.reply_text(
            "Используйте формат: /log_workout <тип тренировки> <время (мин)>.\n\n"
            "Доступные виды тренировок:\n"
            f"{available_workouts}"
        )
        return

    workout_type = context.args[0].lower()
    try:
        duration = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "Пожалуйста, введите корректное число для времени в минутах.\n"
            "Пример: /log_workout бег 30"
        )
        return

    # Проверяем, существует ли такой тип тренировки в словаре
    if workout_type not in WORKOUTS:
        available_workouts = "\n".join([f"- {w}" for w in WORKOUTS.keys()])
        await update.message.reply_text(
            f"Неизвестный тип тренировки '{workout_type}'.\n\n"
            "Доступные виды тренировок:\n"
            f"{available_workouts}"
        )
        return

    # Считаем, сколько калорий сожжено
    cal_per_min = WORKOUTS[workout_type]["cal_per_min"]
    total_burned = cal_per_min * duration
    users[user_id]["burned_calories"] += total_burned

    # Дополнительная вода
    water_bonus_per_30 = WORKOUTS[workout_type]["water_bonus_per_30min"]
    extra_water = (duration // 30) * water_bonus_per_30

    emoji = WORKOUTS[workout_type]["emoji"]
    reply_text = (
        f"{emoji} {workout_type.capitalize()} {duration} мин — {total_burned} ккал.\n"
    )
    if extra_water > 0:
        reply_text += f"Дополнительно: выпейте {extra_water} мл воды."
        users[user_id]["water_goal"] += extra_water
    else:
        reply_text += "Хорошая работа!"

    await update.message.reply_text(reply_text)

def generate_time_based_plots(user_id, target_date=None):
    """
    Строит график динамики (в течение дня или нескольких дней).
    
    Параметр target_date (формат 'YYYY-MM-DD') - если задан, фильтруем логи только за эту дату.
    Если не задан, можно вывести за все время или тоже за сегодня (на ваш выбор).
    """
    water_logs = users[user_id].get("water_logs", [])
    food_logs = users[user_id].get("food_logs", [])

    # Если нужно показывать только за конкретную дату, отфильтруем записи
    # Если target_date не задан, можно выводить все.
    if target_date:
        year, month, day = map(int, target_date.split('-'))
        filter_date = datetime(year, month, day).date()

        water_logs = [w for w in water_logs if w["datetime"].date() == filter_date]
        food_logs = [f for f in food_logs if f["datetime"].date() == filter_date]

    # Сортируем по времени (на всякий случай)
    water_logs.sort(key=lambda x: x["datetime"])
    food_logs.sort(key=lambda x: x["datetime"])

    if not water_logs and not food_logs:
        return None  # Нет данных для графика

    # Считаем накопительные суммы
    # Для воды
    water_times = []
    water_cumulative = 0
    water_values = []
    
    for entry in water_logs:
        water_cumulative += entry["amount"]
        water_times.append(entry["datetime"])
        water_values.append(water_cumulative)

    # Для еды (калории)
    food_times = []
    food_cumulative = 0
    food_values = []
    
    for entry in food_logs:
        food_cumulative += entry["calories"]
        food_times.append(entry["datetime"])
        food_values.append(food_cumulative)

    # Рисуем
    fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(8, 6))
    if target_date:
        fig.suptitle(f"Прогресс за {target_date}")
    else:
        fig.suptitle("Прогресс (за всё время)")

    # --- Верхний график: Вода
    if water_times:
        axes[0].plot(water_times, water_values, marker='o', color='blue', label='Вода (мл)')
    axes[0].set_title("Вода (накопительно)")
    axes[0].set_xlabel("Время")
    axes[0].set_ylabel("мл")
    axes[0].grid(True)
    axes[0].legend()

    # --- Нижний график: Калории
    if food_times:
        axes[1].plot(food_times, food_values, marker='o', color='red', label='Калории (накопительно)')
    axes[1].set_title("Калории (накопительно)")
    axes[1].set_xlabel("Время")
    axes[1].set_ylabel("ккал")
    axes[1].grid(True)
    axes[1].legend()

    # Немного подправим расположение, поворот меток по X (чтобы не налезали)
    plt.tight_layout()
    for ax in axes:
        for label in ax.get_xticklabels():
            label.set_rotation(45)
            label.set_ha('right')

    # Сохраняем рисунок
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)

    return buf

async def show_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in users or "water_logs" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return
    
    # Проверим аргументы
    if len(context.args) > 0:
        target_date = context.args[0]  # ожидаем формат 'YYYY-MM-DD'
    else:
        # По умолчанию - сегодня
        target_date = datetime.now().strftime("%Y-%m-%d")

    buf = generate_time_based_plots(user_id, target_date)
    if buf is None:
        await update.message.reply_text(f"Данных для даты {target_date} нет.")
        return

    # Отправляем картинку
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=buf,
        caption=f"Прогресс за {target_date}"
    )


def get_recommendations(user_id):
    """
    Анализирует показатели пользователя и возвращает строку с рекомендациями.
    Рекомендации основаны на:
      - Недостатке выпитой воды (если выпито меньше 80% от дневной нормы).
      - Перебое или недостатке калорий в рационе.
      - Балансе между потреблёнными и сожженными калориями.
    """
    user_data = users[user_id]
    water_goal = user_data.get("water_goal", 0)
    logged_water = user_data.get("logged_water", 0)
    calorie_goal = user_data.get("calorie_goal", 0)
    logged_calories = user_data.get("logged_calories", 0)
    burned_calories = user_data.get("burned_calories", 0)

    recommendations = []

    # Рекомендация по воде:
    water_deficit = water_goal - logged_water
    if water_deficit > water_goal * 0.2:
        recommendations.append("Вы выпили недостаточно воды. Рекомендуем выпить еще стакан чистой воды.")

    # Рекомендация по рациону:
    if logged_calories > calorie_goal:
        recommendations.append("Ваш рацион превышает дневную норму калорий. Попробуйте выбрать легкие блюда (например, овощной салат или суп), чтобы немного снизить потребление калорий.")
    elif logged_calories < calorie_goal * 0.7:
        recommendations.append("Вы потребляете меньше калорий, чем требуется. Убедитесь, что получаете достаточное количество питательных веществ.")

    # Рекомендация по физической активности:
    net_calories = logged_calories - burned_calories  # "чистые" калории, остающиеся после активности
    if net_calories > calorie_goal:
        recommendations.append("Ваш калорийный баланс довольно высок. Рекомендуем выполнить 30 минут кардио (например, бег или быструю ходьбу) для повышения расхода калорий.")
    elif burned_calories < calorie_goal * 0.2:
        recommendations.append("Добавьте физической активности в свой день. Например, попробуйте 20–30 минут йоги или легкой зарядки.")

    if not recommendations:
        recommendations.append("Отлично! Вы хорошо соблюдаете свои нормы.")

    return "\n".join(recommendations)

async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in users or "water_goal" not in users[user_id]:
        await update.message.reply_text("Сначала настройте профиль с помощью /set_profile.")
        return

    recs = get_recommendations(user_id)
    await update.message.reply_text(recs)


# Основная функция
def main():
    TOKEN = "telegram_key"
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set_profile", set_profile))
    application.add_handler(CommandHandler("log_water", log_water))
    application.add_handler(CommandHandler("log_food", log_food))
    application.add_handler(CommandHandler("log_workout", log_workout))
    application.add_handler(CommandHandler("show_graph", show_graph))
    application.add_handler(CommandHandler("check_progress", check_progress))
    application.add_handler(CommandHandler("recommend", recommend_command))
    application.add_handler(CommandHandler("help", help_command))


    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_food_logging),
        group=0  # приоритетная группа
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_setup),
        group=1  # следующая группа
    )

    application.run_polling()

if __name__ == "__main__":
    main()