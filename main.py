"""
Easy English Buddy - Telegram бот для изучения английского языка
Использует GigaChat для обработки текста и OpenAI для озвучки
"""
import asyncio
import logging
import sys
import uuid
import time
from typing import Optional

import requests
import urllib3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from openai import OpenAI

from config import BOT_TOKEN, GIGACHAT_AUTH, OPENAI_API_KEY, check_config

# Отключаем предупреждения SSL для работы с GigaChat API
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# URL для GigaChat API
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1"
CHAT_COMPLETIONS_URL = f"{GIGACHAT_API_URL}/chat/completions"

# Системный промпт для GigaChat
SYSTEM_PROMPT = """Ты — дружелюбный репетитор английского для уровня A0.

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:

1. Если пишут на русском — ОБЯЗАТЕЛЬНО переведи ВСЕ слова на английский:
   - Переведи КАЖДОЕ слово: существительные, прилагательные, глаголы, предлоги
   - Не пропускай никаких слов, даже если это конкретные предметы (еда, вещи и т.д.)
   - Для еды, предметов используй точные английские названия:
     * "гречка" → "buckwheat" или "buckwheat porridge"
     * "рис" → "rice"
     * "молоко" → "milk"
   - Если в предложении есть слово, которое ты не знаешь — найди английский эквивалент или объясни, что это

2. Если пишут на английском — исправь ошибки и улучши формулировку.

3. Объясняй грамматику кратко на русском языке.

4. НЕ ОСТАВЛЯЙ непереведенных русских слов в английской части ответа.

ФОРМАТ ОТВЕТА СТРОГИЙ (ОБЯЗАТЕЛЬНО СЛЕДУЙ ЭТОМУ ФОРМАТУ):

[Только английская фраза для озвучки - полный перевод ВСЕХ слов предложения]

---

[Твое объяснение на русском языке - краткое пояснение грамматики или особенностей перевода]"""


class GigaChatClient:
    """Клиент для работы с GigaChat API"""
    
    def __init__(self, auth_key: str):
        self.auth_key = auth_key
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0
    
    def get_access_token(self) -> str:
        """Получает access token через OAuth"""
        # Если токен еще действителен, возвращаем его
        if self.access_token and time.time() < self.token_expires_at:
            return self.access_token
        
        # Генерируем уникальный RqUID
        rquid = str(uuid.uuid4())
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': rquid,
            'Authorization': f'Basic {self.auth_key}'
        }
        
        data = {
            'scope': 'GIGACHAT_API_PERS'
        }
        
        try:
            response = requests.post(OAUTH_URL, headers=headers, data=data, verify=False)
            response.raise_for_status()
            
            result = response.json()
            self.access_token = result.get('access_token')
            
            if not self.access_token:
                raise ValueError("Access token не получен в ответе")
            
            # Токен обычно действителен 30 минут
            expires_in = result.get('expires_in', 1800)
            self.token_expires_at = time.time() + expires_in - 60  # минус 1 минута для запаса
            
            logger.info(f"Access token получен, действителен {expires_in} секунд")
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при получении access token: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Ответ сервера: {e.response.text}")
            raise
    
    async def send_message(self, message: str) -> str:
        """Отправляет сообщение в GigaChat и получает ответ
        
        Args:
            message: Текущее сообщение пользователя
            
        Returns:
            Ответ от GigaChat
        """
        access_token = self.get_access_token()
        
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Формируем список сообщений (каждый запрос как новый, но с системной ролью)
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": message
            }
        ]
        
        # Формируем запрос для chat completions
        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 512
        }
        
        try:
            # Выполняем запрос в отдельном потоке, чтобы не блокировать event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    CHAT_COMPLETIONS_URL,
                    headers=headers,
                    json=payload,
                    verify=False
                )
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Извлекаем ответ из структуры ответа GigaChat
            if 'choices' in result and len(result['choices']) > 0:
                choice = result['choices'][0]
                if 'message' in choice:
                    return choice['message'].get('content', 'Пустой ответ от GigaChat')
                elif 'text' in choice:
                    return choice['text']
            
            logger.warning(f"Неожиданная структура ответа: {result}")
            return "Извините, не удалось получить ответ от GigaChat."
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при отправке сообщения в GigaChat: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Ответ сервера: {e.response.text}")
            raise


