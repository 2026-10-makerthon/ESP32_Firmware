import json
from pathlib import Path
import pytest
from harness import codec
from harness.protocol import ProtocolError

VECTORS=json.loads((Path(__file__).resolve().parents[1]/"contracts/golden_vectors.json").read_text())


@pytest.mark.parametrize("vector",VECTORS["adpcm"],ids=lambda v:v["name"])
def test_independent_oracle(vector):
    block=bytes.fromhex(vector["block_hex"])
    assert codec.encode(vector["input_pcm"])==block
    assert codec.decode(block,len(vector["input_pcm"]))==vector["decoded_pcm"]


def test_bad_blocks():
    for block,count in [(bytes(3),1),(b"\0\0\x59\0",1),(b"\0\0\0\1",1),(b"\0\0\0\0\xf0",2)]:
        with pytest.raises(ProtocolError):codec.decode(block,count)


def test_lossy():
    v=VECTORS["adpcm"][-1]
    assert v["input_pcm"]!=v["decoded_pcm"]
