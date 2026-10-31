# Regen and the stop lamps — the deceleration thresholds, and where the Coda's regen sits

2026-10-14, codasim / DLCM session, from web research the user asked for ("do some research, cite sources: typical
threshold for the brake lights turning on during regen braking"). Sources are listed at the end, each marked by how
it was read. The Coda side: the stop lamps are not lit by regen (`brake-lamp-relay.md`: the harness is built, the
software is not). This file motivates plan `../plans/next_flash_regen13_brake_blend.md`.

## 1. Regulations

### UN Regulation No. 13-H (EU type approval) — read in the regulation text

Paragraph 5.2.22.4: "Electric regenerative braking systems as defined in paragraph 2.17., which produce a retarding
force upon release of the accelerator control, shall generate the signal mentioned above according to the following
provisions:"

| vehicle deceleration | signal |
|---|---|
| <= 0.7 m/s2 (0.07 g) | shall not be generated |
| > 0.7 and <= 1.3 m/s2 | may be generated |
| > 1.3 m/s2 (0.13 g) | shall be generated |

"In all cases the signal shall be de-activated at the latest when the deceleration has fallen below 0.7 m/s2."
Footnote: at type approval, the vehicle manufacturer confirms compliance. Read in MLIT Japan's bilingual copy. The
English column prints "<" and ">"; the Japanese column reads "以下" (at or below) for the lower bands.

Search summaries of the same regulation add that, for automatically commanded braking and/or regenerative braking,
the signal may be generated at or below 1.3 m/s2 and shall be generated above it. Once generated, it may be suppressed
below 1.3 m/s2 or at standstill (attributed to Amendment 3 to Revision 4).

Rationale for the 0.7 / 1.3 pair: UNECE working paper GRVA-07-48 (2020), "UN Regulation No. 13-H Stop Lamp
Illumination", calls 1.3 m/s2 "a reasonable trigger value sufficiently different from the extinguishing value of
0.7 m/s2 to avoid flickering of the stop lamps in case of slow decelerations". **Read only through search-result
snippets; the PDF returned 403.**

### China, GB 21670-2025 — secondary source only

Stop lamps must light above 1.3 m/s2 of regenerative or automatic deceleration, may light at or below it, and must not
flicker when deceleration changes quickly. The same standard limits default-mode one-pedal regen to 3 m/s2, and in
default mode lifting off must not bring the car to a full stop. It applies to new type approvals from 2026-01-01; the
one-pedal rule applies about 13 months later. **Read in an English summary (chinastandards.org); the official text is
Chinese only.**

### United States, FMVSS 108 / 135 — no threshold

There is no deceleration threshold. The stop lamps must come on with the service brake and "may also be activated by
a device designed to retard the motion of the vehicle" (search summaries citing 49 CFR). Per a search summary of NHTSA
interpretation 09-001076as, lighting the stop lamps when the vehicle reaches a deceleration rate regardless of whether
the driver intended to brake would not be permissible. **Unverified: the NHTSA page returned 403.** CarBuzz (2023)
reports NHTSA confirming the US "does not require the lamps to be activated at a specific level of deceleration" and
that there is no open rulemaking.

## 2. What production cars do

| vehicle / source | threshold | basis |
|---|---|---|
| Consumer Reports test fleet (article 2023-06-09, updated 06-26) | about 0.1 g for most EVs | CR measurement |
| Hyundai Ioniq 5, Genesis GV60 / Electrified GV70 (~56,000 cars) | changed to > 1.3 m/s2 (about 0.13 g) | field service campaign, reported by CR |
| Kia EV6, Niro EV (~45,000 cars) | changed to about 0.13 g | software update, reported by CR |
| Mercedes-Benz EQS / EQE | about 0.15 g, lamps then go off as the car stops | reported by CR |
| Chevrolet Bolt | about 0.1 g; 2022+ cars keep the lamps on at a one-pedal stop, 2017-21 cars do not | owner forum, "confirmed by Chevrolet" per the forum |
| Tesla | about 0.1 g | owner forum |

Before the update, Hyundai/Kia i-Pedal could bring the car to a near stop without lighting the lamps (search summaries).

**The 0.2 g figure.** It appears only in owner-forum posts: one gives "0.2G" as the threshold and calls it too high on
some vehicles such as the Kia EV6; another speculates that future laws would require the lamps at "0.1g to 0.2g". The
Kia forum thread could not be opened (paywalled to bots), so whom it attributes the figure to is unknown. No regulation
or manufacturer source for 0.2 g was found. A forum claim of an EU threshold of 0.17 g contradicts the regulation text
above.

## 3. The Coda's regen, in g (model estimate)

Torque -> deceleration from the codasim plant constants (`tools/codasim/plant/lash.py`, from the clunk model): J_TOT
4.385 kg m2 at the motor and 0.04714 m of travel per motor rad, so a = T x 0.04714 / 4.385 (equivalent mass about
1,970 kg; wheel radius about 0.31 m with the 6.576 ratio). Regen only, with no drag or rolling resistance. Whether the
mass includes occupants is unknown, and 100 kg moves the result by about 5 %.

| speed | limit | motor torque | deceleration |
|---|---|---|---|
| below about 4 mph (C4c) | map: regen ends | 0 | 0 |
| 5 mph | map | -23.5 Nm | 0.03 g |
| 7.4 mph | map | -132.8 Nm | 0.15 g |
| 12.4-31 mph | map (one-pedal plateau, flash 5) | -156.2 Nm | 0.17 g |
| about 50 mph | 0x312 M_MIN (the DLCM's own published regen limit), median about 49 kW | about -100 Nm | about 0.11 g |
| about 62 mph | M_MIN | about -80 Nm | about 0.09 g |
| about 87 mph | M_MIN | about -57 Nm | about 0.06 g |

The 49 kW figure is the median of 0x312 M_MIN (transmitted by the DLCM itself, its published torque limit; DBC CM_ BO_ 786) above about 1750 rpm (`dlcm-cal-flash-campaign.md` section 5). It
follows the battery's charge limit, so it is lower with a full or cold battery. Off throttle the map also tapers above
31 mph (-135.2 Nm at 49.6 mph to -77.3 at 86.8). The brake map equals the coast map from 5 mph up (flash 5, option A),
so pressing the brake adds friction only.

Against R13-H, the plateau (about 0.17 g, 12-31 mph) is above the 1.3 m/s2 level at which the stop-lamp signal is
required. Above about 32 mph the estimate falls to the 0.7-1.3 m/s2 band, where it is optional.

## Sources

Read directly:
- [UN Regulation No. 13-H, bilingual text (MLIT Japan)](https://www.mlit.go.jp/jidosha/un/UN_R013H.pdf), paragraph 5.2.22.4
- [Consumer Reports: Brake Lights Can Fail to Provide Fair Warning on Some EVs](https://www.consumerreports.org/cars/car-safety/brake-lights-can-fail-to-provide-fair-warning-on-some-evs-a9533519285/)
- [ChinaStandards: GB 21670-2025 explained](https://chinastandards.org/news/china-gb-21670-2025-braking-standard-one-pedal-driving) (secondary)

Through search-result summaries only (the page could not be fetched, or was not fetched):
- [UN Regulation No. 13-H (EUR-Lex, 2023)](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX%3A42023X0401)
- [GRVA-07-48: UN Regulation No. 13-H Stop Lamp Illumination](https://www.unece.org/fileadmin/DAM/trans/doc/2020/wp29grva/GRVA-07-48e.pdf)
- [NHTSA interpretation 09-001076as](https://www.nhtsa.gov/interpretations/09-001076as)
- [CarBuzz: US EV brake-light law](https://carbuzz.com/features/theres-a-massive-safety-flaw-with-american-ev-laws/)
- [chevybolt.org: Brake Lights While Using One-Pedal Operation](https://www.chevybolt.org/threads/brake-lights-while-using-one-pedal-operation.50568/)
- [chevybolt.org: Brake lights on regen, new concern](https://www.chevybolt.org/threads/brake-lights-on-regen-new-concern.55407/)
- [teslamotorsclub.com: When do the brake lights come on?](https://teslamotorsclub.com/tmc/threads/when-do-the-brake-lights-come-on.204593/)
- [kiaevforums.com: Regen and Brake Lights](https://www.kiaevforums.com/threads/regen-and-brake-lights-observations-and-concerns-confirmed.5455/)