class OpenAITTSClient:
    """Клиент для работы с OpenAI Text-to-Speech API"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    async def generate_speech(self, text: str) -> bytes:
        """Генерирует аудио из текста
        
        Args:
            text: Текст для озвучки
            
        Returns:
            Байты аудио файла в формате opus
        """
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.audio.speech.create(
                    model="tts-1",
                    voice="alloy",
                    input=text,
                    response_format="opus",
                    speed=0.8  # Скорость речи: 0.8 = на 20% медленнее нормальной
                )
            )
            
            # Читаем содержимое ответа
            audio_data = response.content
            
            return audio_data
            
        except Exception as e:
            logger.error(f"Ошибка при генерации речи: {e}")
            raise


# Инициализация клиентов
gigachat_client: Optional[GigaChatClient] = None
tts_client: Optional[OpenAITTSClient] = None

# Инициализация бота и диспетчера
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def parse_gigachat_response(response: str) -> tuple[str, str]:
    """Разделяет ответ GigaChat на английский текст и объяснение
    
    Args:
        response: Полный ответ от GigaChat
        
    Returns:
        Кортеж (english_text, explanation)
    """
    response = response.strip()
    
    # Ищем разделитель --- (может быть с пробелами или без)
    if '---' in response:
        parts = response.split('---', 1)
        if len(parts) == 2:
            english_text = parts[0].strip()
            explanation = parts[1].strip()
        else:
            english_text = response
            explanation = ""
    else:
        # Если разделителя нет, ищем по другим признакам
        lines = [line.strip() for line in response.split('\n') if line.strip()]
        english_text = ""
        explanation = ""
        
        # Пытаемся найти первую строку с английским текстом (без кириллицы)
        for i, line in enumerate(lines):
            # Проверяем, нет ли в строке кириллицы
            has_cyrillic = any('\u0400' <= char <= '\u04FF' for char in line)
            # Проверяем, есть ли латинские буквы
            has_latin = any(c.isalpha() and ord(c) < 128 for c in line)
            
            if has_latin and not has_cyrillic and not line.startswith('['):
                # Нашли строку с латиницей без кириллицы - это английский текст
                english_text = line
                if i + 1 < len(lines):
                    explanation = '\n'.join(lines[i+1:]).strip()
                break
        
        if not english_text:
            # Если ничего не нашли, берем первую строку
            english_text = lines[0] if lines else response
            explanation = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
    
    # Очищаем английский текст от квадратных скобок и лишних символов
    english_text = english_text.strip('[]').strip()
    
    # Убираем лишние пробелы из английского текста, но сохраняем структуру
    english_text = ' '.join(english_text.split())
    
    # Сохраняем структуру объяснения (может быть многострочным)
    explanation = explanation.strip()
    
    logger.debug(f"Извлечено: english_text='{english_text}', explanation='{explanation[:50] if explanation else 'нет'}...'")
    
    return english_text, explanation


async def process_message(message: Message):
    """Обрабатывает текстовое сообщение от пользователя"""
    user_text = message.text
    
    if not user_text or not user_text.strip():
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return
    
    try:
        # Показываем, что бот печатает
        await message.bot.send_chat_action(message.chat.id, "typing")
        
        # Получаем ответ от GigaChat
        logger.info(f"Получен запрос от пользователя {message.from_user.id}: {user_text}")
        gigachat_response = await gigachat_client.send_message(user_text)
        logger.debug(f"Ответ от GigaChat: {gigachat_response[:200]}...")
        
        # Разделяем ответ на английский текст и объяснение
        english_text, explanation = parse_gigachat_response(gigachat_response)
        logger.info(f"Извлечено - английский текст: '{english_text}', объяснение: '{explanation[:50] if explanation else 'нет'}...'")
        
        # Проверяем, что английский текст не пустой
        if not english_text or not english_text.strip():
            logger.warning(f"Внимание: английский текст пуст! Полный ответ GigaChat: {gigachat_response}")
            # Если английский текст пуст, используем весь ответ как английский текст
            english_text = gigachat_response.split('---')[0].strip() if '---' in gigachat_response else gigachat_response.strip()
            if not english_text:
                english_text = "Translation not available"
        
        # Проверяем на наличие кириллицы в английском тексте (это ошибка)
        has_cyrillic = any('\u0400' <= char <= '\u04FF' for char in english_text)
        if has_cyrillic:
            logger.warning(f"Обнаружен русский текст в английской части! Текст: {english_text}")
            # Попробуем извлечь английский текст заново
            lines = gigachat_response.split('\n')
            for line in lines:
                line = line.strip()
                # Ищем первую строку с латиницей и без кириллицы
                if line and not any('\u0400' <= char <= '\u04FF' for char in line) and any(c.isalpha() for c in line):
                    if '---' not in line and not line.startswith('['):
                        english_text = line
                        break
        
        # Формируем полный текстовый ответ
        if explanation:
            full_response = f"{english_text}\n\n---\n\n{explanation}"
        else:
            full_response = english_text
        
        # Отправляем текстовый ответ
        await message.answer(full_response)
        
        # Генерируем и отправляем озвучку английского текста
        if english_text and english_text.strip():
            audio_sent = False
            max_retries = 2
            
            for attempt in range(max_retries):
                try:
                    await message.bot.send_chat_action(message.chat.id, "record_voice")
                    
                    logger.info(f"Генерирую озвучку для: {english_text} (попытка {attempt + 1}/{max_retries})")
                    audio_data = await tts_client.generate_speech(english_text.strip())
                    
                    if not audio_data or len(audio_data) == 0:
                        raise ValueError("Получены пустые данные аудио")
                    
                    # Отправляем голосовое сообщение из байтов в памяти
                    voice_file = BufferedInputFile(audio_data, filename="voice.opus")
                    await message.answer_voice(voice_file)
                    
                    logger.info("✓ Озвучка успешно отправлена")
                    audio_sent = True
                    break
                    
                except Exception as tts_error:
                    logger.error(f"Ошибка при генерации озвучки (попытка {attempt + 1}/{max_retries}): {tts_error}")
                    if attempt < max_retries - 1:
                        # Небольшая задержка перед повторной попыткой
                        await asyncio.sleep(1)
                    else:
                        # После всех попыток уведомляем пользователя
                        logger.error(f"Не удалось сгенерировать озвучку после {max_retries} попыток")
                        error_note = (
                            f"\n\n⚠️ _Не удалось сгенерировать озвучку для фразы._"
                        )
                        try:
                            await message.answer(error_note, parse_mode="Markdown")
                        except:
                            pass  # Если не удалось отправить уведомление, продолжаем
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        error_message = (
            "Произошла ошибка при обработке вашего запроса. "
            "Пожалуйста, попробуйте еще раз позже."
        )
        await message.answer(error_message)


async def cmd_start(message: Message):
    """Обработчик команды /start"""
    welcome_text = (
        "👋 Привет! Я Easy English Buddy — твой репетитор по английскому языку!\n\n"
        "Я могу:\n"
        "• Переводить с русского на английский\n"
        "• Исправлять ошибки в английском тексте\n"
        "• Объяснять грамматику кратко на русском\n"
        "• Озвучивать английские фразы\n\n"
        "Просто напиши мне на русском или английском, и я помогу тебе! 🎯"
    )
    await message.answer(welcome_text)


async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = (
        "📚 Справка по использованию бота:\n\n"
        "Отправь мне:\n"
        "• Текст на русском — я переведу его на английский\n"
        "• Текст на английском — я исправлю ошибки\n\n"
        "Я также:\n"
        "• Объясню грамматику кратко на русском\n"
        "• Озвучу правильную английскую фразу\n\n"
        "Команды:\n"
        "/start — приветствие\n"
        "/help — эта справка"
    )
    await message.answer(help_text)


async def handle_text(message: Message):
    """Обработчик всех текстовых сообщений"""
    await process_message(message)


async def main():
    """Основная функция для запуска бота"""
    global bot, dp, gigachat_client, tts_client
    
    # Проверяем конфигурацию
    check_config()
    
    try:
        # Инициализация клиента GigaChat
        logger.info("Инициализация GigaChat клиента...")
        gigachat_client = GigaChatClient(GIGACHAT_AUTH)
        
        # Тестовая проверка токена
        logger.info("Проверка подключения к GigaChat...")
        test_token = gigachat_client.get_access_token()
        if test_token:
            logger.info("✓ Подключение к GigaChat успешно!")
        else:
            logger.error("✗ Не удалось получить токен GigaChat")
            sys.exit(1)
        
        # Инициализация клиента OpenAI TTS
        logger.info("Инициализация OpenAI TTS клиента...")
        tts_client = OpenAITTSClient(OPENAI_API_KEY)
        logger.info("✓ Клиент OpenAI TTS готов!")
        
        # Инициализация бота и диспетчера
        logger.info("Инициализация Telegram бота...")
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()
        
        # Регистрируем обработчики
        dp.message.register(cmd_start, Command("start"))
        dp.message.register(cmd_help, Command("help"))
        dp.message.register(handle_text, F.text)
        
        # Запускаем бота
        logger.info("Бот запущен и готов к работе!")
        logger.info("Нажмите Ctrl+C для остановки")
        
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.info("\nБот остановлен пользователем")
    except Exception as e:
        logger.error(f"ОШИБКА при запуске бота: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if bot:
            await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
