#!/usr/bin/env python3
"""Upload CAN log data to InfluxDB 1.x for Grafana visualization.

Two measurements are written:
  signals  -- DBC-decoded signal values, one point per decoded frame
  raw      -- raw bytes for frames not in the DBC (only with --raw)

Each point carries a 'bus' tag (e.g. powertrain/vehicle/obd for Vtrux,
b_can/c_can/d_can for Coda) derived by matching anchor IDs to channel numbers.

Write policy (--write-policy, default on-change): a signal value is written
only when it differs from the last value written for that signal, plus a
heartbeat point at most every --heartbeat seconds so gaps stay bounded and
Grafana's last-value-before-window stays correct. Measured 3.5x less disk
than writing every frame; see the internal `influx-sync` plan.

Requires:  pip install cantools requests
"""
import argparse
import contextlib
import glob
import hashlib
import io
import json
import os
import queue
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.parsers.autodetect import detect_format
from canre.parsers.busmaster import BusmasterParser
from canre.dbc.msghash import message_hashes
from canre.utils.timebase import TimebaseIndex

try:
    import cantools
except ImportError:
    cantools = None

try:
    import requests
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# Vehicle profiles — hardcoded DBCs and bus anchor IDs
#
# bus_anchors: ordered list of (bus_name, {anchor_id, ...}).
#   A channel is assigned the name of the first anchor set that overlaps
#   with the IDs seen on that channel. Order matters — put the most
#   distinctive anchor first.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The unidentified-channel namespace.
#
# A channel matching no anchor set is still uploaded, under the fallback bus
# tag `ch<N>` -- N being the raw channel number, which is meaningless across
# captures (AGENTS.md: never identify a bus by channel number). The tag is
# therefore an admission that the bus is UNKNOWN, not a bus name.
#
# It gets a named producer and a named recogniser here because having the
# format implicit in an f-string let three consumers disagree about it, all
# silently, and each disagreement cost real data:
#
#   * `message_hashes()` is built over the NAMED buses only, so a `ch<N>` key
#     has no definition hash. influx_sync's L0 compares manifest hashes against
#     it and had to learn to normalise the missing value, or every such file
#     drifted on every run and never converged (see the note at its `drift`).
#   * influx_sync's L1 orphan test never learned the same lesson. It asks only
#     `(bus, can_id) in current_hashes()`, which no `ch<N>` pair can satisfy, so
#     it condemned EVERY unidentified-channel series as an orphan -- 147 of them
#     on 2026-10-04, including 8 written minutes earlier by the fixed uploader
#     and 161,917 field-values of vtrux data unrelated to that work.
#   * the profile `exclude` lists are keyed `(bus_name, can_id)`, so a
#     bus-scoped exclusion does NOT apply to `ch<N>`. A channel demoted to
#     `ch<N>` therefore uploads gateway-rebroadcast copies that the same frames
#     would have had excluded under a named bus. Measured, not inferred: the
#     `coda_20260807_192700` tail wrote nothing while labelled `d_can` because
#     all five of its ids are d_can-excluded, and five series once it became
#     `ch1`.
#
# The third item is a BEHAVIOUR question, not a defect to patch here -- it needs
# a decision about what an unidentified channel should decode against at all.
# It is recorded so the next reader does not have to rediscover it.
UNIDENTIFIED_BUS_RE = re.compile(r"^ch(\d+)$")


def unidentified_bus_name(channel) -> str:
    """The fallback bus tag for a channel no anchor set identified."""
    return f"ch{channel}"


def is_unidentified_bus(bus: str) -> bool:
    """True if `bus` is a fallback tag from unidentified_bus_name()."""
    return bool(UNIDENTIFIED_BUS_RE.match(bus or ""))

