# Creative Subtitle Studio architecture

## Alignment and presentation

The selected media and single-language spoken script enter the V1 pipeline in `Job.run`. FFprobe identifies the playable streams, FFmpeg extracts mono 16 kHz PCM, and the existing `Wav2VecAligner` returns immutable `Word` values. Model selection, acoustic scoring, offset calculation, and the alignment JSON schema are shared with V1.

A window retains one completed acoustic result in memory. Its key includes the resolved audio source, file size, modification time, spoken script, selected language and device. A style change, replacement-audio offset or display-only spelling can reuse that result. The job still calculates the current video-relative intervals and publishes a fresh report and collision-safe export. Opening the studio or changing its controls never invokes the aligner.

`Project.display_script` optionally supplies one display token per spoken token. The renderer consumes copies with those tokens substituted. The report keeps the acoustic script, its original spelling, confidence and timing. This supports visual code switching while keeping V1's monolingual acoustic contract.

## Subtitle generation

| Component | Contract |
| --- | --- |
| `core.Style` | V1 settings, defaults, installed-font option and legacy ASS layout |
| `styles.StudioStyle` | Validated, immutable bilingual presentation configuration |
| `font_library` | Catalog of genuine static faces, script choices, supported weights and per-job font staging |
| `styles.script_runs` | Assigns script-specific faces inside words while retaining combining signs and joiners |
| `subtitles.generate_ass` | Consumes timed words and either style type, returns an ASS script |
| `media.Media.render` | Renders with libass, encodes H.264/AAC, muxes and verifies the output |
| `presets.PresetStore` | Built-in definitions and atomic, versioned per-user preset storage |
| `studio.StudioDialog`, `preview.FramePreview` | Edit style snapshots, debounce work, cancel stale renders and display the latest valid frame |

ASS coordinates use a 1080-unit reference height and the source display aspect ratio. Studio layout measures shaped runs with HarfBuzz and the font's Windows ascent/descent, matching libass sizing. At most two lines share a phrase. Width, word count, paragraph breaks, punctuation and timing gaps control grouping. A single overlong token scales horizontally to fit. Positioned line events implement adjustable line spacing. A separate ASS drawing under each line provides box color and opacity independently of outline and shadow.

Word highlighting uses the V1 convention of absolute start/end events rounded to centiseconds. During a gap the caption can remain visible with no active word. Static presets span the phrase's visible interval. Each script run gets a font override using the font's internal legacy family name, numeric weight, explicit italic state and color. Using the legacy name matters for Windows selection of Medium and SemiBold static faces. An unrepresentable glyph produces an actionable rendering error.

## Preview and export

Each dialog owns one worker and a temporary directory. The preview caches one lossless source frame, retains its native dimensions during ASS rendering, and scales the result for display. The sample uses illustrative word times. Without a video it uses a neutral sample frame. A failed render leaves the last successful frame on screen. Closing the dialog cancels pending work and removes the workspace.

Qt registration is process-local. Both FFmpeg paths explicitly stage font faces in a flat relative `fonts` directory and use `ass=captions.ass:fontsdir=fonts:shaping=complex`. Relative filter arguments keep Unicode, apostrophes and drive letters in user paths out of the filter syntax. Font files use hard links where possible and copies otherwise. Each export keeps V1's input maps, cancellation, progress, stream validation, and publication semantics. A standalone ASS file still needs the same fonts in its rendering environment.

## Preset schema

`subtitle-presets.json` lives in the app data directory. Version 1 of this storage format contains `version`, `presets` (custom name to style), `selected` and `current` (applied style snapshot). V1 of the application had no persisted preset library. New optional fields receive defaults. Malformed entries are skipped. An unreadable or unsupported library opens with a notice and session-only settings, preserving the file. Move that file aside to start a fresh library.

Read-modify-write operations acquire a Qt file lock, reload the latest library and atomically replace the file with a sibling temporary file. Built-ins live in an immutable mapping. Applying an edited built-in saves a snapshot. Naming a custom copy is a separate operation.

## Verification

The original tests cover the acoustic, export and desktop contracts. Studio tests additionally inspect TTF metadata and licensing, probe libass face selection, compare preview pixels with decoded H.264 output, exercise the preset lifecycle, test preview-error recovery, and verify report equality across restyles. Opt-in model cases exercise both V1 and studio exports with matching speech recordings. See the [README](README.md) for commands.
