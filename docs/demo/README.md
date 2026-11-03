# Demo assets

## Demo video: 3:00, in two cuts

`scripts/demo_video.py` renders the 3-minute demo video at 1920 × 1080 and 30 fps, in the Darubini Proposal colours. It is cut on the music's 2-second bar grid. Both cuts share the same picture:

| File | Sound |
| --- | --- |
| `darubini_demo_sfx.mp4` | Music and sound effects |
| `darubini_demo_narrated.mp4` | Music, sound effects and a female narrator; the music ducks under her |

The full script, with timings, what is on screen and every narration line, is in **[SCRIPT.md](SCRIPT.md)**. The narration text is in [narration.json](narration.json).

The story runs in this order:
1. The problem before Darubini: manual counting, and the malaria burden.
2. Darubini and the three Meta models it uses.
3. The app: capture, voice commands and the audit.
4. Two-stage detection on a real field.
5. SAM 3.1 tracking.
6. How it was trained, the best practices behind it and the best results.
7. The Muse Spark agent and the Kiswahili report.
8. The test results.
9. What it is and isn't.
10. The roadmap: TB, schistosomiasis, sleeping sickness, helminths, and simulated TB culture.

The craft follows the [/brag](https://github.com/latent-spaces/brag) skill:
- the real product, not abstract filler
- readable holds
- transitions that dip through the background instead of muddy crossfades
- cuts on the beat
- a soft sound-effect layer under the music
- a settled poster as frame 0

Every number is real; [SCRIPT.md](SCRIPT.md#sources) lists the sources. The roadmap scene is labelled "not yet built", and its culture plate is labelled as a simulation.

### Rebuilding

1. Copy the audio from a clone of `latent-spaces/brag` into `datasets/processed/demo/audio/`:
   - `skills/brag/assets/music/happy-beats-business-moves-vol-1-by-ende-dot-app.mp3`, renamed to `music.mp3`
   - the sound effects named in `sfx_plan()` in `scripts/demo_video.py`
2. Install the narrator in its own environment, so PyTorch stays out of the project:

   ```bash
   python -m venv .venv-tts
   .venv-tts/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   .venv-tts/Scripts/python -m pip install "kokoro>=0.9" soundfile
   ```

3. Run the steps:

   ```bash
   python scripts/demo_video.py --prepare           # field image, detections, report (needs the final_eval.py caches)
   .venv-tts/Scripts/python scripts/narrate.py      # narration WAVs and their durations
   python scripts/demo_video.py --still 40 100      # check frames
   python scripts/demo_video.py --script            # regenerate SCRIPT.md
   python scripts/demo_video.py                     # both videos, plus poster.jpg
   ```

The outputs land in `datasets/processed/demo/` and are not committed. Upload them to YouTube or the portal.

### Credits

- Music: "Happy Beats / Business Moves Vol. 1" by Sascha Ende, ende.app ([CC BY 4.0](https://ende.app/en/standard-license)). The credit is shown on screen.
- Sound effects: [Kenney](https://kenney.nl/) and unicae_games' Keyboard Soundpack #1, both CC0, via /brag.
- Narration: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache 2.0), voice `af_bella`.

## Tracking demo

[`tracking_demo.mp4`](tracking_demo.mp4) is the output of `scripts/tracking_demo.py`. See STATUS.md, step 17.
