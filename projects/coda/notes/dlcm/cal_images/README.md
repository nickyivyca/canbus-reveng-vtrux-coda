# Calibration images by headline name

The maintained candidate CAL images (user 2026-10-17: moved out of the internal artifacts folder and named by their headline
names). **Simulation only. FLASHING IS NOT AUTHORISED**: being in this folder, or in `flash_cal.py`'s menu, authorises
nothing. Whether anything goes on the car is the user's decision alone.

| file | builder code | md5 | criteria | write-up |
|---|---|---|---|---|
| `0.13g-brakeblend-156nm.bin`, `.json` | K1+B25+FLAT31+R13P75+BBSW20P256+RDZ+G58 (since 2026-10-28) | `aa6377a143f216d6083697c65cd57815` | `../candidate-criteria.md` (0.13 g card) | `../next-flash-candidate-regen13-brakeblend.md`; RDZ: worklog 6H.84; chatter fix: drivetrain modeling worklog 3BU/3BV |
| `0.13g-brakeblend-156nm-nochatterfix.bin`, `.json` | K1+B25+FLAT31+R13P10+BBSW20P256+RDZ | `d917d46543513680472b5de5cde13163` | `../candidate-criteria.md` (0.13 g card) | as above, without the chatter fix |
| `illegal-onepedal-156nm.bin`, `.json` | K1+B25+FLAT31 | `f9885cedd82c87fae50c7b1cc138d769` | `../candidate-criteria.md` (illegal card) | `../next-flash-candidate-k1-b25-flat31.md` |

- **2026-10-27, user: this name now means the brake-blend image plus D's zero point in reverse (RDZ); the image
  flashed 2026-10-25 (K1+B25+FLAT31+R13P10+BBSW20P256, md5 `13679c3c...`) is deprecated** and no longer a builder
  candidate. It is still the image on the car until a reflash, archived as
  `../artifacts/cal_as_flashed_20261025_regen13_brakeblend.bin`; scripts that replay the 2026-10-25 drives or review the
  old candidate read that file. The two differ only in the R accelerator map, its pedal axis and ECM2's twins of both
  (370 bytes, `../artifacts/reverse_pedal_map.p5.out.txt`). `projects/coda/tools/flash_cal.py` lists the new md5
  `d917d465...` for this name (2026-10-28) and has no entry for the old image.
- **2026-10-28, user: "the new image would be the new 0.13g-brakeblend-156nm but also leave the no chatter
  modification as a primary profile".** The name now carries the highway chatter fix on top of RDZ: the 46.6 kW coast
  envelope above 31 mph (R13P75, was 50.5 kW) and CalBoundDerateBGain 230 -> 58 (G58). 157 bytes differ from the RDZ
  image: the gain, the D accelerator map's columns above 31 mph, the D brake map's same columns (the blend starts from
  the coast value) and ECM2's twins of both maps. The RDZ image stays as `0.13g-brakeblend-156nm-nochatterfix`, same
  bytes as before. Both are in `flash_cal.py` as candidates.
- Each `.json` is the builder's header: edit list, changed addresses, md5. Its `note` field ("NOT a flash candidate")
  dates from the build and is kept as written.
- The builder that writes these (and the scorecard and change-list
  scripts that read them) is internal-only; the images rebuild
  md5-identical from it.
- Read by `projects/coda/tools/flash_cal.py` (the menu) and by internal
  scorecard and change-list scripts.
- Before 2026-10-17 these lived under the internal artifacts folder with
  builder-code filenames; internal scripts and older plan text still name
  the old paths.
- The stock image is `../coda_dlcm_cal.bin`; the as-flashed images are
  held internally.
