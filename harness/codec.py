"""Independent IMA ADPCM blocks; deliberately not a WAV IMA container."""
import struct
from .protocol import ProtocolError, Detail

STEPS = (7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,
         88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,
         598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,
         2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,
         11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767)
INDEX = (-1,-1,-1,-1,2,4,6,8)


def nibble_decode(code, predictor, index):
    step = STEPS[index]
    diff = (step >> 3) + ((step >> 2) if code & 1 else 0) + ((step >> 1) if code & 2 else 0) + (step if code & 4 else 0)
    predictor = max(-32768, min(32767, predictor + (-diff if code & 8 else diff)))
    return predictor, max(0, min(88, index + INDEX[code & 7]))


def encode(samples, index=0):
    if not samples or not 0 <= index <= 88 or any(not -32768 <= x <= 32767 for x in samples):
        raise ProtocolError(Detail.BAD_VALUE)
    predictor = samples[0]
    output = bytearray(struct.pack("<hBB", predictor, index, 0))
    codes = []
    for sample in samples[1:]:
        step = STEPS[index]
        delta = sample - predictor
        code = 8 if delta < 0 else 0
        delta = abs(delta)
        for bit, amount in ((4, step), (2, step >> 1), (1, step >> 2)):
            if delta >= amount:
                code |= bit
                delta -= amount
        predictor, index = nibble_decode(code, predictor, index)
        codes.append(code)
    for i in range(0, len(codes), 2):
        output.append(codes[i] | (codes[i+1] << 4 if i+1 < len(codes) else 0))
    return bytes(output)


def decode(block, sample_count):
    if sample_count < 1 or len(block) != 4 + sample_count // 2:
        raise ProtocolError(Detail.BAD_LENGTH)
    predictor, index, reserved = struct.unpack_from("<hBB", block)
    if index > 88 or reserved or (sample_count % 2 == 0 and block[-1] & 0xf0):
        raise ProtocolError(Detail.BAD_VALUE)
    samples = [predictor]
    for i in range(sample_count - 1):
        code = (block[4 + i // 2] >> (4 * (i % 2))) & 15
        predictor, index = nibble_decode(code, predictor, index)
        samples.append(predictor)
    return samples


def pcm(frame):
    from .protocol import PROFILES
    count = PROFILES[frame.profile][1]
    return list(struct.unpack(f"<{count}h", frame.body)) if frame.profile == 3 else decode(frame.body, count)
