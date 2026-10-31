#!/usr/bin/env python3
"""Flash a named DLCM calibration to the Coda: the human-facing front end of the flash tooling.

    py -3.12 projects/coda/tools/flash_cal.py --list
    py -3.12 projects/coda/tools/flash_cal.py c4c-onepedal-156nm

Each name in CAL_IMAGES below is one complete 114,688-byte CAL image. The flash writes exactly that image
and nothing else:

  - CAL segment only. PROG is never erased or written.
  - The image's own bytes are what get written, so a name cannot carry half of an earlier change. Its
    diff from the stock base is still derived and compared against it before the erase, as a cross-check;
    the two disagreeing is a safety abort. Per-patch lines are DEBUG (--debug): one per byte, and on
    2026-10-25 845 of them to a console took ~8 s, overran the 5 s S3 timer and got the erase rejected
    with NRC 0x7F. Volume was not the change -- earlier flashes printed 730-746 with a 0-1 s gap -- so the
    per-line slowdown is unexplained; see the comment in omitec_sim._apply_patches.
  - The image's md5 must match the registry. A 'candidate' image (one that has never run on the car) is
    refused unless --allow-candidate is given.
  - Before anything is sent, the script prints what will change against the on-car reference and asks you
    to type the name back (skip with --yes).

The defaults are the settings every real flash has used (notes/plans/dlcm_next_incar_session.md section 2,
five for five): --block-delay-ms 217, --tx-stmin-ms 1.1, no ignition poll (it opens a second bus handle,
which gs_usb refuses), no startup delay, SecurityAccess level 0x01. The dongle is found automatically
(--transport auto): exactly one CAN interface must be present, otherwise the script lists what it found and
stops, so it cannot pick the wrong one. Name a brand with --transport to choose. (Every real flash so far
used an Innomaker gs_usb on the Diag CAN through the gateway.)

The UDS flash itself is flash_sim/omitec_sim.py's OmitecSim, unchanged; this script only chooses
the image and the settings. After a flash, update omitec_sim.CAL_ON_CAR and the lineage in
notes/dlcm/dlcm-cal-flash-campaign.md, as for any flash.

Test against the simulated gateway (both on the localhost virtual bus):
    py -3.12 projects/coda/tools/flash_sim/gateway_sim.py --time-scale 0.02 --verify-bins
    py -3.12 projects/coda/tools/flash_cal.py stock --transport virtual --yes
"""

import argparse
import hashlib
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLASH_SIM = HERE / "flash_sim"
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(FLASH_SIM))

import omitec_sim as O                                   # noqa: E402
import uds                                               # noqa: E402
from bus import REAL_BRANDS, VIRTUAL_DEFAULT_PORT, open_bus  # noqa: E402
from busload import add_busload_args, governor_from_args  # noqa: E402
from isotp import IsoTpEndpoint, IsoTpError              # noqa: E402

logger = logging.getLogger("flash_cal")

DLCM_DIR = HERE.parent / "notes" / "dlcm"
ART = DLCM_DIR / "artifacts"
IMAGES = DLCM_DIR / "cal_images"

PROVEN = "proven"          # this exact image has run on this car
CANDIDATE = "candidate"    # it never has; refused without --allow-candidate (user 2026-10-16)

