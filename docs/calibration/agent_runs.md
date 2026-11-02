# Agent runs on NIH validation slides (31 Oct)

Generated from the transcripts in this folder (`agent_<slide>.json`): `darubini agent <slide folder> --language sw --segmenter hybrid`, with Muse Spark quality reviews and the parasite audit. Expert and Darubini figures compare the same labelled, usable fields; densities use 8,000 WBC/µL. The audited density is the count times the confirmed share. These are validation slides, not test results.

| Slide | Fields used / examined | Excluded | Tool calls | Expert P / WBC | Count P / WBC | Expert density | Count density | Audit confirmed | Audited density | Flag |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| TF31_Sc440 | 18 / 20 | 2 | 14 | 100 / 209 | 617 / 207 | 3,828 | 23,845 | 6/20 | 7,154 | yes |
| TF52_CW36 | 7 / 8 | 0 | 13 | 30 / 177 | 53 / 185 | 1,356 | 2,292 | 7/20 | 802 | yes |
| TF30_W13B1 | 13 / 14 | 0 | 10 | 3102 / 200 | 3103 / 194 | 124,080 | 127,959 | 13/20 | 83,173 | no |

TF52 and TF30 each had one examined field without labels; it is left out of both columns.
