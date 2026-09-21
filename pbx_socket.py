import asyncio
import uuid


async def read_audiosocket_message(reader: asyncio.StreamReader):
	"""
	Reads exactly one Asterisk AudioSocket packet (Header + Payload).
	"""
	try:
		# Header: 1 byte (Type) + 2 bytes (Length, Big-Endian)
		header = await reader.readexactly(3)
		msg_type = header[0]
		payload_length = int.from_bytes(header[1:3], byteorder='big')

		# Read the exact payload based on the length from header
		payload = await reader.readexactly(payload_length) if payload_length > 0 else b""
		return msg_type, payload
	except asyncio.IncompleteReadError:
		return None, None


async def handle_audio_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
	print("\n[AudioSocket] INCOMING CONNECTION FROM ASTERISK")
	call_id = None
	bytes_received = 0

	try:
		while True:
			msg_type, payload = await read_audiosocket_message(reader)

			# Type 0x00: Hangup or Disconnect
			if msg_type is None or msg_type == 0x00:
				print("[AudioSocket] Asterisk hung up.")
				break

			# Type 0x01: Stream UUID
			elif msg_type == 0x01:
				call_id = uuid.UUID(bytes=payload)
				print(f"[AudioSocket] Call ID established: {call_id}")

			# Type 0x10: 8kHz Audio Payload
			elif msg_type == 0x10:
				bytes_received += len(payload)

				# Debug output every ~1 second of 8kHz audio (16000 bytes)
				if bytes_received > 0 and bytes_received % 16000 == 0:
					print(f"[AudioSocket] Streaming... Bytes received: {bytes_received}")

			# TODO: Send `payload` to Deepgram Live WebSocket here

			# Type 0x03: DTMF Digit
			elif msg_type == 0x03:
				print(f"[AudioSocket] DTMF detected: {payload.decode('ascii')}")

			# Type 0xff: Asterisk Error
			elif msg_type == 0xff:
				print(f"[AudioSocket] Asterisk error code: {payload}")
				break

	except Exception as e:
		print(f"[AudioSocket] ERROR: {e}")
	finally:
		print(f"[AudioSocket] Closing connection for {call_id}\n")
		writer.close()
		await writer.wait_closed()


async def start_audiosocket_server(host="127.0.0.1", port=9090):
	server = await asyncio.start_server(handle_audio_stream, host, port)
	addr = server.sockets[0].getsockname()
	print(f"[AudioSocket] TCP Server listening on {addr}")
	async with server:
		await server.serve_forever()