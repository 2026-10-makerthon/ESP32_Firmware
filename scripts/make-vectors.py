"""Maintainer-only: independent CPython audioop oracle. Never run during tests.

Requires Python 3.12 (audioop removed in 3.13). Audited output is committed.
audioop packs high nibble first; the project packs low nibble first.
"""
import audioop
import hashlib
import json
import math
from pathlib import Path
import random
import struct

root = Path(__file__).resolve().parents[1]
rng = random.Random(73412)
inputs = {"manual_small":[0,1,4,8,15], "silence":[0]*320,
          "extremes":[-32768,32767]*160, "step":[0]*160+[12000]*160,
          "sine":[int(12000*math.sin(2*math.pi*440*i/16000)) for i in range(320)],
          "random_seed_73412":[rng.randrange(-32768,32768) for _ in range(320)]}
vectors = []
for name, samples in inputs.items():
    rest = samples[1:]
    if len(rest)%2:
        rest = rest+[rest[-1]]
    raw = struct.pack(f"<{len(rest)}h",*rest)
    encoded, _ = audioop.lin2adpcm(raw,2,(samples[0],0))
    swapped = bytearray((b>>4)|((b&15)<<4) for b in encoded)
    if len(samples)%2==0:
        swapped[-1] &= 15
    body = struct.pack("<hBB",samples[0],0,0)+swapped
    high = bytes((b>>4)|((b&15)<<4) for b in body[4:])
    decoded, _ = audioop.adpcm2lin(high,2,(samples[0],0))
    decoded_pcm = [samples[0]]+list(struct.unpack(f"<{len(decoded)//2}h",decoded))[:len(samples)-1]
    vectors.append({"name":name,"input_pcm":samples,"block_hex":body.hex(),"decoded_pcm":decoded_pcm,
                    "decoded_sha256":hashlib.sha256(struct.pack(f"<{len(samples)}h",*decoded_pcm)).hexdigest()})
assert vectors[0]["block_hex"] == "000000002143"
assert vectors[0]["decoded_pcm"] == [0,1,4,8,15]
payload={"source":"CPython 3.12 audioop.lin2adpcm/adpcm2lin (independent C implementation), nibble order adapted",
         "manual_check":"predictor=0,index=0,step=7: codes 1,2,3,4 -> deltas 1,3,4,7 -> PCM 0,1,4,8,15; bytes 21 43",
         "reference":"https://github.com/python/cpython/blob/v3.12.0/Modules/audioop.c",
         "adpcm":vectors,
         "commands":[
             {"name":"get_state","hex":"0101010000000000","result":0},
             {"name":"detection","hex":"01040200785634126cee78ecf4016400","result":0},
             {"name":"start","hex":"010203007856341201","result":0},
             {"name":"heartbeat","hex":"0120040078563412","result":0},
             {"name":"double","hex":"011005007856341202500100d007","result":0},
             {"name":"stop","hex":"0111060078563412","result":0},
             {"name":"short","hex":"0101","result":1},
             {"name":"version","hex":"0201010000000000","result":2},
             {"name":"opcode","hex":"01ff010000000000","result":9},
             {"name":"profile","hex":"010201000000000009","result":3},
             {"name":"reserved","hex":"011005007856341202500101d007","result":3}
         ]}
(root/"contracts/golden_vectors.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
patterns_path=root/"contracts/patterns.json"
patterns=json.loads(patterns_path.read_text(encoding="utf-8"))
patterns["4"]["segments"]=[[5,i*100//199] for i in range(200)]
patterns_path.write_text(json.dumps(patterns,indent=2)+"\n",encoding="utf-8")
