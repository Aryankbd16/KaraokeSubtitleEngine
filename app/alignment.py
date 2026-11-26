from __future__ import annotations

import gc
import hashlib
import json
import logging
import math
import os
import tempfile
import unicodedata
import urllib.request
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .core import Cancellation, EngineError, Token, Word, validate_words

LOG = logging.getLogger(__name__)
SAMPLE_RATE = 16000
STRIDE = 320
RECEPTIVE_FIELD = 400
MAX_PATH_CELLS = 100_000_000
EN_FILE = "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
EN_SHA256 = "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d"
HI_REPOSITORY = "theainerd/Wav2Vec2-large-xlsr-hindi"
HI_REVISION = "3020b7d543a987afd986f1a5a241d47c588fe865"
HI_FILES = ("config.json", "vocab.json", "model.safetensors")


@dataclass(frozen=True)
class Language:
    label: str
    model: str
    script: str


LANGUAGES = {
    "en": Language("English", "WAV2VEC2_ASR_BASE_960H", "Latin"),
    "hi": Language("Hindi · देवनागरी", HI_REPOSITORY, "Devanagari"),
}


def check_language(language: str, tokens: list[Token]) -> None:
    if language not in LANGUAGES:
        raise EngineError("Choose English or Hindi in Devanagari.")
    letters = {c for token in tokens for c in token.normalized if c.isalpha()}
    if not letters:
        raise EngineError("Spell out numbers and abbreviations as they are spoken.")
    if language == "en":
        compatible = all("a" <= c <= "z" for c in letters)
    else:
        compatible = all("\u0900" <= c <= "\u097f" for c in letters)
    if not compatible:
        raise EngineError(f"Use {LANGUAGES[language].script} script for this language. "
                          "Romanized Hindi and mixed-script alignment are unavailable.")


