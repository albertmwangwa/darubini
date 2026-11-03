# Demo assets

## Demo video

`scripts/demo_video.py` renders a 1:48 motion-graphics video at 1920 × 1080 and 30 fps, with a synthesised music bed. The live lab session was not possible, so the video shows the results from our own train/test split instead.

Every number and image in it comes from the project:

| Scene | What it shows | Source |
| --- | --- | --- |
| Hook | 282 million cases and 610,000 deaths in 2024; Tanzania 4th for deaths | WHO World Malaria Report 2025 (see README) |
| Problem | A real thick-film field | NIH development field TF44_UW16 |
| App | The Android app's Start, voice and Report screens | Emulator screenshots in `docs/calibration/` |
| Two models | 281 candidates, 34 parasites kept, 17 white blood cells; the expert labelled 35 and 18 | Hybrid detections on the same development field |
| Tracking | The SAM 3.1 tracking clip: 31 counted frame by frame, 12 tracked once each, 0 duplicates across frames | `tracking_demo.mp4` and `tracking_demo.json` |
| Agent | Muse Spark's real tool names, and the Kiswahili report for held-out test slide TF65: 16,383 /µL against the expert's 16,142 /µL | `final_eval.py` test caches |
| Results | Parasite F1 0.80, 19 of 24 slides within 2×, *r* = 0.93, 8 of 8 over-counts flagged; the F1 ablation; UDOM F1 0.48 | [`calibration/final_test.md`](../calibration/final_test.md) |
| What it is and isn't | Not a screen, not a diagnosis | [`EVALUATION.md`](../EVALUATION.md) |

To regenerate the video, use the detection caches that `scripts/final_eval.py` writes:

```bash
python scripts/demo_video.py --prepare        # field image, detections, report → datasets/processed/demo/
python scripts/demo_video.py --still 40 80    # check single frames
python scripts/demo_video.py                  # datasets/processed/demo/darubini_demo.mp4
```

Notes:
- The video is about 8.5 MB. It is not committed: upload it to YouTube or the portal.
- The music is synthesised by the script, so it carries no licence. To use a licensed track instead, replace the audio in a video editor.

## Tracking demo

[`tracking_demo.mp4`](tracking_demo.mp4) is the output of `scripts/tracking_demo.py`. See STATUS.md, step 17.
