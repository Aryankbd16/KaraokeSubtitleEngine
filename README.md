# Karaoke Subtitle Engine

Karaoke Subtitle Engine is a local Windows desktop application for turning a video and its exact spoken or sung script into an MP4 with word-by-word karaoke captions. Choose the video's audio or provide a replacement track. The app preserves script spelling and punctuation for display, estimates word intervals with a local acoustic model, and burns the captions into the picture.

## Quick start on Windows

In a built workspace, double-click **Launch Karaoke.cmd** to open the packaged application. The launcher can reuse FFmpeg and model files downloaded during verification in this checkout. Keep the entire `dist/KaraokeSubtitleEngine` folder together if you move the package, and install FFmpeg on the destination computer.

For a source checkout without the package:

1. Install [64-bit Python 3.12](https://www.python.org/downloads/windows/) with the `py` launcher, and install an [FFmpeg build for Windows](https://ffmpeg.org/download.html#build-windows) containing both `ffmpeg.exe` and `ffprobe.exe`. The build must include libass with complex text shaping and the libx264 encoder.
2. Double-click **Setup Karaoke.cmd** to make the local Python environment and install CPU dependencies.
3. Double-click **Launch Karaoke.cmd**.
4. Select a video. If needed, choose a replacement audio file and set the offset. Paste the exact script, select its language, and click **Generate Karaoke Video**.
5. Approve the first model download for that language. When export finishes, use **Play video** to open the MP4 in your system player, or open the output folder and alignment report.

With Windows Package Manager, these commands install the system prerequisites. Open a fresh terminal after installation.

```powershell
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e
ffmpeg -version
ffprobe -version
```

For manual FFmpeg setup, extract the archive and add the directory containing both executables to PATH. You can also point `KARAOKE_FFMPEG` and `KARAOKE_FFPROBE` at their full executable paths before launching. Install the [Microsoft Visual C++ x64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) if a native Python wheel reports a missing Visual C++ runtime.

## Source setup

Windows x64 and Python 3.12 are the primary target. A recent multicore CPU and 8 GB RAM are a practical starting point for English. Allow more RAM for the Hindi model and for large videos. Allow several GB for the environment, models and temporary output. The rendering workspace can hold a video-only MP4, an AAC track and the combined MP4 at the same time.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

For optional NVIDIA acceleration, use a fresh environment with matching CUDA builds for torch and torchaudio. For a compatible Windows x64 NVIDIA driver, replace the CPU-wheel install above with the CUDA 12.6 wheel command below and choose **Auto** in Settings. The application uses CPU when CUDA is unavailable or when GPU alignment fails. GPU covers alignment inference. FFmpeg encoding uses CPU.

```powershell
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu126 torch==2.8.0 torchaudio==2.8.0
```

Use the [PyTorch previous versions wheel matrix](https://pytorch.org/get-started/previous-versions/) when choosing a CUDA build. CUDA and GPU fallback require separate hardware verification. On Linux and macOS, use your system package manager for FFmpeg, create a Python 3.12 virtual environment, and select the platform's PyTorch wheels. These platforms have their own Qt and FFmpeg runtime requirements and were outside the Windows verification run.

## Formats and alignment

| Input | Formats |
| --- | --- |
| Video | MP4, MOV, MKV, AVI, WebM |
| Replacement audio | WAV, MP3, M4A, AAC, FLAC, OGG |
| Input script | English Latin text or Hindi Devanagari |

| Language | Acoustic checkpoint | First download |
| --- | --- | --- |
| English | TorchAudio `WAV2VEC2_ASR_BASE_960H` | 378 MB |
| Hindi in Devanagari | `theainerd/Wav2Vec2-large-xlsr-hindi`, pinned revision | 1.26 GB |

Choose the spoken language manually. Romanized Hindi and mixed Latin–Devanagari scripts are rejected for alignment. English spelling in Latin letters cannot distinguish English speech from romanized speech automatically. Hindi loans written in Devanagari may still receive weak acoustic scores. Spell out numbers and abbreviations as spoken. Paste paragraphs to suggest where to begin a new caption.

Windows models are stored under `%LOCALAPPDATA%\KaraokeSubtitleEngine\models`. The default on Unix-like platforms is `$XDG_CACHE_HOME/KaraokeSubtitleEngine/models` or `~/.cache/KaraokeSubtitleEngine/models`. Set `KARAOKE_DATA_DIR` to choose the parent directory for both models and logs. **Settings → Open model folder** opens the active location. The app downloads missing files after confirmation and uses the local files for subsequent jobs. It caches the active model in memory across exports. Restart the app to free the cache. For a corrupt model, remove that language's files from the model directory and approve a fresh download.

The English files go in `models/checkpoints` and the Hindi files in `models/hi`. An offline installation can copy an already populated model directory. A standalone transcription engine, VAD model download, API credential and network processing are unnecessary.

## Timing, subtitles and output

- **Offset.** Positive values delay replacement audio and captions. The renderer adds leading silence. Negative values advance both timelines and trim the corresponding beginning of the replacement audio. The selected video's played duration controls the export. Longer audio is trimmed, shorter audio is padded, and significant duration mismatches appear in the UI and report. Embedded audio keeps its relative stream start. Only the first playable video stream and first audio stream are used.
- **Highlighting.** ASS events divide each phrase at absolute word starts and ends, rounded to centiseconds. The upcoming, active and completed colors are applied independently, including between words when no word is active. At video frame boundaries, visibility follows the video's frame rate. The caption preview shows the style and placement. Final widths also depend on the video aspect ratio and the font metrics used by libass.
- **Output.** The app writes `<video>_karaoke.mp4` plus `<video>_karaoke.alignment.json` next to the source, or in the selected output folder. Settings enables an additional `.ass` file. Name collisions receive a numeric suffix. The report records display and normalized text, source and video timestamps, acoustic scores, and word-level issues. Scores are heuristics derived from acoustic emissions and do not represent calibrated probabilities. Words with unsupported characters or weak evidence receive no highlight interval. A job with no visible aligned words fails.
- **Encoding.** Output is H.264 video with AAC audio. The original audio content is carried through when embedded audio is selected, with AAC re-encoding for compatibility. Odd resolutions are padded by at most one pixel per dimension for 4:2:0 output. The app checks the resulting streams and duration using FFprobe. FFmpeg processes audio and picture separately before muxing.
- **Privacy.** The media and script stay local. The alignment report contains script text. The diagnostic log is separate and uses a rotating file under the data directory. FFmpeg commands are constructed as argument lists, and every job uses a unique workspace that is removed when the job exits.

## Architecture

| File or directory | Responsibility |
| --- | --- |
| `app/main.py` | Desktop startup and diagnostic logging |
| `app/ui.py`, `app/preview.py` | Native Qt controls, preview, worker-thread lifecycle and output actions |
| `app/core.py` | Configuration, token mapping, timing validation and cancellation |
| `app/media.py` | FFmpeg discovery and execution, inspection, audio preparation, encoding and output validation |
| `app/alignment.py` | Provider contract, language registry, model acquisition and CTC forced alignment |
| `app/subtitles.py` | Phrase grouping and ASS event generation |
| `app/jobs.py` | Pipeline coordination, diagnostic reports, temporary workspaces and output publication |
| `app/fonts/` | Noto Sans Devanagari and its license |
| `tests/`, `scripts/` | Test suite and Windows packaging entry point |

The Windows WhisperX dependency install did not resolve in the verification environment. The production provider uses the same Wav2Vec2 model families directly through TorchAudio and Transformers. FFmpeg decodes the selected track to mono 16 kHz PCM for acoustic inference. The CTC Viterbi path consumes the normalized script labels in order, with explicit blank and repeat transitions. Waveform windows include context on both sides while keeping frame coordinates on one continuous timeline. The engine derives word intervals from matched acoustic frames and preserves the original display tokens.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe -m app.main --smoke
```

The suite checks token mapping, deterministic CTC paths, timing, ASS, reports, cleanup, and desktop behavior with controlled inputs. FFmpeg tests create disposable videos and compare output pixels, audio onset and audio frequency. They require both binaries on PATH or explicit executable overrides. The UI tests use Qt's offscreen platform. Real model tests are opt-in and separate from controlled alignment fixtures. Download the relevant models in the app first, then supply short matching test recordings.

```powershell
$env:KARAOKE_TEST_EN_WAV = 'C:\samples\english.wav'
$env:KARAOKE_TEST_EN_SCRIPT = 'Every word shines brightly.'
$env:KARAOKE_TEST_HI_WAV = 'C:\samples\hindi.wav'
$env:KARAOKE_TEST_HI_SCRIPT = 'नमस्ते दुनिया।'
# If the models are in a different folder:
# $env:KARAOKE_TEST_MODELS = 'C:\samples\models'
.\.venv\Scripts\python.exe -m pytest -m model -v -s
```

The Windows verification run passed 19 tests with both real-model cases enabled. It used Python 3.12.14, CPU PyTorch 2.8.0, Qt 6.12.0 and FFmpeg 9.1. The English Windows speech-synthesis clip aligned four words. The Hindi eSpeak NG clip aligned two words, and the burned-in export was visually checked for Devanagari shaping and highlighting. These short speech fixtures do not establish alignment accuracy for musical recordings. Transformers emitted a configuration deprecation warning on the Hindi checkpoint.

The Windows one-folder packaging script uses the virtual environment and runs a startup smoke test after building. The generated Windows executable passed its native startup smoke test. Both real-model exports also passed through a console diagnostic entry point using the packaged runtime. Model files and FFmpeg are resolved at runtime.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

## Troubleshooting and limits

- **Missing FFmpeg, libass or libx264.** Run both version commands and verify `ffmpeg -filters` lists the `ass` filter and `ffmpeg -encoders` lists `libx264`. Reopen the app after changing PATH.
- **Missing or weak word intervals.** Compare the audio with the exact script, check the language, and inspect the JSON for unsupported spelling or weak matches. A clean isolated voice usually works better than a dense music mix. Singing, overlapping voices, compression artifacts and code switching have lower expected accuracy than clean single-speaker speech.
- **CPU time or memory.** Model loading and long exports can take several minutes. The alignment path uses a memory budget that depends on both script length and audio duration. Dense clips may reach it after a few minutes. Split long inputs into matching video and script sections. Cancellation takes effect between acoustic inference windows or after an in-flight model load returns. FFmpeg is stopped on cancellation.
- **Typography.** The Hindi default uses bundled Noto Sans Devanagari. FFmpeg uses bundled and installed fonts. Install a font appropriate for the intended script or choose the bundled Hindi font if an installed font displays missing glyphs. The ASS file depends on fonts available to the playback or rendering system.
- **Playback and media compatibility.** Playback opens in the system player. For unusual variable-frame-rate containers with incomplete duration metadata, remux or transcode into a clean MP4 first. The app uses the first qualifying streams and standard SDR H.264 output. HDR mastering, multiple audio tracks and manual timeline editing are outside Version 1.

## Third-party licenses

- The English Wav2Vec2 checkpoint is MIT-licensed as documented by [TorchAudio](https://docs.pytorch.org/audio/2.0.0/generated/torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.html).
- The Hindi checkpoint's [model card at the pinned revision](https://huggingface.co/theainerd/Wav2Vec2-large-xlsr-hindi/tree/3020b7d543a987afd986f1a5a241d47c588fe865) does not declare an explicit license for the fine-tuned weights. Its upstream model and training material have separate terms. The Hindi weights are acquired separately and should not be redistributed without clarifying rights with the publisher.
- The bundled [Noto Sans Devanagari](https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSansDevanagari) is licensed under SIL OFL 1.1. The notice is in `app/fonts/OFL.txt`.
- [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html) is available under LGPLv3, GPLv3 or commercial terms, with obligations that depend on the distribution. [PyTorch](https://github.com/pytorch/pytorch/blob/main/LICENSE) and [TorchAudio](https://github.com/pytorch/audio/blob/main/LICENSE) carry BSD-style licenses. [Transformers](https://github.com/huggingface/transformers/blob/main/LICENSE) is Apache 2.0. [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) is BSD-licensed.
- FFmpeg's license depends on build configuration. Builds with libx264 generally enable GPL components. The package uses an external FFmpeg installation. See the [FFmpeg license documentation](https://ffmpeg.org/legal.html) before redistributing a build.

## Next development phase

Collect a pronunciation- and genre-diverse validation corpus, measure timing and coverage, and use those results to build a manual correction workflow. The provider interface is the extension point for code switching and aligners tuned for singing.
