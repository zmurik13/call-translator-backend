import asyncio
import uuid


async def handle_audio_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
	print("\n📞 [AudioSocket] ВХОДЯЩИЙ ЗВОНОК ОТ ASTERISK!")

	try:
		# Протокол AudioSocket начинается с 16-байтного UUID звонка
		uuid_bytes = await reader.readexactly(16)
		call_id = uuid.UUID(bytes=uuid_bytes)
		print(f"🔗 [AudioSocket] Call ID установлен: {call_id}")

		bytes_received = 0

		# Запускаем бесконечный цикл чтения аудио-потока
		while True:
			# Читаем чанками по 320 байт (это ровно 20 миллисекунд аудио 8kHz)
			chunk = await reader.read(320)
			if not chunk:
				print("📴 [AudioSocket] Asterisk положил трубку.")
				break

			bytes_received += len(chunk)

			# Для отладки выводим инфу каждую секунду (1 сек = ~16000 байт)
			if bytes_received % 16000 == 0:
				print(f"🌊 [AudioSocket] Поток идет... Получено {bytes_received} байт")

		# В БУДУЩЕМ: здесь мы будем кидать chunk в WebSocket Deepgram

	except asyncio.IncompleteReadError:
		print("⚠️ [AudioSocket] Астериск разорвал соединение (IncompleteRead).")
	except Exception as e:
		print(f"❌ [AudioSocket] Ошибка: {e}")
	finally:
		print(f"🛑 [AudioSocket] Закрываем соединение для {call_id}\n")
		writer.close()
		await writer.wait_closed()


async def start_audiosocket_server(host="127.0.0.1", port=9090):
	server = await asyncio.start_server(handle_audio_stream, host, port)
	addr = server.sockets[0].getsockname()
	print(f"🚀 [AudioSocket] TCP Сервер запущен на {addr}")
	async with server:
		await server.serve_forever()