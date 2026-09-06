import asyncio
import edge_tts
import subprocess
import os

# Папка, где Asterisk хранит кастомные звуки (убедись, что она существует)
OUTPUT_DIR = "/var/lib/asterisk/sounds/custom"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Список наших фраз: (Текст, Голос, Имя файла)
PROMPTS = [
	(
		"Sveiki paskambinę į šimtas auto ratų. Kuo galime padėti?",
		"lt-LT-LeonasNeural",
		"greeting_lt"
	),
	(
		"Спасибо. Передаю ваш вопрос мастеру, пожалуйста, оставайтесь на линии.",
		"ru-RU-DmitryNeural",
		"bridge_ru"
	),
	(
		"Ačiū. Sujungiame su meistru. Kadangi meistras kalba rusiškai, jūsų pokalbį realiu laiku vers dirbtinis intelektas.",
		"lt-LT-LeonasNeural",
		"bridge_lt_ai"
	)
]


async def generate_all():
	print(f"🎙️ Начинаем генерацию аудио для Asterisk в {OUTPUT_DIR}...")

	for text, voice, filename in PROMPTS:
		mp3_path = f"/tmp/{filename}.mp3"
		wav_path = f"{OUTPUT_DIR}/{filename}.wav"

		print(f"⏳ Генерируем {filename} ({voice})...")

		# 1. Генерируем MP3
		communicate = edge_tts.Communicate(text, voice)
		await communicate.save(mp3_path)

		# 2. Конвертируем в идеальный формат для Asterisk (WAV, 8000Hz, 16-bit, mono)
		subprocess.run([
			"ffmpeg", "-y", "-i", mp3_path,
			"-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", wav_path
		], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		# 3. Убираем мусор
		os.remove(mp3_path)
		print(f"✅ Готово: {wav_path}")

	# Меняем права, чтобы Asterisk мог прочитать файлы
	subprocess.run(["chown", "-R", "asterisk:asterisk", OUTPUT_DIR])
	print("🎉 Все файлы успешно созданы!")


if __name__ == "__main__":
	asyncio.run(generate_all())