def cache_dir() -> Path:
    custom = os.getenv("KARAOKE_DATA_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    base = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "KaraokeSubtitleEngine"


class Aligner(Protocol):
    def align(self, audio: Path, tokens: list[Token], language: str, device: str,
              cancel: Cancellation, status: Callable[[str], None]) -> list[Word]: ...


def ctc_path(log_probs: NDArray[np.float32], labels: list[int], blank: int,
             cancel: Cancellation) -> tuple[NDArray[np.int32], int]:
    """Viterbi alignment through the CTC blank/label state sequence."""
    frames = log_probs.shape[0]
    required = len(labels) + sum(a == b for a, b in zip(labels, labels[1:]))
    if not labels or frames < required:
        raise EngineError("The prepared audio is too short for the supplied script.")
    states = np.full(len(labels) * 2 + 1, blank, dtype=np.int32)
    states[1::2] = labels
    if states.size * frames > MAX_PATH_CELLS:
        raise EngineError("This recording and script are too long to align together. "
                          "Split them into shorter matching clips.")
    can_skip = np.zeros(states.size, dtype=bool)
    can_skip[3::2] = states[3::2] != states[1:-2:2]
    trace = np.zeros((frames, states.size), dtype=np.uint8)
    previous = np.full(states.size, -np.inf, dtype=np.float32)
    previous[0] = 0
    for frame, row in enumerate(log_probs):
        if frame % 100 == 0:
            cancel.check()
        advance = np.empty_like(previous)
        advance[0], advance[1:] = -np.inf, previous[:-1]
        skip = np.full_like(previous, -np.inf)
        skip[2:] = np.where(can_skip[2:], previous[:-2], -np.inf)
        move = advance > previous
        best = np.maximum(advance, previous)
        jump = skip > best
        trace[frame] = np.where(jump, 2, move)
        previous = np.maximum(skip, best) + row[states]
    state = states.size - (1 if previous[-1] >= previous[-2] else 2)
    if not np.isfinite(previous[state]):
        raise EngineError("The acoustic model could not align this script.")
    path = np.empty(frames, dtype=np.int32)
    for frame in range(frames - 1, -1, -1):
        path[frame] = state
        state -= int(trace[frame, state])
    return path, states.size


def align_emissions(log_probs: NDArray[np.float32], vocabulary: dict[str, int], blank: int,
                    tokens: list[Token], duration: float, cancel: Cancellation) -> list[Word]:
    labels: list[int] = []
    spans: list[tuple[int, int] | None] = []
    separator = vocabulary.get("|")
    alphabet = {unicodedata.normalize("NFKC", symbol).casefold(): index
                for symbol, index in vocabulary.items() if index != blank and len(symbol) == 1}
    max_length = max(map(len, alphabet), default=1)
    for token in tokens:
        word_labels: list[int] = []
        remaining = token.normalized
        while remaining:
            prefix = next((remaining[:size] for size in range(min(max_length, len(remaining)), 0, -1)
                           if remaining[:size] in alphabet), "")
            if not prefix:
                break
            word_labels.append(alphabet[prefix])
            remaining = remaining[len(prefix):]
        if remaining or not word_labels:
            spans.append(None)
            continue
        if labels and separator is not None:
            labels.append(separator)
        start = len(labels)
        labels.extend(word_labels)
        spans.append((start, len(labels)))
    if not labels:
        raise EngineError("The model alphabet cannot align any script words.")
    path, state_count = ctc_path(log_probs, labels, blank, cancel)
    frames = np.flatnonzero(path % 2 == 1)
    positions = path[frames] // 2
    starts = np.full(state_count // 2, log_probs.shape[0], dtype=int)
    ends = np.full_like(starts, -1)
    np.minimum.at(starts, positions, frames)
    np.maximum.at(ends, positions, frames)
    midpoint = RECEPTIVE_FIELD / 2
    result = []
    for token, span in zip(tokens, spans):
        if span is None:
            result.append(Word(token, issue="Punctuation only or outside the model alphabet"))
            continue
        first, last = span
        frame_lists = [np.arange(starts[i], ends[i] + 1) for i in range(first, last)]
        scores = [float(np.exp(log_probs[index, labels[i]]).mean())
                  for i, index in enumerate(frame_lists, first)]
        score = sum(scores) / len(scores)
        if score < 0.15:
            result.append(Word(token, score=score, issue="Insufficient acoustic evidence"))
            continue
        start = max(0.0, (starts[first] * STRIDE + midpoint - STRIDE / 2) / SAMPLE_RATE)
        end = min(duration, (ends[last - 1] * STRIDE + midpoint + STRIDE / 2) / SAMPLE_RATE)
        result.append(Word(token, start, end, score,
                           "Low acoustic score" if score < 0.45 else None))
    return validate_words(result, duration)


class Wav2VecAligner:
    """Direct Wav2Vec2 provider using the acoustic models selected by WhisperX."""

    def __init__(self, cache: Path | None = None) -> None:
        self.cache = cache or cache_dir() / "models"
        self._key: tuple[str, str] | None = None
        self._model = None
        self._metadata: dict = {}

    def model_files(self, language: str) -> dict[Path, str]:
        if language == "en":
            return {self.cache / "checkpoints" / EN_FILE:
                    f"https://download.pytorch.org/torchaudio/models/{EN_FILE}"}
        return {self.cache / "hi" / name:
                f"https://huggingface.co/{HI_REPOSITORY}/resolve/{HI_REVISION}/{name}"
                for name in HI_FILES}

    def ready(self, language: str) -> bool:
        return all(path.is_file() and path.stat().st_size > 0
                   for path in self.model_files(language))

    def prepare(self, language: str, cancel: Cancellation, status: Callable[[str], None]) -> None:
        """Download missing model files only after the caller obtains consent."""
        for path, url in self.model_files(language).items():
            cancel.check()
            if path.is_file() and path.stat().st_size:
                continue
            pending = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                status(f"Downloading {LANGUAGES[language].label} model files")
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
                    pending = Path(temp.name)
                    request = urllib.request.Request(url, headers={"User-Agent": "KaraokeSubtitleEngine/1.0"})
                    with urllib.request.urlopen(request, timeout=45) as source:
                        total = int(source.headers.get("Content-Length") or 0)
                        downloaded = 0
                        last_percent = -1
                        while chunk := source.read(1024 * 1024):
                            cancel.check()
                            temp.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                percent = min(100, downloaded * 100 // total)
                                if percent != last_percent:
                                    status(f"Downloading {LANGUAGES[language].label} model · {percent}%")
                                    last_percent = percent
                        if not downloaded or (total and downloaded != total):
                            raise EngineError("The model download was incomplete.")
                cancel.check()
                pending.replace(path)
            except OSError as exc:
                raise EngineError("Model download failed. Check the connection and available disk space.") from exc
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)

    def unload(self) -> None:
        self._model = None
        self._metadata = {}
        self._key = None
        gc.collect()

    def _load(self, language: str, device: str) -> None:
        key = (language, device)
        if self._key == key:
            return
        self.unload()
        if not self.ready(language):
            raise EngineError("The alignment model is missing. Approve its download in the app.")
        try:
            if language == "en":
                import torchaudio

                checkpoint = self.cache / "checkpoints" / EN_FILE
                with checkpoint.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != EN_SHA256:
                        raise EngineError("The English checkpoint is corrupt. Remove it and download it again.")
                bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
                self._model = bundle.get_model(dl_kwargs={"model_dir": str(checkpoint.parent)}).to(device)
                alphabet = {value: index for index, value in enumerate(bundle.get_labels())}
                self._metadata = {"type": "torchaudio", "dictionary": alphabet, "blank": 0}
            else:
                from transformers import Wav2Vec2ForCTC

                directory = self.cache / "hi"
                vocabulary = json.loads((directory / "vocab.json").read_text(encoding="utf-8"))
                self._model = Wav2Vec2ForCTC.from_pretrained(
                    directory, local_files_only=True, use_safetensors=True).to(device)
                self._metadata = {"type": "transformers", "dictionary": vocabulary,
                                  "blank": self._model.config.pad_token_id}
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError("Could not load the local alignment model. Check the ML installation "
                              "and see the diagnostic log.") from exc
        self._key = key

    def _emissions(self, samples: NDArray[np.float32], device: str, cancel: Cancellation,
                   status: Callable[[str], None]) -> NDArray[np.float32]:
        import torch

        if self._model is None:
            raise EngineError("Alignment model is unavailable.")
        outputs = []
        frame_count = (len(samples) - RECEPTIVE_FIELD) // STRIDE + 1
        window, context = 650, 50
        model = self._model.eval()
        is_torch = self._metadata["type"] == "torchaudio"
        for first in range(0, frame_count, window):
            cancel.check()
            status(f"Analyzing audio {min(99, round(first / frame_count * 100))}%")
            last = min(frame_count, first + window)
            left, right = max(0, first - context), min(frame_count, last + context)
            chunk = samples[left * STRIDE:(right - 1) * STRIDE + RECEPTIVE_FIELD]
            if not is_torch:
                chunk = (chunk - chunk.mean()) / math.sqrt(float(chunk.var()) + 1e-7)
            tensor = torch.from_numpy(chunk).unsqueeze(0).to(device)
            with torch.inference_mode():
                logits = model(tensor)[0] if is_torch else model(tensor).logits
                if logits.shape[1] != right - left:
                    raise EngineError("The model frame geometry is incompatible with this provider.")
                emission = logits[0, first - left:last - left].log_softmax(dim=-1)
                outputs.append(emission.cpu().numpy())
        if not outputs:
            raise EngineError("The prepared audio is too short.")
        return np.concatenate(outputs)

    def align(self, audio: Path, tokens: list[Token], language: str, device: str,
              cancel: Cancellation, status: Callable[[str], None]) -> list[Word]:
        check_language(language, tokens)
        try:
            import torch
        except (ImportError, OSError) as exc:
            raise EngineError("Install the PyTorch alignment dependencies before processing.") from exc
        with wave.open(str(audio), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise EngineError("Expected prepared 16 kHz mono PCM audio.")
            sample_count = wav.getnframes()
            estimated_states = 2 * sum(len(token.normalized) + 1 for token in tokens) + 1
            if sample_count > 1800 * SAMPLE_RATE or estimated_states * (sample_count // STRIDE) > MAX_PATH_CELLS:
                raise EngineError("This recording and script are too long to align together. "
                                  "Split them into shorter matching clips.")
            samples = np.frombuffer(wav.readframes(sample_count), dtype="<i2").astype(np.float32)
            samples /= 32768
        selected = "cuda" if device == "auto" and torch.cuda.is_available() else "cpu"
        try:
            status(f"Loading {LANGUAGES[language].label} model on {selected.upper()}")
            self._load(language, selected)
            emissions = self._emissions(samples, selected, cancel, status)
        except (EngineError, RuntimeError) as exc:
            if selected != "cuda" or cancel.event.is_set():
                raise
            LOG.warning("CUDA alignment failed. Switching to CPU.", exc_info=exc)
            self.unload()
            torch.cuda.empty_cache()
            status("CUDA unavailable for this job. Loading the CPU model.")
            self._load(language, "cpu")
            emissions = self._emissions(samples, "cpu", cancel, status)
        cancel.check()
        status("Matching script words to acoustic frames")
        dictionary = self._metadata["dictionary"]
        blank = self._metadata["blank"]
        return align_emissions(emissions, dictionary, blank, tokens,
                               len(samples) / SAMPLE_RATE, cancel)
