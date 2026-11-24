"""Optional content-addressed tokenizer files installed by the server operator."""

import hashlib
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from tokenizers import Tokenizer
from argus.config import HOME


def directory():
    return Path(os.getenv("ARGUS_TOKENIZER_DIR", str(HOME / "tokenizers")))


def installed():
    return sorted(
        p.stem
        for p in directory().glob("*.json")
        if re.fullmatch("[0-9a-f]{64}", p.stem)
    )


@lru_cache(maxsize=16)
def adapter(digest):
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Invalid tokenizer hash")
    data = (directory() / (digest + ".json")).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Tokenizer checksum mismatch")
    return Tokenizer.from_buffer(data)


def count(text, digest=None):
    if digest:
        return len(adapter(digest).encode(text, add_special_tokens=False).ids)
    return math.ceil(len(text.encode()) / 4)
