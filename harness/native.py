"""Build/load the same portable C source used by the ESP-IDF firmware."""
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    out = ROOT / "build" / ("sh_core.dll" if os.name == "nt" else "libsh_core.so")
    out.parent.mkdir(exist_ok=True)
    source = ROOT / "firmware/components/sh_core/sh_core.c"
    include = source.parent / "include"
    cache = ROOT / ".tools/zig-cache"
    cache.mkdir(parents=True, exist_ok=True)
    (ROOT / ".tools/tmp").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache / "local"),
               TMP=str(ROOT / ".tools/tmp"), TEMP=str(ROOT / ".tools/tmp"))
    args = [sys.executable, "-m", "ziglang", "cc", "-shared", "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-O2", "-I", str(include), str(source), str(source.parent / "sh_device.c"),
            str(source.parent / "sh_button.c"), str(source.parent / "sh_link.c"), "-o", str(out)]
    if os.name != "nt":
        args += ["-fPIC", "-lm"]
    result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Native C build failed:\n{result.stdout}\n{result.stderr}")
    return out


class Native:
    def __init__(self, path=None):
        self.lib = C.CDLL(str(path or build()))
        self.lib.sh_parse.argtypes = [C.c_char_p, C.c_size_t, C.c_void_p]
        self.lib.sh_adpcm_encode.argtypes = [C.POINTER(C.c_int16), C.c_size_t, C.c_uint8, C.c_void_p, C.c_size_t]
        self.lib.sh_adpcm_decode.argtypes = [C.c_char_p, C.c_size_t, C.c_size_t, C.POINTER(C.c_int16)]
        self.lib.sh_pattern_duration.argtypes = [C.c_uint8, C.c_uint8]
        self.lib.sh_pattern_duration.restype = C.c_uint32
        self.lib.sh_pattern_level.argtypes = [C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint32]
        self.lib.sh_pattern_level.restype = C.c_uint8

    def parse_result(self, raw):
        output = C.create_string_buffer(64)
        return self.lib.sh_parse(raw, len(raw), output)

    def encode(self, samples, index=0):
        source = (C.c_int16 * len(samples))(*samples)
        out = C.create_string_buffer(4 + len(samples)//2)
        n = self.lib.sh_adpcm_encode(source, len(samples), index, out, len(out))
        if n < 0:
            raise ValueError("C encoder rejected input")
        return out.raw[:n]

    def decode(self, block, count):
        out = (C.c_int16 * count)()
        result = self.lib.sh_adpcm_decode(block, len(block), count, out)
        if result:
            raise ValueError(result)
        return list(out)