VEHICLE_PROFILES = {
    "vtrux": {
        "dbcs": [
            PROJECT_ROOT / "projects/vtrux/GMW8762_PPEI_GMLAN.dbc",
            PROJECT_ROOT / "projects/vtrux/epri-pt-bus.dbc",
            PROJECT_ROOT / "projects/vtrux/epri-obd-bus.dbc",
            PROJECT_ROOT / "projects/vtrux/BelInverter-v2.dbc",
            PROJECT_ROOT / "projects/vtrux/vtrux-powertrain-experimental.dbc",
            PROJECT_ROOT / "projects/vtrux/vtrux-obd-experimental.dbc",
        ],
        # Powertrain: 0x051 is exclusive and fires at 100 Hz — most reliable anchor
        # Vehicle (Vehicle): 0x1E5/0x500 never appear on the other buses
        # OBD: 0x040-0x044 exclusive to OBD bus
        "bus_anchors": [
            ("powertrain", {0x051}),
            ("vehicle",    {0x1E5, 0x500}),
            ("obd",        {0x040, 0x041, 0x042, 0x043, 0x044}),
        ],
        # Exclusions: each entry is one of:
        #   {"signal": "Name", "bus": "..."}   -- exclude signal by name on a specific bus
        #   {"signal": "Name"}                 -- exclude signal on all buses
        #   {"can_id": 0xXXX, "bus": "..."}    -- exclude entire message on a specific bus
        #   {"can_id": 0xXXX}                  -- exclude entire message on all buses
        #
        # VCM gateway modifications:
        # OBD bus carries wrong/synthetic data for these IDs — real data is on Vehicle bus.
        # Vehicle bus carries wrong/synthetic data for these IDs — real data is on OBD bus.
        # Faithfully bridged IDs are excluded from the non-source bus to avoid duplicates.
        "exclude": [
            # --- OBD bus: VCM-modified or spoofed content (real data on Vehicle bus) ---
            {"can_id": 0x0C1, "bus": "obd"},  # Driven wheel speeds masked to all zeros
            {"can_id": 0x0C5, "bus": "obd"},  # Non-driven wheel speeds masked to all zeros
            {"can_id": 0x0F9, "bus": "obd"},  # TCM stub: torque ratio canned, shaft speed zero, B5-B7=0xFF
            {"can_id": 0x1C7, "bus": "obd"},  # EBCM torque requests frozen to constant (B0=0x07, B1=0x02)
            {"can_id": 0x1E9, "bus": "obd"},  # Chassis status fully frozen (all 8 bytes constant)
            {"can_id": 0x1F5, "bus": "obd"},  # Transmission position frozen at Park
            {"can_id": 0x3E9, "bus": "obd"},  # Vehicle speed frozen at zero (cascade: VCM masks wheel inputs to ECM)
            # EBCM messages faithfully bridged to OBD bus (source = Vehicle bus)
            {"can_id": 0x2F9, "bus": "obd"},  # EBCM reference -- identical on both buses; Vehicle is native
            {"can_id": 0x1CF, "bus": "obd"},  # TCCM/RDCM torque request -- identical on both; Vehicle is native
            # --- Vehicle bus: VCM-synthetic ECM content (real data on OBD bus) ---
            {"can_id": 0x0C9, "bus": "vehicle"},  # All ECM signals synthetic (~800 RPM motor idle, not real engine)
            {"can_id": 0x1C3, "bus": "vehicle"},  # Motor torque substituted for engine torque
            {"can_id": 0x1C5, "bus": "vehicle"},  # Axle torque reporting adjusted by VCM
            # ECM messages faithfully bridged to Vehicle bus (source = OBD bus)
            {"can_id": 0x3C1, "bus": "vehicle"},  # Engine_General_Status_6 -- identical on both; OBD is native
            {"can_id": 0x3F9, "bus": "vehicle"},  # Engine_General_Status_3 -- identical on both; OBD is native
            {"can_id": 0x3FB, "bus": "vehicle"},  # Engine_Torque_Status_1 -- identical on both; OBD is native
            {"can_id": 0x4D1, "bus": "vehicle"},  # Engine_Torque_Status_5 -- identical on both; OBD is native
            # --- Vehicle bus: high-rate messages not useful for EV analysis ---
            {"can_id": 0x0C1, "bus": "vehicle"},  # Wheel distance accumulators (10-bit rollover counters, not graphable speed; use 0x3E9 for vehicle speed)
            {"can_id": 0x0C5, "bus": "vehicle"},  # Non-driven wheel distance accumulators -- same
            {"can_id": 0x1E5, "bus": "vehicle"},  # Steering wheel angle -- not used in Vtrux analysis
            {"can_id": 0x1C4, "bus": "vehicle"},  # Accelerator pedal override -- irrelevant for EV drivetrain
            {"can_id": 0x1C4, "bus": "obd"},      # Same message bridged to OBD
            {"can_id": 0x1F1, "bus": "vehicle"},  # A/C + fuel flags -- faithfully bridged; keep OBD copy
            {"can_id": 0x2C3, "bus": "vehicle"},  # Engine MAP/max torque -- B3 frozen on Vehicle; keep OBD copy
            {"can_id": 0x3D1, "bus": "vehicle"},  # TPS/DFCO/A/C cmd -- B3 frozen on Vehicle; keep OBD copy
            # --- OBD 0x0C9: trim to the 6 signals we use; exclude the other 18 ---
            # Kept: Engine_Speed, Engine_Run_Active, Engine_Idle_Active, Cruise_Control_Active,
            #       Accelerator_Actual_Position, Accelerator_Actual_Position_Validity
            {"signal": "Cruise_Control_Enabled",                                "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detected",                     "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detected_Protection_Value",    "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detection_Alive_Rolling_Count","bus": "obd"},
            {"signal": "Engine_Cylinder_Deactivation_Event_Pending",            "bus": "obd"},
            {"signal": "Engine_Cylinder_Deactivation_Mode",                     "bus": "obd"},
            {"signal": "Engine_Intake_Air_Boost_Pressure",                      "bus": "obd"},
            {"signal": "Engine_Intake_Air_Boost_Pressure_Validity",             "bus": "obd"},
            {"signal": "Engine_Speed_Status",                                   "bus": "obd"},
            {"signal": "Platform_Engine_Speed_Command_Inhibit_Request",         "bus": "obd"},
            {"signal": "Platform_Engine_Speed_Command_Superceded",              "bus": "obd"},
            {"signal": "Power_Take_Off_Powertrain_Run_Aborted",                 "bus": "obd"},
            {"signal": "Powertrain_Brake_Pedal_Discrete_Input_Status",          "bus": "obd"},
            {"signal": "Powertrain_Brake_Pedal_Discrete_Input_Status_Validity", "bus": "obd"},
            {"signal": "Powertrain_Crank_Aborted",                              "bus": "obd"},
            {"signal": "Powertrain_Crank_Active",                               "bus": "obd"},
            {"signal": "Powertrain_Run_Aborted",                                "bus": "obd"},
            {"signal": "Remote_Vehicle_Start_Engine_Running",                   "bus": "obd"},
        ],
    },
    "coda": {
        "dbcs": [
            PROJECT_ROOT / "projects/coda/CODA-B-CAN.dbc",
            PROJECT_ROOT / "projects/coda/CODA-D-CAN.dbc",
            PROJECT_ROOT / "projects/coda/CODA-C-CAN-cells.dbc",
        ],
        # AUDITED 2026-09-29 -- every id here is measured exclusive to one bus
        # (projects/coda/notes/artifacts/anchor_exclusivity_audit.py, 45 multi-channel
        # captures). An anchor that appears on both buses identifies nothing.
        #
        # b_can WAS {0x1D5, 0x48A, 0x275, 0x381, 0x383} and THREE of those -- 0x1D5,
        # 0x275, 0x383 -- are GWM gateway rebroadcasts carried on D CAN as well, at an
        # exact 50.00 % frame split (the same pass-through this profile's `exclude` list
        # already strips on d_can, which is the contradiction that exposed it). A D CAN
        # channel therefore scored 3/5 = 0.60 for b_can on rebroadcast traffic alone, and
        # was labelled correctly only while it ALSO beat 0.60 on the d_can set, i.e. while
        # 4 of its 5 exclusive ids were present. Below that the rebroadcast score wins and
        # either D CAN traffic is tagged b_can, or both channels claim b_can and step 2's
        # churn filter drops the loser -- a whole bus missing, silently.
        #
        # No stored data was affected: across 51 multi-channel captures, 0 channels were
        # labelled b_can without 0x48A or 0x381 also present
        # (notes/artifacts/bus_label_evidence_audit.py). The set was right by margin, not
        # by evidence, which is what this change fixes.
        #
        # EXPANDED 2026-10-04 from 2 b_can and 5 d_can ids to 18 and 9.
        #
        # Every audit before this one tested exactly the ids
        # projects/coda/README.md already published, so by construction it could
        # only REMOVE anchors; the 2026-09-29 sweep withdrew four and added none,
        # and the README records the gap in its "NOT YET AUDITED" section. With
        # two b_can anchors, a capture too short for either to appear cannot be
        # identified even while carrying ids that occur nowhere else, and its
        # frames upload under `ch<N>`. That is the whole mechanism behind the 147
        # unidentified-channel series found on 2026-10-04, and behind
        # min_anchor_hits["b_can"] having to sit at its weakest possible value.
        #
        # notes/artifacts/anchor_discovery_audit.py is the missing direction. It
        # breaks the circularity -- bus labels come from anchors, and anchors are
        # what is being measured -- by scoring candidates only against channels
        # identified at FULL anchor strength, every published anchor of that bus
        # present. Those labels rest on the audited-exclusive sets at maximum
        # evidence, so no candidate can influence the label it is scored against.
        #
        # Admitted here: exclusive on the frame split AND coverage >= 0.98, i.e.
        # present in at least 98 % of the sessions where that bus was identified.
        # Both are needed and they are independent -- the charger ids 0x274-0x27D
        # and 0x615-0x61C are perfectly exclusive at coverage 0.040 because they
        # only occur while charging, and an anchor nobody emits identifies
        # nothing. Measured over 392 sessions, 369 with a full-strength channel
        # (c_can 100, d_can 288, b_can 353):
        #
        #   b_can  cov 1.000 (353/353): 0x07D 0x1D7 0x270 0x271 0x2C2 0x378 0x381
        #                               0x390 0x392 0x439 0x48A 0x492
        #          cov 0.997: 0x2C1 0x382 0x391 0x410   cov 0.994: 0x620
        #          cov 0.980: 0x3A0        all at 0.0000 minority share
        #   d_can  cov 1.000: 0x278 0x308 0x312 0x315 0x325 0x330 0x55C 0x580
        #          cov 0.997: 0x08C
        #
        # This also settles both leads the README left open: all eight of
        # `CodaConstants.B_CAN_EXCLUSIVE_IDS` audit clean, and 0x492 -- recorded
        # there as never tested either way -- is clean at coverage 1.000.
        #
        # c_can is deliberately NOT expanded. 97 ids clear the same bar, but the
        # 26-id cell range is already perfectly bimodal ({1: 1, 26: 280}) and
        # identification never fails on it; adding 71 more would only rescale
        # min_anchor_hits for no gain.
        "bus_anchors": [
            ("c_can", set(range(0x000, 0x01A))),
            ("d_can", {0x08C, 0x278, 0x308, 0x312, 0x315,
                       0x325, 0x330, 0x55C, 0x580}),
            ("b_can", {0x07D, 0x1D7, 0x270, 0x271, 0x2C1, 0x2C2, 0x378, 0x381,
                       0x382, 0x390, 0x391, 0x392, 0x3A0, 0x410, 0x439, 0x48A,
                       0x492, 0x620}),
        ],
        # Minimum DISTINCT anchor hits before a label is accepted; below it the
        # channel becomes `ch<N>`. See the long note in identify_buses for the
        # failure this exists to stop: one stray frame deciding a bus, with no
        # way for the ambiguity warning to fire because only one set matched.
        #
        # RE-DERIVED 2026-10-04 after the anchor expansion, because the earlier
        # values were measured against the 2-id b_can and 5-id d_can sets and do
        # not transfer. Re-measured over 2,257 channels in 1,088 coda logs
        # (notes/artifacts/bus_label_min_anchor_audit.py):
        #
        #   b_can (of 18): {1:1, 5:1, 7:5, 9:1, 13:2, 14:3, 15:3, 16:8, 17:42, 18:1010}
        #   d_can (of  9): {1:2, 3:1, 4:15, 5:1, 6:4, 7:2, 8:5, 9:865}
        #   c_can (of 26): {26: 280}
        #
        # THE RULE USED LAST TIME DOES NOT WORK HERE AND SAYING WHY MATTERS.
        # "Set it at the observed minimum for a genuine channel" returns 1 for
        # both b_can and d_can -- no guard at all -- and it only ever worked
        # because every channel in the population was assumed genuine, which is
        # the very thing in question. A number read off this histogram would be
        # a threshold I chose wearing the clothes of a measurement.
        #
        # So the sub-threshold channels were inspected by CONTENT
        # (notes/artifacts/low_hit_channel_inspect.py, 54 channels):
        #
        #   KEEP. coda_20260426_151050_T7 ch2 carries 237,777 frames at d_can
        #   4/9, b_can 0/18, c_can 0/26 -- 0x325 0x330 0x55C 0x580 plus
        #   0x7E0/0x7E8, a real D CAN capture in a diagnostic state where the
        #   fast periodics 0x308/0x312 are not running. Four more like it at
        #   ~237k frames. Any d_can threshold above 4 demotes 15 real channels.
        #
        #   REJECT. coda_20260507_104222_T0 ch1 is 10 frames on ONE b_can anchor
        #   with nothing else matching; coda_20260429_193542_T0 ch2 is 2 frames
        #   on one d_can anchor. These are the case the guard is for.
        #
        # The distributions have a clean gap either side of the chosen value --
        # b_can has nothing at 2, 3 or 4, d_can nothing at 2 -- so 2 is not a
        # cut through a population, it sits in empty space. It demotes exactly
        # three channels corpus-wide: the two named above and one more.
        #
        # c_can stays at 10. Its distribution is now a single spike at 26 (the
        # {1: 1} outlier was coda_20260608_095955_T6, which the expanded b_can
        # set now identifies correctly), but requiring all 26 would demote any
        # short chunk carrying a partial cell sweep, and 10 is already far below
        # anything observed.
        "min_anchor_hits": {"c_can": 10, "d_can": 2, "b_can": 2},
        # GWM gateway rebroadcast exclusions (see notes/driver-inputs.md Gateway Rebroadcast):
        # D CAN native IDs that are passed through to B CAN -- upload from D CAN only.
        # B CAN native IDs that are passed through to D CAN -- upload from B CAN only.
        "exclude": [
            # --- B CAN: gateway copies of D CAN native messages (source = D CAN) ---
            {"can_id": 0x080,  "bus": "b_can"},  # EPS steering angle (EPS/PSM is D CAN module)
            {"can_id": 0x1C0,  "bus": "b_can"},  # MCM core telemetry (D CAN native)
            {"can_id": 0x200,  "bus": "b_can"},  # Heartbeat/counter (D CAN native)
            {"can_id": 0x208,  "bus": "b_can"},  # ESC brake pressure + wheel speeds (D CAN native)
            {"can_id": 0x210,  "bus": "b_can"},  # Throttle pedal position (D CAN native)
            {"can_id": 0x212,  "bus": "b_can"},  # EPS sub-frames + brake switch (D CAN native)
            {"can_id": 0x215,  "bus": "b_can"},  # TCM signal (D CAN native)
            {"can_id": 0x240,  "bus": "b_can"},  # System state (D CAN native)
            {"can_id": 0x241,  "bus": "b_can"},  # Motor thermal data (D CAN native)
            # 0x248 and 0x370 were excluded on b_can until 2026-09-26 on the belief
            # that they were D CAN native. They are not, and this is the same error
            # as the 0x276 one below. In codadriveslowturnonwithdefroster2.log and
            # DCDCRUNNingwithoutkeyon-then-key-on.log both are on B CAN from +0.01 s
            # with D CAN asleep, and reach D CAN only when it wakes (+9.46 s / +41.88 s);
            # frame counts are 2836 on B against 742 on D. Excluding b_can kept the
            # gateway copy and dropped the original, blanking both for every B-only
            # capture. 0x370 additionally is NOT a faithful copy -- B1 differs in
            # 100% of 34,919 matched pairs (a bus tag), so the D copy cannot stand in.
            # 0x370 is the GWM "Vehicle Faults" message (factory DTC list U0146) and
            # carries the vehicle power-state field. Exclusions moved to d_can.
            {"can_id": 0x278,  "bus": "b_can"},  # Drive keepalive / HV ready (D CAN native)
            {"can_id": 0x315,  "bus": "b_can"},  # DLCM status: brake switch, Batt_Volt (D CAN native)
            {"can_id": 0x418,  "bus": "b_can"},  # PRND gear selector (D CAN native)
            {"can_id": 0x600,  "bus": "b_can"},  # TPMS pressure (D CAN native)
            # --- D CAN: gateway copies of B CAN native messages (source = B CAN) ---
            {"can_id": 0x275,  "bus": "d_can"},  # BMS discharge/charge limits (B CAN native)
            {"can_id": 0x383,  "bus": "d_can"},  # State of Charge (B CAN native)
            {"can_id": 0x1D5,  "bus": "d_can"},  # DCDC Status1 (B CAN native)
            {"can_id": 0x491,  "bus": "d_can"},  # IPK status (IPK is B CAN module)
            # 0x276 was excluded on b_can until 2026-08-23 on the belief that HVAC status
            # was D CAN native. It is not: in codapumprunningwhencaroffthenturningoncar.log
            # and DCDCRUNNingwithoutkeyon-then-key-on.log the AICM transmits 0x276 on B CAN
            # from +0.07 s with D CAN asleep, and it reaches D CAN only when D CAN wakes
            # (+23.1 s / +41.9 s), 65-94 ms ahead of D CAN's own 0x308/0x312. Excluding it
            # on b_can discarded the original to keep the copy, and blanked PTC heater
            # energy for every B-only capture -- all charge sessions and 100% of March
            # miles. See notes/efficiency-calculation.md Sec.5.
            {"can_id": 0x276,  "bus": "d_can"},  # HVAC status (AICM is a B CAN module)
            {"can_id": 0x6FA,  "bus": "d_can"},  # GWM VIN broadcast (GWM is the gateway; primary on B CAN, rebroadcast to D CAN)
            {"can_id": 0x248,  "bus": "d_can"},  # Mode flags / exterior lights (B CAN native -- see note above)
            {"can_id": 0x370,  "bus": "d_can"},  # GWM Vehicle Faults / power state (B CAN native -- see note above)
            # --- The same bus-blind index in the MIRROR direction: C CAN cell
            # ids decoded on B/D CAN. Added 2026-10-04 alongside the c_can block
            # below, after dropping the 45 series they had already produced.
            #
            # These are stray frames, not a rare message, and the two
            # measurements that say so are independent. Per session they arrive
            # as 1, 4, 10 and 34 frames with median gap 0.000 s -- one burst, not
            # a period -- and in total they held 253 field-values against
            # 1,420,682 and 1,388,657 for the same ids on their native c_can,
            # four ten-thousandths of a percent. anchor_discovery_audit.py
            # reached the same verdict from the other side: 0x000, 0x004 and
            # 0x00C are exclusive to c_can at coverage 1.000 with 5, 7 and 8
            # stray frames across the whole 392-session corpus.
            #
            # A rare-but-real message is still PERIODIC when it appears. These
            # are not, which is what separates them from the genuinely rare
            # charger ids (0x274-0x27D, 0x615-0x61C) that the same audit found
            # exclusive to b_can at coverage 0.040 -- real messages that only
            # occur while charging.
            #
            # The README warns that a split ratio is meaningless at tiny counts,
            # and these are exactly that case: 0x00C measured a 50.00 % "split"
            # of two frames against two.
            {"can_id": 0x004,  "bus": "b_can"},
            {"can_id": 0x00C,  "bus": "b_can"},
            {"can_id": 0x00C,  "bus": "d_can"},
            # --- c_can: ids the C CAN DBC does not define, decoded with the
            # WRONG DBC because build_id_index() keys on frame id alone and has
            # no bus dimension, so every DBC is tried against every bus.
            #
            # Found 2026-10-04 while verifying an unrelated upload: a query
            # scoped to can_id='0x300' but not to bus returned 2329 "armed"
            # ESC-intervention points in a session with one real episode.
            #
            # Two evidence classes, both from
            # notes/artifacts/ccan_crossbus_decode_audit.py (+ _phase2.py):
            #
            # 1. MEASURED DISTINCT. c_can has its own message at this id.
            #    Payload-set overlap against the native bus is 0.000 in BOTH
            #    directions, scored only in sessions carrying the id on both
            #    buses at once so the score cannot be vacuously zero:
            #      0x200  92 sessions (d_can), 90 (b_can)  fwd 0.000 rev 0.000
            #      0x300  92 sessions (d_can)              fwd 0.000 rev 0.000
            #    A c_can 0x200 payload looks like 15 15 15 16 15 16 16 16,
            #    eight similar small values, against the structured D CAN
            #    0x200 heartbeat it was being decoded as. What the c_can
            #    message actually carries is NOT established here -- only
            #    that it is not the D CAN one.
            {"can_id": 0x200,  "bus": "c_can"},
            {"can_id": 0x300,  "bus": "c_can"},
            # 2. NEVER OBSERVED ON c_can AT ALL across 392 sessions. Their
            #    c_can rows in InfluxDB come from ONE mislabelled channel --
            #    coda_20260608_095955_T6, see identify_buses -- not from c_can
            #    traffic. The `min_anchor_hits` guard above stops that label
            #    being produced again; these entries additionally drop the
            #    pairs out of current_hashes(), which is what lets
            #    `--check-existing` see the stored rows as orphans and delete
            #    them. Not a claim that c_can carries these messages: a claim
            #    that it does not.
            {"can_id": 0x271,  "bus": "c_can"},
            {"can_id": 0x276,  "bus": "c_can"},
            {"can_id": 0x370,  "bus": "c_can"},
            {"can_id": 0x391,  "bus": "c_can"},
            {"can_id": 0x410,  "bus": "c_can"},
            {"can_id": 0x439,  "bus": "c_can"},
            {"can_id": 0x6FA,  "bus": "c_can"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_session(path: Path) -> str:
    """
    Build a session tag from the filename.
    canlog_20260315_123456_M0_T1.log -> 2026-03-15_M0
    Falls back to the stem with _T<n> stripped.
    """
    name = path.stem
    date_m = re.search(r'(\d{4})(\d{2})(\d{2})_\d{6}', name)
    mn_m = re.search(r'_M(\d+)', name)
    if date_m:
        date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
        return f"{date}_M{mn_m.group(1)}" if mn_m else date
    return re.sub(r'_T\d+$', '', name)


def _parse_tz(tz_str: str):
    """
    Parse a timezone string into a tzinfo object.
    Accepts IANA names ('America/Los_Angeles', 'UTC') or numeric offsets ('-7', '+5.5').
    """
    try:
        hours = float(tz_str)
        return timezone(timedelta(hours=hours))
    except ValueError:
        pass
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Unknown timezone: {tz_str!r}. "
                         "Use an IANA name (e.g. 'America/Los_Angeles') "
                         "or a numeric offset (e.g. '-7').")


NS_PER_S = 1_000_000_000


def read_log_start_time_ns(path: Path, tz=timezone.utc) -> int | None:
    """
    Read the start timestamp from a BUSMASTER log header line:
      ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTTT***
    Returns Unix epoch in integer NANOSECONDS (UTC), or None if not found /
    not parseable. TTTT are 10 kHz ticks (0.1 ms), same unit as frame
    timestamps, so each tick is exactly 100_000 ns.

    Integer nanoseconds, not float seconds: a float epoch (~1.7e9) has only
    ~0.24 us of resolution left in a float64 mantissa, so `(epoch + offset) *
    1e9` injected +/-128 ns of rounding noise into every stored timestamp.
    Building the epoch in integer ns and adding an integer offset removes it.
    (That noise turned out NOT to cost disk -- see the internal `influx-sync` plan,
    Lever B -- but exact timestamps are required for the time-bounded DELETE
    that per-file repair depends on.)

    tz: tzinfo for the recording PC's clock. datetime.timestamp() converts to UTC.
    Defaults to UTC (header treated as UTC). Pass ZoneInfo('America/Los_Angeles')
    for DST-aware Pacific time, or timezone(timedelta(hours=-7)) for a fixed offset.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                # BUSMASTER does not zero-pad: real headers include
                # "12:2:2025 16:51:57:846" and "17:1:2026 0:1:30:217". The
                # previous {2}-digit pattern rejected 356 of 3,135 headers in
                # the corpus and fell through to the filename/mtime fallbacks
                # without saying so.
                m = re.search(
                    r'START DATE AND TIME\s+(\d{1,2}):(\d{1,2}):(\d{4})\s+'
                    r'(\d{1,2}):(\d{1,2}):(\d{1,2}):(\d+)',
                    line
                )
                if m:
                    day, mon, yr, h, mn, s, ms = (int(x) for x in m.groups())
                    dt = datetime(yr, mon, day, h, mn, s, tzinfo=tz)
                    # The HEADER's sub-second field is milliseconds, unlike the
                    # data lines' 10 kHz ticks: across 1,062 headers it never
                    # exceeds 998, while data-line values reach 9999. Reading it
                    # as ticks was wrong by 10x.
                    # dt has whole seconds, so dt.timestamp() is an exactly
                    # representable float integer; int() is lossless here.
                    return int(dt.timestamp()) * NS_PER_S + (ms % 1000) * 1_000_000
    except Exception:
        pass
    return None


def derive_start_epoch_ns(path: Path, log_duration: float = 0.0,
                          tz=timezone.utc, timebase: "TimebaseIndex" = None) -> int:
    """
    Return the Unix epoch in integer NANOSECONDS (UTC) that this capture's
    frame timestamps are counted from. Priority:
      1. canre.utils.timebase -- session-aware anchor (see below)
      2. BUSMASTER header: ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTTT***
      3. YYYYMMDD_HHMMSS in filename
      4. file mtime minus log_duration (mtime is when the file was written = end of capture)

    Step 1 exists because two loggers write BUSMASTER files with different time
    bases. The Android logger resets frame timestamps to zero every chunk, so
    `header + frame.timestamp` is right. The laptop captures write wall-clock
    time of day, so the same sum double-counts and displaces points by up to
    ~24 h; 348 files / 14.74 GB of the corpus are that flavour. Which flavour a
    file is cannot always be told from the file alone -- `debuglog_M1_T8`'s
    header disagrees with its own data -- so `TimebaseIndex` decides per
    session. Pass a shared index to reuse its per-directory cache.

    Only the mtime fallback is inexact, and it is already an approximation.

    tz: tzinfo for the recording PC's clock (applied to header and filename timestamps).
    """
    if timebase is not None:
        t = timebase.anchor_ns(path, tz)
        if t is not None:
            return t

    t = read_log_start_time_ns(path, tz)
    if t is not None:
        return t

    m = re.search(r'(\d{8})_(\d{6})', path.stem)
    if m:
        try:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return int(dt.replace(tzinfo=tz).timestamp()) * NS_PER_S
        except ValueError:
            pass

    return round((path.stat().st_mtime - log_duration) * NS_PER_S)


def scan_log(path: Path) -> tuple[dict, dict, float]:
    """
    Single streaming pass over the log to collect:
      - channel_ids:    {bus_int: set of arbitration_ids}     -- for anchor matching
      - channel_counts: {bus_int: total frame count}          -- for churn filtering
      - last_timestamp: float (seconds), only used as a mtime fallback for
                        derive_start_epoch_ns when the BUSMASTER header and the
                        filename-date both fail to parse.

    Per-channel frame counts let identify_buses filter out the Android-logger
    startup churn described in projects/vtrux/README.md ("Bus number churn in
    Android T0"): T0 captures can carry 20+ transient channel numbers, each
    with only a handful of frames, before settling on a stable bus number.

    For BUSMASTER logs (the primary format), this dispatches to
    `BusmasterParser.scan_ids` -- a stripped-down line scanner that skips
    timestamp conversion, data-byte hex decoding, and CANFrame allocation,
    roughly halving the scan-pass cost. (Benchmark: scan_log was ~23% of a
    535 MB upload's profiled runtime; the fast path nets ~50-70s real-world
    on that workload.)

    For other log formats (candump, PEAK TRC, SavvyCAN, Vector ASC) we fall
    back to a full parse via `parse_file`. Those formats are rare in this
    project; the extra cost is acceptable to keep the fast path
    BUSMASTER-only and avoid duplicating parsing logic in five places.
    """
    parser = detect_format(path)
    if isinstance(parser, BusmasterParser):
        return BusmasterParser.scan_ids(path)

    channel_ids: dict[int, set] = defaultdict(set)
    channel_counts: dict[int, int] = defaultdict(int)
    last_ts = 0.0
    for frame in parser.parse_file(path):
        channel_ids[frame.bus].add(frame.arbitration_id)
        channel_counts[frame.bus] += 1
        last_ts = frame.timestamp
    return dict(channel_ids), dict(channel_counts), last_ts


def identify_buses(
    channel_ids: dict,
    channel_counts: dict,
    bus_anchors: list,
    min_anchor_hits: dict | None = None,
) -> dict:
    """
    Map channel integers to named bus strings using anchor ID sets, with
    Android-logger churn filtering (see projects/vtrux/README.md "Bus number
    churn in Android T0").

    A channel that matches no anchor set is mapped to None and is NOT
    uploaded. See step 3 for why, and for what that replaced.

    `min_frames` and `min_fraction` were removed 2026-10-04 along with the
    `ch<N>` fallback they gated -- they existed only to decide which
    unidentifiable channels were big enough to upload anyway, and nothing now
    uploads an unidentifiable channel at any size. No caller ever passed
    either one. The churn filter in step 2 is unaffected: it compares channels
    claiming the SAME bus name and never used these.

    Channels passing the count test but lacking any anchor match get the
    fallback name 'ch<N>' (uploaded with channel number as the bus tag). A
    channel whose only anchor match falls below `min_anchor_hits` for that bus
    counts as no match, for the reason set out at step 1.

    Returns {channel_int: bus_name_str_or_None}.
    """
    if not channel_counts:
        return {}

    # Step 1: score every channel against every anchor set and take the best
    # match by FRACTION of that anchor set present, not by first-listed hit.
    #
    # First-match-wins mislabels whenever anchor sets overlap. Coda
    # chargepointcharge.log: the real b_can channel carries 4 of 5 b_can
    # anchors, but it also carries ID 0x000, which falls inside c_can's
    # 0x000-0x019 cell-voltage range -- so c_can was listed first and won,
    # labelling b_can traffic as c_can. Fraction fixes it: 4/5 = 0.80 for
    # b_can beats 1/26 = 0.04 for c_can. Fraction rather than raw count
    # because the anchor sets differ hugely in size (1 id for powertrain,
    # 26 for c_can). Ties fall back to the declared order.
    #
    # Every anchor set is meant to hold ids exclusive to its own bus, so a channel
    # should match EXACTLY ONE set. Matching two is a contradiction -- a stray frame,
    # or an anchor that is not exclusive after all -- and resolving it by fraction
    # silently produces a bus label with no evidence behind it. Measured 2026-09-29:
    # all 126 channels across 55 multi-channel Coda captures match exactly one set.
    # So the ambiguous case is reported rather than passed off as a result. It still
    # resolves, because refusing would fail an upload over one frame, but it says so.
    # A label must also clear a MINIMUM NUMBER OF DISTINCT ANCHOR HITS for the
    # set it claims. Without it, one stray frame decides a bus and nothing can
    # report the failure: the ambiguity warning below only fires when TWO sets
    # match, so a channel matching exactly one set on exactly one id is
    # indistinguishable from a channel matching it on all of them.
    #
    # That is the null-discriminator failure in AGENTS.md -- a selection among
    # one candidate is not evidence -- and it had happened:
    # coda_20260608_095955_T6, a 33 KB tail chunk with ONE channel carrying 621
    # frames of B CAN traffic, holds no b_can anchor (too short for 0x48A or
    # 0x381 to appear) and one id inside c_can's 0x000-0x019 cell range. c_can
    # was the only set with a hit, so 621 B CAN frames went to InfluxDB tagged
    # c_can, carrying seven ids that only ever appear on B/D CAN.
    #
    # Thresholds are the OBSERVED MINIMUM for genuine channels, measured over
    # every channel of every coda log -- 2262 channels in 1095 files, no
    # pre-filtering (notes/artifacts/bus_label_min_anchor_audit.py):
    #     b_can (of  2): {1: 36, 2: 1032}        -> must stay 1
    #     d_can (of  5): {1: 1, 2: 1, 3: 19, 4: 7, 5: 866}
    #     c_can (of 26): {1: 1, 26: 280}         -> perfectly bimodal
    # Only 3 channels in the whole corpus sit below these, all `_T6` tail
    # chunks, and they become `ch<N>` -- still uploaded, just not under a bus
    # name they have not earned.
    #
    # This REPLACES the population behind the note in the coda profile saying a
    # minimum must not be added. That measurement
    # (notes/artifacts/anchor_hit_distribution.py) skipped single-channel
    # captures outright (`if len(ids) < 2: continue`) and classified a channel
    # as a c_can candidate only at `nc >= 10`, so neither the failing case nor a
    # low-hit c_can channel could appear in it. Its b_can conclusion survives
    # and is why b_can is still 1.
    min_hits = dict(min_anchor_hits or {})

    best: dict = {}
    for channel, ids in channel_ids.items():
        scored = []
        for order, (bus_name, anchors) in enumerate(bus_anchors):
            hits = len(ids & anchors)
            if hits and hits >= min_hits.get(bus_name, 1):
                scored.append((hits / len(anchors), hits, -order, bus_name))
        if len(scored) > 1:
            detail = ", ".join(f"{name}:{h}/{int(h / f) if f else 0}"
                               for f, h, _o, name in sorted(scored, reverse=True))
            print(f"  !! channel {channel} matches {len(scored)} anchor sets ({detail}) "
                  f"-- anchors are supposed to be exclusive, so this label is not "
                  f"evidenced; taking the strongest", flush=True)
        best[channel] = max(scored)[3] if scored else None

    # Step 2: churn filter, applied ONLY between channels competing for the
    # same bus. Android T0 captures re-number one physical bus across many
    # transient channels (vtrux_20260503_171127_T0: a real PT bus at 155k
    # frames plus 4 more channels that also match powertrain at 2-7k, and a
    # real OBD bus at 86k plus 5 more matching obd) -- all duplicates of the
    # same traffic, so the highest-count claimant wins and the rest are
    # dropped.
    #
    # A blanket "under 5% of the busiest channel" rule cannot express that.
    # It also discarded genuinely separate buses: in that same Coda log the
    # real c_can channel is only 3.5% of b_can's frame count (cell voltages
    # are bursty, b_can is continuous) and was being thrown away entirely.
    # Competing for the same NAME is the signal; relative volume alone is not.
    claimants: dict = defaultdict(list)
    for channel, bus_name in best.items():
        if bus_name is not None:
            claimants[bus_name].append(channel)

    mapping: dict = {}
    for bus_name, channels in claimants.items():
        winner = max(channels, key=lambda c: channel_counts.get(c, 0))
        for c in channels:
            mapping[c] = bus_name if c == winner else None

    # Step 3: A CHANNEL THAT MATCHES NO ANCHOR SET IS NOT UPLOADED.
    #
    # Until 2026-10-04 such a channel was uploaded under the fallback tag
    # `ch<N>` if it cleared an absolute and relative frame-count floor. That
    # was wrong in a way the floor could not fix, because the problem was
    # never the channel's size:
    #
    #   * `ch<N>` is not a bus name, it is an admission that the bus is
    #     UNKNOWN. N is dongle insertion order, which varies per capture, so
    #     the tag does not even identify the same thing across two files
    #     (AGENTS.md: never identify a bus by channel number).
    #   * The profile `exclude` lists are keyed `(bus_name, can_id)`, so a
    #     bus-scoped exclusion CANNOT MATCH `ch<N>`. An unidentified channel
    #     therefore uploaded gateway-rebroadcast copies that the identical
    #     frames would have had excluded under a named bus. Measured: the
    #     coda_20260807_192700 tail wrote nothing while labelled `d_can`
    #     because all five of its ids are d_can-excluded, and five series once
    #     it became `ch1`.
    #   * `build_id_index()` keys on frame id alone, so those frames were
    #     decoded against whichever DBC happened to define the id, with no bus
    #     to constrain the choice -- the same bus-blindness that put c_can
    #     0x200/0x300 under D-CAN signal names.
    #
    # So the data was not merely unlabelled, it was actively misleading, and
    # every consumer had to special-case it: influx_sync's L0 had to normalise
    # the missing definition hash or every such file drifted forever, and its
    # L1 condemned all 147 `ch<N>` series as orphans because no `ch<N>` pair
    # can be in current_hashes().
    #
    # The right response to "which bus is this?" having no answer is to fix
    # the anchors, not to invent a label. Coda b_can went from 2 anchors to 18
    # on the same day (notes/artifacts/anchor_discovery_audit.py) and its
    # unattributable population went to almost nothing.
    #
    # Cost of this change, measured before making it
    # (tools/artifacts/unidentified_channel_census.py): 9 channels across both
    # vehicles, 2 on Coda (305 frames) and 7 on Vtrux (332,082 frames). The
    # Vtrux captures were quarantined to logs/unidentified-bus/ rather than
    # silently dropped, because every one is a disconnect experiment whose
    # bus is unidentifiable precisely BECAUSE the test disconnected the module
    # emitting the sole `powertrain` anchor.
    #
    # NOTE this is invisible to all three sync staleness keys -- file sha1,
    # DBC message hashes, policy hash -- because it changes interpretation,
    # not bytes or encoding. It needs no re-upload (it can only ever REMOVE
    # series, so dropping the existing `ch<N>` series reaches the same end
    # state), but the drop is the migration, not optional tidying.
    for channel in channel_ids:
        mapping.setdefault(channel, None)
    return mapping


def estimate_avg_bytes_per_line(path: Path, sample_bytes: int = 100_000) -> float:
    """
    Estimate average bytes per line by reading the first *sample_bytes* of
    the file and counting newlines. Used to drive a rough byte-based
    progress display without a frame-counting pre-pass: progress estimate
    is `frames_seen * avg_bytes_per_line / file_size`.

    The estimate ignores headers (which are negligible vs millions of data
    lines) and is parser-agnostic -- every CAN log format we support has
    one frame per line. Returns 0.0 if the file is empty or unreadable, in
    which case the caller should suppress the progress display.
    """
    try:
        with open(path, "rb") as fh:
            sample = fh.read(sample_bytes)
    except OSError:
        return 0.0
    newlines = sample.count(b"\n")
    if newlines == 0:
        return 0.0
    return len(sample) / newlines


class _Unset:
    """Sentinel for 'this signal has never been emitted'.

    A plain object() would work, but a named class makes the on-change state
    readable in a traceback. Must never compare equal to a decoded value --
    decoded values are ints/floats/strings, so the default identity __eq__ is
    correct here.
    """
    __slots__ = ()


_UNSET = _Unset()

MANIFEST_MEASUREMENT = "upload_manifest"
# Bump when the stored encoding changes in a way that invalidates every existing
# manifest row (timestamp derivation, line-protocol layout, tag set). A bumped
# value forces a full re-upload rather than a per-message repair.
ENCODING_VER = "2026-08-10.1"

_TAG_ESCAPE_RE = re.compile(r'([,= ])')
_FIELD_STR_ESCAPE_RE = re.compile(r'(["\\])')


def escape_field_str(value: str) -> str:
    """Escape a line-protocol string FIELD value: backslash and double quote."""
    return _FIELD_STR_ESCAPE_RE.sub(r'\\\1', value)


def sha1_file(path: Path, chunk: int = 1 << 20) -> str:
    """SHA-1 of a log file, streamed."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def policy_hash(profile_exclude, cli_exclude, on_change, heartbeat_s,
                upload_raw, only_ids, min_anchor_hits=None) -> str:
    """Hash of every upload-policy input that changes what gets written.

    Separate from the per-message definition hash: a change here (a new
    exclusion, a different write policy) invalidates whole files rather than
    single messages.
    """
    payload = {
        "profile_exclude": profile_exclude,
        "cli_exclude": sorted(cli_exclude or []),
        "on_change": bool(on_change),
        "heartbeat_s": float(heartbeat_s),
        "raw": bool(upload_raw),
        "only_ids": sorted(only_ids) if only_ids else None,
    }
    # Bus labelling decides the `bus` tag on every point, so a change to the
    # minimum-anchor-hits guard changes what is stored just as surely as an
    # exclusion does -- without this, files uploaded under the old labelling
    # stay invisible to `--plan`.
    #
    # The key is OMITTED when unset rather than written as null, so a profile
    # that does not use the guard keeps the hash it already has. Adding
    # `"min_anchor_hits": null` to the blob moved vtrux's hash from
    # 0a5448cad23b to 651b7c52ab9b and would have queued a re-upload of the
    # entire Vtrux corpus for a Coda-only change.
    if min_anchor_hits:
        payload["min_anchor_hits"] = dict(sorted(min_anchor_hits.items()))
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def build_manifest_line(*, vehicle, session, path, rel_path, stats, bus_map,
                        msg_hash_map, policy_h, log_sha1, uploaded_at_ns,
                        merged=None) -> str:
    """One line-protocol point recording what an upload actually wrote.

    Tagged (vehicle, session, file) so a session's chunks stay individually
    addressable -- session alone is too coarse, since 144 chunks can share one
    session tag.

    `t_start_ns`/`t_end_ns` are the bounds the uploader OBSERVED, not bounds
    re-derived from the file. Repair deletes by these, and re-deriving them
    later reintroduces the tz-drift failure the slice test hit.
    """
    st = path.stat()
    keys = sorted(stats["keys"])
    hashes = {f"{bus}|{cid}": msg_hash_map.get((bus, cid), "") for bus, cid in keys}
    points, values = stats["points"], stats["values"]
    t_start, t_end = stats["t_start_ns"], stats["t_end_ns"]
    if merged is not None:
        hashes, policy_h, bus_map, points, values, t_start, t_end = merged
    fields = [
        f'rel_path="{escape_field_str(rel_path)}"',
        f'log_sha1="{log_sha1}"',
        f'log_bytes={st.st_size}i',
        f'mtime={int(st.st_mtime)}i',
        f'encoding_ver="{ENCODING_VER}"',
        f'policy_hash="{policy_h}"',
        f'msg_hashes="{escape_field_str(json.dumps(hashes, sort_keys=True))}"',
        f'bus_map="{escape_field_str(json.dumps({str(k): v for k, v in bus_map.items()}, sort_keys=True))}"',
        f'points={points}i',
        f'values={values}i',
        f't_start_ns={t_start}i',
        f't_end_ns={t_end}i',
        f'uploaded_at={uploaded_at_ns}i',
    ]
    prefix = (f"{MANIFEST_MEASUREMENT},file={escape_tag(path.name)},"
              f"session={escape_tag(session)},vehicle={escape_tag(vehicle)} ")
    return prefix + ",".join(fields) + f" {uploaded_at_ns}\n"



def fetch_manifest_row(statement_fn, vehicle, session, filename):
    """Latest `upload_manifest` row for one file, or None.

    Used only by the --only-id path, to merge rather than replace. Reads the
    newest row by time: the tag set is (vehicle, session, file) and each upload
    writes a fresh point at its own `uploaded_at`, so a file accumulates rows
    and the last one is the current truth.
    """
    def q_esc(v):
        return str(v).replace("\\", "\\\\").replace("'", "\\'")

    try:
        body = statement_fn(
            f"SELECT * FROM {MANIFEST_MEASUREMENT} "
            f"WHERE \"vehicle\"='{q_esc(vehicle)}' "
            f"AND \"session\"='{q_esc(session)}' "
            f"AND \"file\"='{q_esc(filename)}' "
            f"ORDER BY time DESC LIMIT 1"
        )
    except Exception:
        return None
    for result in body.get("results", []):
        for series in result.get("series", []) or []:
            cols = series.get("columns", [])
            for vals in series.get("values", []) or []:
                return dict(zip(cols, vals))
    return None



# Chunk a delete no wider than this. A session is normally minutes long so one
# chunk is the usual case; a multi-hour laptop capture is split rather than
# handed to the server as one span.
_DELETE_CHUNK_NS = 24 * 3600 * NS_PER_S
# A bounded DELETE still has to rewrite the shards it touches, so it gets longer
# than an ordinary statement -- but a bound, unlike DROP SERIES.
_DELETE_TIMEOUT_S = 300


def _q_esc(v):
    """Escape a tag value for an InfluxQL string literal.

    A single quote inside a session name would otherwise close the literal and
    let the remainder run as InfluxQL.
    """
    return str(v).replace("\\", "\\\\").replace("'", "\\'")


def stored_window_ns(statement_fn, vehicle, session):
    """(t0_ns, t1_ns, manifest_points) for this session, or None if unrecorded.

    Taken from `upload_manifest`, which records the bounds the uploader observed
    per file. The manifest is append-only, so the newest row per file is the one
    describing what is stored now. It is a tiny, tag-filtered measurement, so
    this is cheap -- unlike asking the `signals` measurement for its own extent.
    """
    try:
        body = statement_fn(
            f"SELECT uploaded_at, file, t_start_ns, t_end_ns, points "
            f"FROM {MANIFEST_MEASUREMENT} "
            f"WHERE \"vehicle\"='{_q_esc(vehicle)}' "
            f"AND \"session\"='{_q_esc(session)}'"
        )
    except Exception as exc:
        raise RuntimeError(f"cannot read manifest window for {session}: {exc}")

    newest = {}
    for result in body.get("results", []):
        for series in result.get("series", []) or []:
            cols = series.get("columns", [])
            for vals in series.get("values", []) or []:
                row = dict(zip(cols, vals))
                f = row.get("file")
                ua = row.get("uploaded_at") or 0
                if f not in newest or ua > newest[f][0]:
                    newest[f] = (ua, row)

    starts = [r["t_start_ns"] for _ua, r in newest.values()
              if r.get("t_start_ns") is not None]
    ends = [r["t_end_ns"] for _ua, r in newest.values()
            if r.get("t_end_ns") is not None]
    if not starts or not ends:
        return None
    pts = sum(r.get("points") or 0 for _ua, r in newest.values())
    return min(starts), max(ends), pts


def has_points(statement_fn, measurement, vehicle, session, t0, t1):
    """True if ANY point is stored for this session inside [t0, t1].

    Deliberately NOT `COUNT(*)`. COUNT(*) expands across every field of the
    measurement, and an unbounded version of exactly that query is what drove
    the host into swap thrash on 2026-09-28 -- memory pressure appeared 1 min
    48 s into a loop of 54 of them, before any DELETE had been issued. A
    bounded COUNT(*) is far cheaper, but zero-or-not is all this needs, and
    `LIMIT 1` stops at the first row instead of aggregating every field.

    The exact stored count, when one is wanted for the log, comes from the
    manifest rather than from the data.
    """
    body = statement_fn(
        f"SELECT * FROM {measurement} "
        f"WHERE \"vehicle\"='{_q_esc(vehicle)}' "
        f"AND \"session\"='{_q_esc(session)}' "
        f"AND time >= {int(t0)} AND time <= {int(t1)} LIMIT 1"
    )
    for result in body.get("results", []):
        for series in result.get("series", []) or []:
            if series.get("values"):
                return True
    return False


def clear_session_window(statement_fn, vehicle, session, *, with_raw=False):
    """Remove this session's stored points with a TIME-BOUNDED DELETE.

    **This replaced an unbounded `DROP SERIES` on 2026-09-28.** Not because that
    statement caused the outage that day -- the host journal shows memory
    pressure began 1 min 48 s into a loop of 54 unbounded `SELECT COUNT(*)`
    queries, before any DELETE was issued, and 40 minutes of swap thrash
    followed with no OOM kill, so the box had to be power-cycled. `DROP SERIES`
    was the next unbounded statement to land on an already-starved server, and
    it is unbounded in the same way: InfluxDB 1.x walks every shard and rewrites
    the index, and it kept working long after the client's 120 s timeout gave
    up. The instance has no query-timeout, no max-concurrent-queries and no
    memory limit, so nothing server-side stops a heavy statement. Raising the
    client timeout would only have hidden a multi-minute operation.

    The lesson is about unbounded statements generally, reads included, not
    about deletes specifically -- see `has_points` for the read half.

    A time-bounded DELETE touches only the shards in the window, and the window
    comes from the manifest, which knows exactly where this session's points
    are. The series keys survive, which is harmless: the caller rewrites the same
    series immediately. The same bounded-delete-then-verify shape is what
    `influx_sync.reupload_ids` has always used for per-message repairs.

    Verified rather than assumed, because a delete that silently matches nothing
    turns the caller's re-upload into an append:

      * no manifest window  -> RAISE. It is tempting to read this as "nothing
                               was ever stored, so nothing to delete", and that
                               is wrong: anything uploaded before the manifest
                               existed has no row, so skipping would append the
                               new timestamps ALONGSIDE the old points instead
                               of replacing them. Without a window there is no
                               safe bounded delete, so the caller must decide.
      * zero points in it   -> skip; there is genuinely nothing to remove. This
                               is also the path a session takes when a previous
                               run already dropped it.
      * points left after   -> RAISE, so the caller does not upload on top of
                               stale data and duplicate it
    """
    win = stored_window_ns(statement_fn, vehicle, session)
    if win is None:
        raise RuntimeError(
            f"no manifest window for {vehicle}/{session}: cannot bound a delete, "
            f"and skipping it would append new points beside any old ones. "
            f"Upload without --delete only if you know the session is absent."
        )
    t0, t1 = win[0] - NS_PER_S, win[1] + NS_PER_S   # 1 s margin each side
    man_pts = win[2]

    for meas in ("signals",) + (("raw",) if with_raw else ()):
        if not has_points(statement_fn, meas, vehicle, session, t0, t1):
            print(f"  {session} [{meas}]: no points in window, nothing to delete",
                  flush=True)
            continue
        span_h = (t1 - t0) / NS_PER_S / 3600
        n_chunks = max(1, -(-(t1 - t0) // _DELETE_CHUNK_NS))
        print(f"  {session} [{meas}]: ~{man_pts:,} point(s) per the manifest, "
              f"{span_h:.2f} h in {n_chunks} chunk(s)", flush=True)
        t_del = time.time()
        lo = t0
        while lo <= t1:
            hi = min(lo + _DELETE_CHUNK_NS, t1)
            statement_fn(
                f"DELETE FROM {meas} "
                f"WHERE \"vehicle\"='{_q_esc(vehicle)}' "
                f"AND \"session\"='{_q_esc(session)}' "
                f"AND time >= {int(lo)} AND time <= {int(hi)}",
                timeout=_DELETE_TIMEOUT_S,
            )
            lo = hi + 1
        del_s = time.time() - t_del
        if has_points(statement_fn, meas, vehicle, session, t0, t1):
            raise RuntimeError(
                f"delete left points for {vehicle}/{session} [{meas}] -- "
                f"refusing to upload on top of them"
            )
        # The DELETE duration is the number worth watching as sessions grow:
        # the delete is chunked by TIME (24 h), not by file, so a 29-file session
        # spanning a few hours is still one chunk and may cost little more than a
        # 2-file one. If this climbs with session size, the chunking is the thing
        # to revisit.
        print(f"  {session} [{meas}]: cleared in {del_s:.1f}s", flush=True)


def merge_manifest_fields(prev_row, *, msg_hash_map, stats, policy_h, bus_map,
                          requested_ids=None):
    """Fold a partial (--only-id) upload into the file's existing manifest row.

    A manifest row describes a WHOLE FILE. `--only-id` uploads one message, so
    writing a fresh row would claim the file contains only that message, with a
    policy hash carrying the only_ids restriction. `influx_sync` then reads
    manifest-says-1-message against data-has-20 and schedules a full re-upload
    of a file that is actually current -- so every targeted repair guaranteed a
    later full re-upload and the repair path never converged. (Observed
    2026-08-25 on the Coda 0x1D7 precision fix: 126 repaired sessions all came
    back wanting 6.2 GB of reupload_file.)

    So merge instead: keep the previous row's whole-file facts (bounds, counts,
    bus map, and the hashes of every message we did NOT touch) and overlay the
    hashes we just rewrote. The policy hash must be the *base* one -- with the
    file's non-repaired messages still on disk from the earlier full upload, the
    row now again describes a full upload under the base policy.

    Returns (msg_hashes_dict, policy_hash, bus_map, points, values,
    t_start_ns, t_end_ns), or None if there is no usable previous row -- in
    which case the caller must fall back to writing what it actually uploaded.
    """
    if not prev_row:
        return None
    try:
        merged = json.loads(prev_row.get("msg_hashes") or "{}")
        prev_bus = json.loads(prev_row.get("bus_map") or "{}")
    except (ValueError, TypeError):
        return None
    if not merged:
        return None
    for bus, cid in stats["keys"]:
        merged[f"{bus}|{cid}"] = msg_hash_map.get((bus, cid), "")

    # Record the ids we were ASKED to upload even when the file turned out to
    # contain none of them. influx_sync treats "defined by the DBC but recorded
    # by no upload" as a newly added message and queues a backfill; without
    # this, backfilling an id that simply is not in a given capture would leave
    # the manifest unchanged, so the same backfill would be queued again on
    # every future run and never converge. Only buses that actually define the
    # message are recorded, so a real later encoding change is still detected.
    for cid in sorted(requested_ids or []):
        for bus in set(bus_map.values()):
            h = msg_hash_map.get((bus, cid))
            if h is not None:
                merged.setdefault(f"{bus}|{cid}", h)
    prev_bus.update({str(k): v for k, v in bus_map.items()})
    t0, t1 = prev_row.get("t_start_ns"), prev_row.get("t_end_ns")
    if t0 is None or t1 is None:
        return None
    return (merged, policy_h, prev_bus,
            int(prev_row.get("points") or stats["points"]),
            int(prev_row.get("values") or stats["values"]),
            int(t0), int(t1))


def escape_tag(value: str) -> str:
    """
    Escape a line-protocol tag key/value: comma, equals and space take a
    backslash.

    This used to be skipped on the stated invariant that our tag values can
    never contain those characters. A `--session` override with spaces broke
    that invariant and wrote a session literally named
    `generator\\ on\\ then\\ off` into the database -- the backslashes became
    part of the stored tag value. Escaping here means such a session is stored
    as `generator on then off`, which is what was meant.
    """
    return _TAG_ESCAPE_RE.sub(r'\\\1', value)


_EXTENDED_BIT = 0x80000000
_BO_RE = re.compile(r'^(BO_ )(\d+)( )', re.MULTILINE)


def _fix_extended_ids(text: str) -> str:
    """
    Some DBCs store 29-bit extended IDs without the 0x80000000 marker that
    cantools requires. Detect BO_ IDs > 0x7FF and OR in the marker.
    """
    def _fix(m):
        raw_id = int(m.group(2))
        if raw_id > 0x7FF and not (raw_id & _EXTENDED_BIT):
            raw_id |= _EXTENDED_BIT
        return m.group(1) + str(raw_id) + m.group(3)
    return _BO_RE.sub(_fix, text)


def load_databases(dbc_paths: list[Path]) -> list:
    """
    Load each DBC into a separate cantools Database object.
    Applies extended-ID fix and suppresses cantools chatter.
    Skips files that don't exist or fail to parse (with a warning).
    Returns list of (name_str, db) tuples.
    """
    result = []
    for path in dbc_paths:
        if not path.exists():
            print(f"  Warning: DBC not found, skipping: {path}", file=sys.stderr)
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
            text = _fix_extended_ids(text)
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                db = cantools.database.load_string(text, database_format='dbc', strict=False)
            result.append((path.name, db))
        except Exception as e:
            print(f"  Warning: could not load {path.name}: {e}", file=sys.stderr)
    return result


def build_id_index(databases: list) -> dict:
    """
    Build {frame_id: [db, ...]} so each frame goes straight to the DBCs that
    actually define it. Avoids the per-frame "try every DBC and catch the
    KeyError" pattern, which is dominant on logs with many loaded DBCs.

    Most IDs land in exactly one DBC (single-element list); the few that
    appear in multiple DBCs are merged in decode_frame, preserving the
    previous "later DBC wins on signal-name collision" behaviour.
    """
    index: dict[int, list] = {}
    for _name, db in databases:
        for msg in db.messages:
            index.setdefault(msg.frame_id, []).append(db)
    return index


def decode_frame(frame, id_index: dict) -> dict:
    """
    Decode a frame using the frame_id -> [db,...] index built by build_id_index.
    Returns {} if no DBC defines this ID or all decode attempts fail.
    """
    dbs = id_index.get(frame.arbitration_id)
    if not dbs:
        return {}
    if len(dbs) == 1:
        try:
            return dbs[0].decode_message(
                frame.arbitration_id, frame.data, decode_choices=False,
            )
        except Exception:
            return {}
    signals: dict = {}
    for db in dbs:
        try:
            signals.update(db.decode_message(
                frame.arbitration_id, frame.data, decode_choices=False,
            ))
        except Exception:
            pass
    return signals


# ---------------------------------------------------------------------------
# Streaming decode + write
# ---------------------------------------------------------------------------

def build_exclude_sets(profile_exclude: list, cli_exclude: list) -> tuple[set, set, set, set]:
    """
    Parse exclusion lists into four sets for fast lookup:
      exclude_global:     {signal_name}            -- excluded on all buses
      exclude_bus_signal: {(bus_name, signal_name)} -- excluded on a specific bus
      exclude_id:         {can_id}                 -- entire message excluded on all buses
      exclude_bus_id:     {(bus_name, can_id)}     -- entire message excluded on a specific bus

    Profile entries use dicts:
      {"signal": "Name", "bus": "obd"}   or  {"signal": "Name"}
      {"can_id": 0x0C1,  "bus": "obd"}   or  {"can_id": 0x0C1}

    CLI --exclude entries use strings: "SignalName" or "bus:SignalName"
    (can_id exclusions are profile-only; CLI does not support them)
    """
    exclude_global: set = set()
    exclude_bus_signal: set = set()
    exclude_id: set = set()
    exclude_bus_id: set = set()

    for entry in profile_exclude + cli_exclude:
        if isinstance(entry, dict):
            bus = entry.get("bus")
            if "can_id" in entry:
                can_id = entry["can_id"]
                if bus:
                    exclude_bus_id.add((bus, can_id))
                else:
                    exclude_id.add(can_id)
            else:
                sig = entry["signal"]
                if bus:
                    exclude_bus_signal.add((bus, sig))
                else:
                    exclude_global.add(sig)
        else:
            # CLI format: "bus:signal" or just "signal"
            if ":" in entry:
                bus, sig = entry.split(":", 1)
            else:
                bus, sig = None, entry
            if bus:
                exclude_bus_signal.add((bus, sig))
            else:
                exclude_global.add(sig)

    return exclude_global, exclude_bus_signal, exclude_id, exclude_bus_id


def stream_and_write(
    path: Path,
    databases: list,
    vehicle: str,
    session: str,
    start_epoch_ns: int,
    upload_raw: bool,
    bus_map: dict,
    batch_size: int,
    http_session,
    write_url: str,
    dry_run: bool,
    exclude_global: set = frozenset(),
    exclude_bus_signal: set = frozenset(),
    exclude_id: set = frozenset(),
    exclude_bus_id: set = frozenset(),
    on_change: bool = True,
    heartbeat_s: float = 1.0,
    only_ids: set | None = None,
) -> int:
    """
    Single streaming pass: decode each frame and write to InfluxDB in
    fixed-size batches. A background writer thread POSTs pre-built line
    protocol while the main thread continues decoding, hiding network
    round-trip latency. Returns total points queued (or counted in dry-run
    mode).

    Schema: one point per DECODED FRAME, with each signal stored as a field.
    Tag set is {vehicle, bus, can_id, session} -- signal name is NOT a tag,
    so series cardinality stays bounded and Grafana queries scan a single
    series per CAN ID. Querying a signal becomes SELECT "Signal_Name" instead
    of WHERE signal='Signal_Name'.

    Wire format: line protocol is generated here directly, not via
    influxdb-python's ``client.write_points`` / ``make_line``. The pure-Python
    client serializer was the second-largest hot spot in the 535MB benchmark
    (~65s tottime in `make_line` plus ~71s in `_escape_tag` -- 12 escape
    calls per point even though the tag set is fixed across the whole upload).
    Here, the static tag prefix `signals,bus=X,can_id=0x...,session=Y,vehicle=Z `
    is built once per (bus, can_id) pair and cached, so the per-point
    work is just a field-list f-string concat plus a ts_ns concat.

    Tag values ARE escaped (see escape_tag), but only once per (bus, can_id)
    when the prefix is built and cached -- so the hot loop still pays nothing,
    while a `--session` containing a space no longer corrupts the stored tag.

    Write policy. With on_change=True (default) a signal is emitted only when
    its value differs from the last value emitted for that signal, plus a
    heartbeat point whenever heartbeat_s has elapsed since that signal's last
    emission. So heartbeat_s is the maximum gap between consecutive points for
    any signal, which keeps Grafana's last-value-before-window correct and
    bounds gap length. Measured 3.5x less disk than on_change=False on a
    52 MB Vtrux log (the internal `influx-sync` plan, Lever C).

    The forward-fill of an on-change series reconstructs the every-frame
    series exactly at every original timestamp; that equivalence is what
    tools/artifacts/on_change_equivalence.py checks.

    Because a frame's signals are now emitted independently, one line may
    carry a subset of the frame's fields (only the ones that changed). That is
    normal in line protocol -- fields are independent columns -- and is why
    the value count falls ~4.8x while the line count only falls ~2.4x.
    """
    id_index = build_id_index(databases)
    can_id_hex_cache: dict[int, str] = {}
    sig_prefix_cache: dict[tuple, str] = {}
    raw_prefix_cache: dict[tuple, str] = {}
    queued = 0
    values_written = 0
    frames_seen = 0

    # Recorded, never recomputed. The repair path deletes a (file x can_id)
    # window by these bounds; the slice test showed that re-deriving them from
    # the file later picks up any config drift (a --tz default put them 7 h off,
    # the DELETE matched zero rows, and the "repair" silently became an append).
    # So the uploader reports exactly what it wrote.
    t_min_ns: int | None = None
    t_max_ns: int | None = None
    written_keys: set = set()

    # on-change state, keyed (bus_name, arb_id, signal_name).
    # last_val: last value EMITTED (not last seen) -- so a signal that flips
    # away and back between heartbeats still emits both transitions.
    # last_emit_ns: absolute ns of that signal's last emission. Integer, not
    # float seconds: comparing `t - last_t < heartbeat` in float made a sample
    # landing exactly one heartbeat later evaluate as 0.9999999999 < 1.0 and
    # get skipped, deferring it to the next frame. Rare (6 in 1.2M) and
    # harmless, but it made the emission rule inexact and untestable.
    last_val: dict[tuple, object] = {}
    last_emit_ns: dict[tuple, int] = {}
    heartbeat_ns = round(heartbeat_s * NS_PER_S)
    esc_session = escape_tag(session)
    esc_vehicle = escape_tag(vehicle)

    file_size = path.stat().st_size
    avg_bytes_per_line = estimate_avg_bytes_per_line(path)
    can_show_pct = file_size > 0 and avg_bytes_per_line > 0

    # Tag prefix builders. Tags are emitted in alphabetical order so that the
    # InfluxDB engine can take the cached series hash without resorting -- a
    # convention the official client follows internally.
    def signals_prefix(bus_name: str, can_id_hex: str) -> str:
        key = (bus_name, can_id_hex)
        cached = sig_prefix_cache.get(key)
        if cached is None:
            cached = (f"signals,bus={escape_tag(bus_name)},can_id={can_id_hex},"
                      f"session={esc_session},vehicle={esc_vehicle} ")
            sig_prefix_cache[key] = cached
        return cached

    def raw_prefix(bus_name: str, can_id_hex: str) -> str:
        key = (bus_name, can_id_hex)
        cached = raw_prefix_cache.get(key)
        if cached is None:
            cached = (f"raw,bus={escape_tag(bus_name)},can_id={can_id_hex},"
                      f"session={esc_session},vehicle={esc_vehicle} ")
            raw_prefix_cache[key] = cached
        return cached

    # Lines accumulate as Python strings; encoded once per flush.
    batch: list[str] = []

    write_queue: queue.Queue = queue.Queue(maxsize=3)
    write_error: list = [None]

    def writer_worker():
        while True:
            item = write_queue.get()
            if item is None:
                write_queue.task_done()
                break
            try:
                if not dry_run:
                    resp = http_session.post(write_url, data=item, timeout=60)
                    if resp.status_code >= 300:
                        raise RuntimeError(
                            f"InfluxDB write failed {resp.status_code}: "
                            f"{resp.text[:300]}"
                        )
            except Exception as exc:
                write_error[0] = exc
            finally:
                write_queue.task_done()

    worker = threading.Thread(target=writer_worker, daemon=True)
    worker.start()

    def flush():
        nonlocal queued
        if not batch:
            return
        if write_error[0]:
            raise write_error[0]
        body = "".join(batch).encode("utf-8")
        n_lines = len(batch)
        batch.clear()
        queued += n_lines
        write_queue.put(body)
        if can_show_pct:
            est_pct = int(frames_seen * avg_bytes_per_line * 100 / file_size)
            pct = f" (~{est_pct}%)"
        else:
            pct = ""
        print(f"  {queued} points queued{pct}", end="\r", flush=True)

    for frame in parse_file(path):
        frames_seen += 1
        if frame.is_tx:
            continue

        arb_id = frame.arbitration_id

        # Targeted repair: restrict this pass to specific CAN IDs. Because
        # can_id is a tag, each message is its own series, so re-uploading one
        # ID rewrites exactly that series and touches nothing else. Checked
        # first -- it is the cheapest possible rejection and repair runs
        # discard the overwhelming majority of frames here.
        if only_ids is not None and arb_id not in only_ids:
            continue

        if arb_id in exclude_id:
            continue

        # bus_map[chan] is None for transient/churn channels (see Vtrux T0
        # Android startup behaviour, projects/vtrux/README.md "Bus number churn in Android T0").
        bus_name = bus_map.get(frame.bus)
        if bus_name is None:
            continue

        if (bus_name, arb_id) in exclude_bus_id:
            continue

        # Integer arithmetic throughout: start_epoch_ns is an exact integer and
        # frame.timestamp is a small float (seconds since log start), so
        # round(t * 1e9) is exact to the nanosecond. The old
        # int((start_epoch + t) * 1e9) added a ~1.7e9 float epoch first, which
        # cost ~0.24 us of mantissa and injected +/-128 ns of noise.
        t_rel = frame.timestamp
        ts_ns = start_epoch_ns + round(t_rel * 1_000_000_000)
        can_id_hex = can_id_hex_cache.get(arb_id)
        if can_id_hex is None:
            can_id_hex = f"0x{arb_id:03X}"
            can_id_hex_cache[arb_id] = can_id_hex

        decoded = False
        if arb_id in id_index:
            signals = decode_frame(frame, id_index)
            field_parts = []
            for sig_name, sig_value in signals.items():
                if sig_value is None:
                    continue
                if sig_name in exclude_global:
                    continue
                if (bus_name, sig_name) in exclude_bus_signal:
                    continue
                if on_change:
                    key = (bus_name, arb_id, sig_name)
                    prev_ns = last_emit_ns.get(key)
                    if (last_val.get(key, _UNSET) == sig_value
                            and prev_ns is not None
                            and ts_ns - prev_ns < heartbeat_ns):
                        continue
                    last_val[key] = sig_value
                    last_emit_ns[key] = ts_ns
                field_parts.append(f"{sig_name}={float(sig_value)}")
            if field_parts:
                batch.append(
                    f"{signals_prefix(bus_name, can_id_hex)}"
                    f"{','.join(field_parts)} {ts_ns}\n"
                )
                values_written += len(field_parts)
                written_keys.add((bus_name, can_id_hex))
                if t_min_ns is None or ts_ns < t_min_ns:
                    t_min_ns = ts_ns
                if t_max_ns is None or ts_ns > t_max_ns:
                    t_max_ns = ts_ns
            decoded = bool(signals)

        if upload_raw and not decoded:
            # raw measurement: int fields written with the InfluxDB 'i' suffix
            # so they stay typed as integers in the database (line protocol's
            # default for `field=N` is float).
            field_parts = [f"dlc={frame.dlc}i"]
            for i, b in enumerate(frame.data):
                field_parts.append(f"b{i}={b}i")
            batch.append(
                f"{raw_prefix(bus_name, can_id_hex)}"
                f"{','.join(field_parts)} {ts_ns}\n"
            )
            values_written += len(field_parts)
            written_keys.add((bus_name, can_id_hex))
            if t_min_ns is None or ts_ns < t_min_ns:
                t_min_ns = ts_ns
            if t_max_ns is None or ts_ns > t_max_ns:
                t_max_ns = ts_ns

        if len(batch) >= batch_size:
            flush()

    flush()
    write_queue.put(None)
    write_queue.join()
    if write_error[0]:
        raise write_error[0]
    label = "counted" if dry_run else "written"
    policy = f"on-change/{heartbeat_s:g}s" if on_change else "all-frames"
    print(f"  {queued} points, {values_written} values {label}  "
          f"[{policy}]          ")
    return {
        "points": queued,
        "values": values_written,
        "t_start_ns": t_min_ns,
        "t_end_ns": t_max_ns,
        "keys": written_keys,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Upload CAN log data to InfluxDB 1.x",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload a single file
  py -3.11 tools/influx_upload.py canlog_20260315_143000_M0_T0.log --vehicle vtrux

  # Upload all logs in a folder (non-recursive, .log/.asc/.trc/.csv)
  py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux

  # Upload a folder with a success log so interrupted runs can resume
  py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux
      --success-log projects/vtrux/notes/artifacts/upload_done.txt

  # Add an extra DBC on top of the vehicle defaults
  py -3.11 tools/influx_upload.py <log> --vehicle coda --dbc projects/coda/extra.dbc

  # Include raw bytes for frames not in any DBC
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --raw

  # Re-upload after DBC changes (delete old data first)
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --delete

  # Dry run to verify parsing, bus detection, and point counts
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --dry-run
    """,
    )
    p.add_argument("logs", nargs="+",
                   help="Log file(s) or folder(s) to upload (auto-detects format). "
                        "Folders are expanded non-recursively to .log/.asc/.trc/.csv files.")
    p.add_argument("--vehicle", "-v", required=True,
                   help=f"Vehicle name ({', '.join(VEHICLE_PROFILES)}). "
                        "Sets default DBC list and bus anchor IDs.")
    p.add_argument("--dbc", "-d", nargs="+", metavar="DBC",
                   help="Extra DBC file(s) to load in addition to the vehicle defaults")
    p.add_argument("--host",     default="localhost",    help="InfluxDB host (default: localhost)")
    p.add_argument("--port",     type=int, default=8086, help="InfluxDB port (default: 8086)")
    p.add_argument("--database", default="canbus-data",  help="InfluxDB database (default: canbus-data)")
    p.add_argument("--user",     default="claude",       help="InfluxDB username (default: claude)")
    p.add_argument("--password", default="claude",       help="InfluxDB password (default: claude)")
    p.add_argument("--session",  help="Override session name tag (default: derived from filename)")
    p.add_argument("--tz", default="America/Los_Angeles", metavar="TZ",
                   help="Timezone of the recording PC's clock. The BUSMASTER header timestamp "
                        "is local time; this converts it to UTC. Accepts IANA names "
                        "('America/Los_Angeles', 'America/Denver', 'UTC') or numeric offsets "
                        "('-7', '-8'). Default: America/Los_Angeles (Pacific, DST-aware).")
    p.add_argument("--exclude", nargs="+", metavar="SIGNAL",
                   help="Exclude signal(s) from upload. Format: 'SignalName' (all buses) "
                        "or 'bus:SignalName' (specific bus). Stacks with profile defaults.")
    p.add_argument("--compress", action="store_true",
                   help="Reserved for future gzip support (no-op; influxdb-python 5.x "
                        "does not expose gzip_body)")
    p.add_argument("--raw", action="store_true",
                   help="Upload raw byte values for frames not decoded by any DBC")
    p.add_argument("--delete", action="store_true",
                   help="clear stored points for vehicle+session before uploading "
                        "(time-bounded DELETE, verified)")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and count points but do not write to InfluxDB")
    p.add_argument("--batch-size", type=int, default=5000,
                   help="Points per write batch (default: 5000)")
    p.add_argument("--write-policy", choices=("on-change", "all-frames"),
                   default="on-change",
                   help="on-change (default): write a signal only when its value changes, "
                        "plus a heartbeat at most every --heartbeat seconds. Measured 3.5x "
                        "less disk than all-frames. all-frames: write every decoded frame "
                        "(the pre-2026-08 behaviour).")
    p.add_argument("--only-id", nargs="+", metavar="CAN_ID",
                   help="Restrict the upload to these CAN IDs (hex '0x598' or decimal). "
                        "Used for targeted repair after a DBC message definition changes: "
                        "drop just that message's series, then re-upload just that ID. "
                        "Everything else in the log is skipped.")
    p.add_argument("--heartbeat", type=float, default=1.0, metavar="SECONDS",
                   help="Maximum gap between consecutive points for a signal under "
                        "--write-policy on-change (default: 1.0). Bounds gap length so "
                        "Grafana's last-value-before-window stays correct.")
    p.add_argument("--success-log", metavar="FILE",
                   help="File to append successfully uploaded log paths to (append-only). "
                        "Skips files whose resolved path is already listed. "
                        "Use this when uploading a folder so interrupted batches can be resumed "
                        "without re-uploading files that already finished. "
                        "No-op in --dry-run mode.")
    args = p.parse_args()

    # Dependency checks. `requests` is only needed when actually writing, so
    # --dry-run works on a machine with no HTTP client installed (Debian's
    # PEP 668 blocks `pip install`, and the old check aborted dry-run for a
    # package it never used).
    if cantools is None:
        print("Error: cantools not installed.  pip install cantools", file=sys.stderr)
        sys.exit(1)

    only_ids = None
    if args.only_id:
        try:
            only_ids = {int(x, 0) for x in args.only_id}
        except ValueError as e:
            print(f"Error: --only-id takes hex ('0x598') or decimal values: {e}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"  restricting to {len(only_ids)} CAN ID(s): "
              f"{', '.join(f'0x{i:03X}' for i in sorted(only_ids))}")
    if requests is None and not args.dry_run:
        print("Error: requests package not installed.  pip install requests", file=sys.stderr)
        sys.exit(1)

    # Resolve vehicle profile
    profile = VEHICLE_PROFILES.get(args.vehicle)
    if profile is None:
        known = ', '.join(VEHICLE_PROFILES)
        print(f"Error: unknown vehicle '{args.vehicle}'. Known: {known}", file=sys.stderr)
        sys.exit(1)

    bus_anchors = profile["bus_anchors"]
    min_anchor_hits = profile.get("min_anchor_hits")
    exclude_global, exclude_bus_signal, exclude_id, exclude_bus_id = build_exclude_sets(
        profile.get("exclude", []),
        args.exclude or [],
    )
    if exclude_global or exclude_bus_signal or exclude_id or exclude_bus_id:
        for sig in sorted(exclude_global):
            print(f"  excluding signal: {sig} (all buses)")
        for bus, sig in sorted(exclude_bus_signal):
            print(f"  excluding signal: {sig} (bus={bus})")
        for can_id in sorted(exclude_id):
            print(f"  excluding message: 0x{can_id:03X} (all buses)")
        for bus, can_id in sorted(exclude_bus_id, key=lambda x: (x[0], x[1])):
            print(f"  excluding message: 0x{can_id:03X} (bus={bus})")

    # Build DBC path list: vehicle defaults + any --dbc extras
    dbc_paths = list(profile["dbcs"])
    if args.dbc:
        dbc_paths += [Path(d) for d in args.dbc]

    # Load all DBCs
    print(f"Loading DBCs for {args.vehicle}:")
    databases = load_databases(dbc_paths)
    if not databases:
        print("Warning: no DBCs loaded -- only raw bytes will be written (use --raw)", file=sys.stderr)

    for name, db in databases:
        n_sigs = sum(len(m.signals) for m in db.messages)
        print(f"  {name}: {len(db.messages)} messages, {n_sigs} signals")

    # Per-(bus, can_id) definition hashes and the whole-file policy hash. Both
    # go into every manifest row so a later sync run can tell a changed message
    # (repair one can_id) from a changed policy (re-upload the file).
    msg_hash_map = message_hashes(
        databases, [b for b, _ in bus_anchors],
        exclude_global=exclude_global, exclude_bus_signal=exclude_bus_signal,
        exclude_id=exclude_id, exclude_bus_id=exclude_bus_id,
    )
    policy_h = policy_hash(profile.get("exclude", []), args.exclude,
                           args.write_policy == "on-change", args.heartbeat,
                           args.raw, only_ids,
                           profile.get("min_anchor_hits"))
    # The hash the manifest should carry once a --only-id upload is merged back
    # into the file's existing row: the row then again describes a full upload
    # under the base policy. See merge_manifest_fields.
    base_policy_h = policy_hash(profile.get("exclude", []), args.exclude,
                                args.write_policy == "on-change", args.heartbeat,
                                args.raw, None,
                                profile.get("min_anchor_hits"))
    print(f"  {len(msg_hash_map)} (bus,can_id) definition hashes; "
          f"policy {policy_h}")

    # Everything goes through a plain requests.Session -- both writes and the
    # control-plane statements (DELETE, SHOW). The influxdb-python client used
    # to be imported solely for the latter's two query() calls; each is
    # a one-line HTTP POST, so the dependency bought nothing and could not be
    # installed on Debian anyway (PEP 668). Writes were already custom: the
    # per-point serializer in stream_and_write profiled ~3-5x faster than the
    # client's `make_line` once tag-prefix caching is in place. HTTP keepalive
    # gives the same single-TCP-connection behaviour.
    http_session = None
    write_url = None
    query_url = None
    if not args.dry_run:
        http_session = requests.Session()
        http_session.auth = (args.user, args.password)
        write_url = (f"http://{args.host}:{args.port}/write"
                     f"?db={args.database}&precision=n")
        query_url = f"http://{args.host}:{args.port}/query"

    def influx_statement(q: str, timeout: int = 120):
        """POST a control-plane statement (DELETE, SHOW, ...).

        Must be POST: InfluxDB 1.x accepts these over GET but answers with a
        'deprecated use ... in a read only context' warning.
        """
        resp = http_session.post(query_url, data={"db": args.database, "q": q},
                                 timeout=timeout)
        if resp.status_code >= 300:
            raise RuntimeError(f"InfluxDB query failed {resp.status_code}: "
                               f"{resp.text[:300]}")
        body = resp.json()
        for result in body.get("results", []):
            if "error" in result:
                raise RuntimeError(f"InfluxDB error for {q!r}: {result['error']}")
        return body

    try:
        recording_tz = _parse_tz(args.tz)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Recording timezone: {args.tz}")

    # Shared across all files so each directory is scanned once.
    timebase = TimebaseIndex()

    # Expand positional args:
    #   foo.log              -> use as-is
    #   path/to/folder/      -> expand to all .log/.asc/.trc/.csv inside
    #   path/with/*.log      -> shell-style glob (script-side, so PowerShell
    #                           and cmd users get the same convenience as Bash)
    _LOG_EXTS = {'.log', '.asc', '.trc', '.csv'}
    log_paths: list[Path] = []
    for entry in args.logs:
        if any(c in entry for c in '*?['):
            matches = sorted(Path(p) for p in glob.glob(entry))
            if not matches:
                print(f"Warning: no files matched glob {entry}", file=sys.stderr)
            log_paths.extend(matches)
            continue
        p_entry = Path(entry)
        if p_entry.is_dir():
            expanded = sorted(f for f in p_entry.iterdir()
                              if f.is_file() and f.suffix.lower() in _LOG_EXTS)
            if not expanded:
                print(f"Warning: no log files found in folder {entry}", file=sys.stderr)
            log_paths.extend(expanded)
        else:
            log_paths.append(p_entry)

    # Load already-uploaded paths from the success log (if provided).
    done_paths: set[str] = set()
    if args.success_log:
        sl_path = Path(args.success_log)
        if sl_path.exists():
            for line in sl_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line:
                    done_paths.add(line)
        if done_paths:
            print(f"Success log: {len(done_paths)} file(s) already uploaded, will skip.")

    # Pre-compute (log_path, session) pairs for files we will actually upload,
    # so --delete can run ONCE per unique session before the upload loop
    # begins. Previous behaviour ran DROP per file, which on a multi-file
    # upload sharing one --session caused each file to wipe the previous
    # file's data, leaving only the last file's points in InfluxDB.
    pending: list[tuple[Path, str]] = []
    skipped_done: list[Path] = []
    failed: list[str] = []
    for log_path in log_paths:
        resolved_str = str(log_path.resolve())
        if resolved_str in done_paths:
            skipped_done.append(log_path)
            continue
        if not log_path.exists():
            print(f"Skipping {log_path}: file not found", file=sys.stderr)
            failed.append(str(log_path))
            continue
        pending.append((log_path, args.session or derive_session(log_path)))

    if args.delete and not args.dry_run and pending:
        unique_sessions = sorted(set(s for _, s in pending))
        print(f"\nClearing stored points for "
              f"{len(unique_sessions)} session(s) before upload ...")
        for sess in unique_sessions:
            clear_session_window(influx_statement, args.vehicle, sess,
                                 with_raw=args.raw)

    for log_path in skipped_done:
        print(f"\nSkipping {log_path.name}: already in success log")

    for log_path, session in pending:
        resolved_str = str(log_path.resolve())

        print(f"\n--- {log_path.name}")
        print(f"  session : {session}")

        try:
            # Pass 1: scan for per-channel IDs and frame counts (streaming, low memory).
            # The frame counts feed identify_buses' churn filter (Vtrux Android T0).
            print(f"  Scanning ...")
            channel_ids, channel_counts, log_duration = scan_log(log_path)
            total_frames = sum(channel_counts.values())
            print(f"  {total_frames} frames across {len(channel_counts)} channel(s)")

            start_epoch_ns = derive_start_epoch_ns(log_path, log_duration,
                                                   recording_tz, timebase)
            start_dt = datetime.fromtimestamp(
                start_epoch_ns / NS_PER_S, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"  anchor  : {start_dt}")

            bus_map = identify_buses(channel_ids, channel_counts, bus_anchors,
                                     min_anchor_hits=min_anchor_hits)
            for ch, name in sorted(bus_map.items()):
                count = channel_counts.get(ch, 0)
                n_ids = len(channel_ids.get(ch, set()))
                if name is None:
                    # Say WHY, so backfill.log is an auditable record of every
                    # bus decision rather than an opaque "SKIP". A channel is
                    # dropped either because a higher-count channel already
                    # claims its bus (churn) or because nothing identified it
                    # and it is below the floor.
                    ids_here = channel_ids.get(ch, set())
                    claim = None
                    for bname, anch in bus_anchors:
                        if ids_here & anch:
                            frac = len(ids_here & anch) / len(anch)
                            if claim is None or frac > claim[1]:
                                claim = (bname, frac)
                    if claim:
                        print(f"  ch{ch} -> SKIP duplicate of {claim[0]} "
                              f"({count} frames, {n_ids} unique IDs, "
                              f"{claim[1]:.0%} anchor match)")
                    else:
                        print(f"  ch{ch} -> SKIP unidentified "
                              f"({count} frames, {n_ids} unique IDs)")
                else:
                    print(f"  ch{ch} -> {name}  ({count} frames, {n_ids} unique IDs)")

            # Pass 2: stream decode + write. Progress is byte-based, estimated
            # from file_size and a sniffed avg-bytes-per-line ratio (no frame
            # count needed); the '~' prefix flags it as approximate.
            print(f"  Writing ...")
            stats = stream_and_write(
                log_path, databases, args.vehicle, session,
                start_epoch_ns, args.raw, bus_map,
                args.batch_size, http_session, write_url, args.dry_run,
                exclude_global=exclude_global,
                exclude_bus_signal=exclude_bus_signal,
                exclude_id=exclude_id,
                exclude_bus_id=exclude_bus_id,
                on_change=(args.write_policy == "on-change"),
                heartbeat_s=args.heartbeat,
                only_ids=only_ids,
            )

        except Exception as exc:
            print(f"\n  ERROR uploading {log_path.name}: {exc}", file=sys.stderr)
            failed.append(str(log_path))
            continue

        # Manifest AFTER the data lands, never before: an interrupted upload
        # must leave no row claiming the file is done, so a re-run replans it.
        if not args.dry_run and stats["points"]:
            try:
                # Relative to the project root, with `..` allowed, so the
                # Android backup library (a sibling SeaDrive library at
                # ../../CANLogs) is recorded portably. Storing an absolute path
                # is what made the old upload_success.txt files useless -- they
                # hold Windows paths and match nothing on any other machine.
                rel = os.path.relpath(log_path.resolve(), PROJECT_ROOT).replace(os.sep, "/")
                merged = None
                if only_ids:
                    prev = fetch_manifest_row(influx_statement, args.vehicle,
                                              session, log_path.name)
                    merged = merge_manifest_fields(
                        prev, msg_hash_map=msg_hash_map, stats=stats,
                        policy_h=base_policy_h, bus_map=bus_map,
                        requested_ids={f"0x{i & 0x1FFFFFFF:03X}"
                                       for i in only_ids})
                    if merged is None:
                        print(f"  WARNING: no previous manifest row for "
                              f"{log_path.name}; writing a partial row, which "
                              f"will schedule a full re-upload", file=sys.stderr)
                line = build_manifest_line(
                    vehicle=args.vehicle, session=session, path=log_path,
                    rel_path=rel, stats=stats, bus_map=bus_map,
                    msg_hash_map=msg_hash_map, policy_h=policy_h,
                    log_sha1=sha1_file(log_path),
                    uploaded_at_ns=time.time_ns(), merged=merged,
                )
                resp = http_session.post(write_url, data=line.encode(), timeout=60)
                if resp.status_code >= 300:
                    raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
                if merged is not None:
                    print(f"  manifest: {len(stats['keys'])} message(s) merged "
                          f"into {len(merged[0])} for the file")
                else:
                    print(f"  manifest: {len(stats['keys'])} message(s), "
                          f"{stats['t_start_ns']}..{stats['t_end_ns']}")
            except Exception as exc:
                print(f"  WARNING: manifest write failed for {log_path.name}: {exc}",
                      file=sys.stderr)
                failed.append(str(log_path))
                continue

        if args.success_log and not args.dry_run:
            with open(args.success_log, 'a', encoding='utf-8') as sf:
                sf.write(resolved_str + '\n')

    print("\nDone.")
    if failed:
        print(f"  {len(failed)} file(s) failed or not found:", file=sys.stderr)
        for f in failed:
            print(f"    {f}", file=sys.stderr)


if __name__ == "__main__":
    main()
