"""backend.audio unit tests. All subprocess calls are patched — we
deliberately don't require whisper/piper installed on the test host."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend import audio


class TestWhisperStatus:
    def test_missing_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _: None)
        st = audio.whisper_status()
        assert st.available is False
        assert st.reason is not None and "not on PATH" in st.reason

    def test_binary_present_model_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/whisper-cli")
        monkeypatch.setenv("WHISPER_MODEL_PATH", str(tmp_path / "no-model"))
        st = audio.whisper_status()
        assert st.available is False
        assert "model" in (st.reason or "").lower()

    def test_all_present(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "w.bin"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/whisper-cli")
        monkeypatch.setenv("WHISPER_MODEL_PATH", str(model))
        st = audio.whisper_status()
        assert st.available is True


class TestPiperStatus:
    def test_all_present(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "voice.onnx"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/piper")
        monkeypatch.setenv("PIPER_VOICE_MODEL", str(model))
        st = audio.piper_status()
        assert st.available is True


class TestStatusEndpointShape:
    def test_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _: None)
        s = audio.status()
        assert set(s.keys()) == {"transcribe", "tts"}
        assert s["transcribe"]["available"] is False
        assert s["tts"]["available"] is False


class TestTranscribe:
    def test_raises_when_whisper_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _: None)
        with pytest.raises(audio.AudioUnavailable):
            audio.transcribe(b"anything")

    def test_success_from_stdout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "w.bin"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/whisper-cli")
        monkeypatch.setenv("WHISPER_MODEL_PATH", str(model))
        fake = MagicMock(returncode=0, stdout=" hello world \n", stderr="")
        with patch("subprocess.run", return_value=fake) as sp:
            got = audio.transcribe(b"pcm-bytes", suffix=".wav")
        assert got == "hello world"
        # Confirm we invoked the whisper binary with the model + input.
        args = sp.call_args.args[0]
        assert args[0] == "whisper-cli"
        assert "-m" in args and str(model) in args

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "w.bin"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/whisper-cli")
        monkeypatch.setenv("WHISPER_MODEL_PATH", str(model))
        fake = MagicMock(returncode=2, stdout="", stderr="bad audio format")
        with (
            patch("subprocess.run", return_value=fake),
            pytest.raises(audio.AudioUnavailable, match="bad audio format"),
        ):
            audio.transcribe(b"noise")

    def test_timeout_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "w.bin"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/whisper-cli")
        monkeypatch.setenv("WHISPER_MODEL_PATH", str(model))
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="whisper-cli", timeout=1)),
            pytest.raises(audio.AudioUnavailable, match="timed out"),
        ):
            audio.transcribe(b"x")


class TestSynthesize:
    def test_empty_input_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "v.onnx"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/piper")
        monkeypatch.setenv("PIPER_VOICE_MODEL", str(model))
        with pytest.raises(audio.AudioUnavailable, match="empty"):
            audio.synthesize("   ")

    def test_success_returns_bytes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        model = tmp_path / "v.onnx"
        model.write_bytes(b"x")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/piper")
        monkeypatch.setenv("PIPER_VOICE_MODEL", str(model))

        # We can't fake the OS-level "piper writes a wav" side effect cleanly
        # without patching Path.read_bytes. Do so, but only for the specific
        # temp file piper "wrote".
        fake_wav = b"RIFF\0\0\0\0WAVEfmt " + b"\0" * 32
        real_read = Path.read_bytes

        def _read_bytes(self):
            if self.suffix == ".wav":
                return fake_wav
            return real_read(self)

        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=fake_proc), patch.object(Path, "read_bytes", _read_bytes):
            got = audio.synthesize("hello")
        assert got == fake_wav
