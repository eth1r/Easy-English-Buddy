"""
Конфигурация для бота Easy English Buddy
Загружает переменные окружения из .env файла
"""
import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Получаем токены из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
GIGACHAT_AUTH = os.getenv('GIGACHAT_AUTH')  # Authorization key для Basic auth
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Проверка наличия всех необходимых ключей
def check_config():
    """Проверяет наличие всех необходимых переменных окружения"""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN")
    
    if not GIGACHAT_AUTH:
        errors.append("GIGACHAT_AUTH")
    
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY")
    
    if errors:
        print("=" * 60)
        print("ОШИБКА: Отсутствуют необходимые переменные окружения!")
        print("=" * 60)
        print(f"\nНе найдены: {', '.join(errors)}")
        print("\nРешение:")
        print("1. Создайте файл .env в корне проекта")
        print("2. Добавьте следующие строки:")
        print("   BOT_TOKEN=ваш_токен_telegram")
        print("   GIGACHAT_AUTH=ваш_gigachat_auth_key")
        print("   OPENAI_API_KEY=ваш_openai_api_key")
        print("\n3. Получите токены:")
        print("   - BOT_TOKEN: у @BotFather в Telegram")
        print("   - GIGACHAT_AUTH: в личном кабинете GigaChat")
        print("   - OPENAI_API_KEY: на https://platform.openai.com/api-keys")
        print("=" * 60)
        sys.exit(1)

# Проверяем конфигурацию при импорте модуля
if __name__ != "__main__":
    check_config()
