"""
Voice I/O — thin subprocess wrappers around whisper.cpp (STT) and piper
(TTS). Both are optional; if the binary or the model file is missing
the endpoints return 503 with a machine-readable body so the frontend
can hide the mic / speaker buttons gracefully.

Why subprocess instead of Python bindings:
  - whisper.cpp / piper are pre-compiled, tiny, and use their own
    optimized weights. No Python native code to build.
  - Both binaries stream — but for the UX we currently want (mic → text,
    text → wav download) a one-shot subprocess is enough.
  - Keeps runtime dependencies small; the studio doesn't need to pull
    torch just to transcribe a voice memo.

Env overrides:
  WHISPER_CLI          default: whisper-cli (on PATH)
  WHISPER_MODEL_PATH   default: models/whisper-base.en.bin
  PIPER_CLI            default: piper
  PIPER_VOICE_MODEL    default: models/en_US-lessac-medium.onnx
  PIPER_VOICE_CONFIG   default: models/en_US-lessac-medium.onnx.json
  AUDIO_TIMEOUT_S      default: 60
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("studio.audio")

DEFAULT_TIMEOUT_S = int(os.environ.get("AUDIO_TIMEOUT_S", "60"))


@dataclass(frozen=True)
class BinaryStatus:
    available: bool
    binary: str | None = None
    model: str | None = None
    reason: str | None = None


def _resolve(env_var: str, default: str) -> str:
    val = os.environ.get(env_var, "").strip()
    return val or default


def whisper_status() -> BinaryStatus:
    binary = _resolve("WHISPER_CLI", "whisper-cli")
    model = _resolve("WHISPER_MODEL_PATH", "models/whisper-base.en.bin")
    if not shutil.which(binary):
        return BinaryStatus(False, binary=binary, model=model, reason=f"{binary} not on PATH")
    if not Path(model).is_file():
        return BinaryStatus(False, binary=binary, model=model, reason=f"model {model} not found")
    return BinaryStatus(True, binary=binary, model=model)


def piper_status() -> BinaryStatus:
    binary = _resolve("PIPER_CLI", "piper")
    model = _resolve("PIPER_VOICE_MODEL", "models/en_US-lessac-medium.onnx")
    if not shutil.which(binary):
        return BinaryStatus(False, binary=binary, model=model, reason=f"{binary} not on PATH")
    if not Path(model).is_file():
        return BinaryStatus(False, binary=binary, model=model, reason=f"model {model} not found")
    return BinaryStatus(True, binary=binary, model=model)


def status() -> dict[str, Any]:
    """Frontend polls this once at load to decide whether to render the
    mic / speaker buttons."""
    w = whisper_status()
    p = piper_status()
    return {
        "transcribe": {"available": w.available, "reason": w.reason},
        "tts": {"available": p.available, "reason": p.reason},
    }


class AudioUnavailable(RuntimeError):
    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(f"{kind} unavailable: {reason}")
        self.kind = kind
        self.reason = reason


def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """Run whisper-cli against the given audio bytes and return the
    transcript. Raises AudioUnavailable if whisper isn't installed.

    The temp file is created inside the process's temp dir with the given
    suffix so whisper-cli's autodetection can pick the codec — it accepts
    common formats via ffmpeg-linked ingest.
    """
    st = whisper_status()
    if not st.available:
        raise AudioUnavailable("whisper", st.reason or "unknown")
    assert st.binary is not None and st.model is not None
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(audio_bytes)
        in_path = fh.name
    try:
        proc = subprocess.run(
            [st.binary, "-m", st.model, "-f", in_path, "-otxt", "--no-timestamps"],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        raise AudioUnavailable("whisper", f"timed out after {DEFAULT_TIMEOUT_S}s") from e
    finally:
        with contextlib.suppress(OSError):
            os.unlink(in_path)
    if proc.returncode != 0:
        raise AudioUnavailable("whisper", f"whisper-cli exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    # whisper-cli with `-otxt` writes to <input>.txt AND stdout; prefer stdout.
    text = proc.stdout.strip()
    if text:
        return text
    txt_out = Path(in_path).with_suffix(".txt")
    if txt_out.is_file():
        try:
            return txt_out.read_text(encoding="utf-8").strip()
        finally:
            with contextlib.suppress(OSError):
                txt_out.unlink()
    return ""


def synthesize(text: str) -> bytes:
    """Run piper against `text` and return the raw WAV bytes. Raises
    AudioUnavailable when piper or its model file are missing."""
    st = piper_status()
    if not st.available:
        raise AudioUnavailable("piper", st.reason or "unknown")
    assert st.binary is not None and st.model is not None
    text = (text or "").strip()
    if not text:
        raise AudioUnavailable("piper", "empty input")
    # Handle the tempfile inside the with-block just to satisfy SIM115;
    # we still keep the path around for the subprocess to write into.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
        pass
    try:
        proc = subprocess.run(
            [st.binary, "--model", st.model, "--output_file", out.name],
            input=text,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise AudioUnavailable("piper", f"piper exited {proc.returncode}: {proc.stderr.strip()[:400]}")
        return Path(out.name).read_bytes()
    except subprocess.TimeoutExpired as e:
        raise AudioUnavailable("piper", f"timed out after {DEFAULT_TIMEOUT_S}s") from e
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out.name)