# The menu. Headline names (user 2026-10-17); the two candidates and their criteria: notes/dlcm/candidate-criteria.md.
# Change a candidate to PROVEN only after it has been flashed and driven. c4c-onepedal-156nm is listed only
# while C4c is on the car (the way back); it comes off the list when C4c is retired (user 2026-10-16).
CAL_IMAGES = {
    "stock": dict(
        file=DLCM_DIR / "coda_dlcm_cal.bin",
        md5="7db9d7c24918c79814843e7eb812f570",
        status=PROVEN,
        build="factory calibration; flashing it undoes every change, C4c included"),
    "c4c-onepedal-156nm": dict(
        file=ART / "cal_as_flashed_20260925_envelope_c4c.bin",
        md5="2c7a6c6e81fcb16de1719269bf73fede",
        status=PROVEN,
        build="C4c (flash 6, 2026-09-24): one-pedal -156.2 Nm with the accelerator map rebuilt on the "
              "capability envelopes; on the car since the 2026-10-04 revert"),
    "illegal-onepedal-156nm": dict(
        file=IMAGES / "illegal-onepedal-156nm.bin",
        md5="f9885cedd82c87fae50c7b1cc138d769",
        status=CANDIDATE,
        build="full one-pedal regen at C4c's 156.2 Nm, no brake blend; creep off, 25 % low-speed regen floor, "
              "zero point 32.34 % to 31 mph [builder code K1+B25+FLAT31]"),
    "0.13g-brakeblend-156nm": dict(
        file=IMAGES / "0.13g-brakeblend-156nm.bin",
        md5="aa6377a143f216d6083697c65cd57815",
        status=CANDIDATE,
        build="off-throttle regen capped at 0.13 g (106 Nm; 46.6 kW above 31 mph), the full 156.2 Nm blended in on "
              "the brake (0.2 from the switch, full at 256 raw); creep off, 25 % low-speed regen floor, zero point "
              "24.49 %, reverse pedal mapped the same as forward (zero 24.49 %, full pedal 326.8 Nm); highway "
              "chatter fix: CalBoundDerateBGain 230 -> 58 "
              "[builder code K1+B25+FLAT31+R13P75+BBSW20P256+RDZ+G58]"),
    "0.13g-brakeblend-156nm-nochatterfix": dict(
        file=IMAGES / "0.13g-brakeblend-156nm-nochatterfix.bin",
        md5="d917d46543513680472b5de5cde13163",
        status=CANDIDATE,
        build="as 0.13g-brakeblend-156nm without the highway chatter fix: 50.5 kW above 31 mph, "
              "CalBoundDerateBGain stock 230 [builder code K1+B25+FLAT31+R13P10+BBSW20P256+RDZ]"),
}


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def _ndiff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def _car():
    return O.CAL_ON_CAR.read_bytes() if O.CAL_ON_CAR.exists() else None


def list_cals():
    base = O.SEGMENTS["cal"]["bin"].read_bytes()
    car = _car()
    print("On-car reference: %s" % O.CAL_ON_CAR.name)
    print("%-36s %-9s %-8s %9s %9s  %s" % ("name", "status", "md5", "B v stock", "B v car", "build"))
    for name, e in CAL_IMAGES.items():
        if not e["file"].exists():
            print("%-36s %-9s MISSING %s" % (name, e["status"], e["file"]))
            continue
        img = e["file"].read_bytes()
        md5 = _md5(e["file"])
        bad = "" if md5 == e["md5"] else "  ** md5 MISMATCH: file is %s **" % md5
        vs_car = "%9d" % _ndiff(img, car) if car is not None else "        ?"
        on = "  [on the car]" if car is not None and img == car else ""
        print("%-36s %-9s %-8s %9d %s  %s%s%s" % (name, e["status"], e["md5"][:8], _ndiff(img, base),
                                                 vs_car, e["build"], on, bad))


def resolve(name, allow_candidate):
    """(image bytes, patch set) for a named image, after its existence, md5 and status checks."""
    e = CAL_IMAGES[name]
    if not e["file"].exists():
        raise SystemExit("%s: image %s does not exist" % (name, e["file"]))
    md5 = _md5(e["file"])
    if md5 != e["md5"]:
        raise SystemExit("%s: %s has md5 %s, the registry says %s; refusing"
                         % (name, e["file"].name, md5, e["md5"]))
    if e["status"] == CANDIDATE and not allow_candidate:
        raise SystemExit("%s is a candidate: it has never run on the car. Add --allow-candidate "
                         "to flash it anyway." % name)
    return e["file"].read_bytes(), O.patches_from_target(e["file"])


def pick_transport(args):
    """Resolve --transport auto to the brand of the single CAN interface present; refuse otherwise."""
    if args.transport != "auto":
        return
    from canbench.live.receiver import detect_all_can_interfaces
    found = detect_all_can_interfaces(args.bitrate)
    if not found:
        raise SystemExit("--transport auto found no CAN interface. Is the dongle plugged in and its "
                         "driver installed?")
    if len(found) > 1:
        lines = "".join("\n  --transport %-9s  %s" % (i[0], i[2]) for i in found)
        raise SystemExit("--transport auto found %d CAN interfaces and will not guess:%s\n"
                         "Unplug the others, or name the brand with --transport." % (len(found), lines))
    args.transport = found[0][0]
    logger.info("auto: using %s", found[0][2])


