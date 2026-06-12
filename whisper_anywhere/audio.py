import struct

AUDIO = "/tmp/whisper-anywhere.wav"
SAMPLE_RATE = 16000


def write_wav(path, data, sample_rate=SAMPLE_RATE, sample_width=2, channels=1):
    data_size = len(data)
    if data_size % sample_width != 0:
        data_size -= data_size % sample_width
        data = data[:data_size]
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * channels * sample_width))
        f.write(struct.pack("<H", channels * sample_width))
        f.write(struct.pack("<H", sample_width * 8))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(bytes(data))


async def read_audio(proc, buffer):
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buffer.extend(chunk)