def build_argparser():
    p = argparse.ArgumentParser(
        description="Flash a named DLCM calibration (CAL segment only) to the Coda.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("cal", nargs="?", choices=list(CAL_IMAGES), metavar="NAME",
                   help="calibration to flash: %s" % ", ".join(CAL_IMAGES))
    p.add_argument("--list", action="store_true", help="list the calibrations and exit")
    p.add_argument("--allow-candidate", action="store_true",
                   help="allow an image whose status is 'candidate' (never run on the car)")
    p.add_argument("--yes", action="store_true",
                   help="do not ask to type the name back before flashing")
    p.add_argument("--transport", default="auto", choices=("auto", "virtual") + REAL_BRANDS,
                   help="'auto' = the one CAN interface present (refuses if none or several); "
                        "a brand = the first interface of that brand; 'virtual' = localhost sim bus")
    p.add_argument("--channel", default=None,
                   help="real: dongle channel (default: the detected one); virtual: multicast group")
    p.add_argument("--port", type=int, default=VIRTUAL_DEFAULT_PORT, help="virtual transport UDP port")
    p.add_argument("--bitrate", "-b", type=int, default=500000, help="CAN bitrate (bps)")
    add_busload_args(p)
    p.add_argument("--block-delay-ms", type=float, default=217.0,
                   help="idle between TransferData blocks (the Omitec's pacing, survived by the gateway)")
    p.add_argument("--tx-stmin-ms", type=float, default=1.1,
                   help="minimum gap between our frames inside a block (the Omitec's spacing)")
    p.add_argument("--max-blocks", type=int, default=0, help=argparse.SUPPRESS)  # partial transfer: sim tests only
    p.add_argument("--debug", action="store_true", help="debug logging")
    return p


def main():
    args = build_argparser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    if args.list:
        list_cals()
        return
    if args.cal is None:
        build_argparser().print_usage()
        print("give a calibration NAME, or --list to see them")
        sys.exit(2)
    if args.max_blocks and args.transport != "virtual":
        raise SystemExit("--max-blocks leaves a partial CAL on the module; virtual transport only")

    e = CAL_IMAGES[args.cal]
    img, patches = resolve(args.cal, args.allow_candidate)
    pick_transport(args)
    car = _car()
    print()
    print("  calibration  %s  [%s]" % (args.cal, e["status"]))
    print("  build        %s" % e["build"])
    print("  image        %s  md5 %s" % (e["file"].name, e["md5"]))
    print("  changes      %d byte(s) vs stock; %s vs the on-car reference %s"
          % (sum(len(b) for _a, b in patches),
             "%d byte(s)" % _ndiff(img, car) if car is not None else "?", O.CAL_ON_CAR.name))
    if car is not None and img == car:
        print("               (the car already holds this image)")
    print("  segment      CAL only (0x%08X, %d bytes); PROG untouched" % (O.SEGMENTS["cal"]["addr"], len(img)))
    print("  transport    %s; block delay %.0f ms, frame gap %.1f ms" % (args.transport, args.block_delay_ms,
                                                                         args.tx_stmin_ms))
    print()
    if not args.yes:
        if input("Type the calibration name to flash it: ").strip() != args.cal:
            raise SystemExit("name not confirmed; nothing sent")

    bus = open_bus(args, receive_own_messages=False, logger=logger)
    sim = None
    try:
        gov = governor_from_args(args, bitrate=args.bitrate)
        logger.info("%s", gov.describe())
        endpoint = IsoTpEndpoint(bus, tx_id=uds.DEFAULT_REQUEST_ID, rx_id=uds.DEFAULT_RESPONSE_ID,
                                 padding=0xAA, logger=logging.getLogger("omitec_sim"), governor=gov,
                                 tx_stmin_floor=args.tx_stmin_ms / 1000.0)
        sim = O.OmitecSim(endpoint, patches=patches, block_delay_ms=args.block_delay_ms,
                          max_blocks=args.max_blocks, security_level=0x01, whole_image=args.cal,
                          image_bytes=img)
        sim.governor = gov
        t0 = time.monotonic()
        sim.run(["cal"])
        logger.info("flashed '%s' in %.0f s. Now update omitec_sim.CAL_ON_CAR and the lineage in "
                    "dlcm-cal-flash-campaign.md.", args.cal, time.monotonic() - t0)
    except O.SafetyAbort as ex:
        logger.error("SAFETY ABORT (ECU untouched): %s", ex)
        sys.exit(2)
    except (IsoTpError, O.UdsRejected) as ex:
        logger.error("flash aborted after %d block(s): %s", sim.total_blocks if sim else 0, ex)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.error("interrupted after %d block(s)", sim.total_blocks if sim else 0)
        sys.exit(130)
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
