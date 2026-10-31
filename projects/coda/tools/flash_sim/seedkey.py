"""DLCM SecurityAccess seed -> key.

A 48-round Galois-style LFSR with taps at bits 4/11/20/29, keyed by a per-level
secret constant. Recovered 2026-09-19 from the SecurityAccess handler at
0x8007907C once the image was disassembled as TriCore rather than SH-4; see
../dlcm-security-access.md section 1c.

One algorithm, two constants -- not two algorithms, as the notes originally
assumed:

    level 1  (27 01 / 27 02)   0xCAF77776   the PROGRAMMING-session handshake,
                                            i.e. the one a flash needs
    level 3  (27 03 / 27 04)   0x9D89EA36   the EXTENDED-session "Enable
                                            Backdoor" handshake

Verified against every captured pair: 9/9 level-03/04 pairs, and 3/3 genuine
level-01/02 pairs -- flash5, flash6 and the 2026-07-21 session that actually put
FLOOR5 on the car (seed FEED78D7 -> key 51D17AD2). The fourth historical pair,
"flash2", does not fit the level-1 constant but reproduces exactly under the
level-3 one, so it was a level-3 session mislabelled in the notes.

Seed and key are both big-endian on the wire.

IMPORTANT, and the reason self_test() exists: the level-1 path has never been
exercised on the car. Every live unlock so far was level 03/04. The arithmetic
is confirmed against real captured flash-session pairs, which is strong, but it
is not the same as the ECU accepting a key we generated in a programming
session. Treat the first level-1 unlock as an experiment.
"""

SECRET_LEVEL1 = 0xCAF77776
SECRET_LEVEL3 = 0x9D89EA36

SECRETS = {1: SECRET_LEVEL1, 2: SECRET_LEVEL1,
           3: SECRET_LEVEL3, 4: SECRET_LEVEL3}

ROUNDS = 48
TAPS = (4, 11, 20, 29)

# (label, seed, key, secret) for every pair we hold.
KNOWN_PAIRS = [
    ("flash5   (level 1)", 0x89349739, 0x3BED538A, SECRET_LEVEL1),
    ("flash6   (level 1)", 0x7C876E19, 0x2726966F, SECRET_LEVEL1),
    ("20260721 (level 1)", 0xFEED78D7, 0x51D17AD2, SECRET_LEVEL1),
    ("flash2   (level 3)", 0x86BD0760, 0xC6CCDA14, SECRET_LEVEL3),
    ("live 1   (level 3)", 0x195627BC, 0x0524E759, SECRET_LEVEL3),
    ("live 2   (level 3)", 0x92DA0BA7, 0x132A9DC6, SECRET_LEVEL3),
    ("live 3   (level 3)", 0x1660981F, 0xFA2C6D35, SECRET_LEVEL3),
    ("live 4   (level 3)", 0x397BF1F2, 0xEC9418ED, SECRET_LEVEL3),
    ("live 5   (level 3)", 0x1284E071, 0xBC170D5C, SECRET_LEVEL3),
    ("live 6   (level 3)", 0xA86425B0, 0xC0569725, SECRET_LEVEL3),
    ("live 7   (level 3)", 0x9EC33C48, 0x24DEB995, SECRET_LEVEL3),
    ("live 8   (level 3)", 0x5C2CC2F2, 0xC3495EE7, SECRET_LEVEL3),
    ("live 9   (level 3)", 0x20C5FA97, 0xD3DC3E79, SECRET_LEVEL3),
]


def compute_key(seed, secret):
    """seed (int) -> key (int), both 32-bit."""
    v = (seed ^ secret) & 0xFFFFFFFF
    for _ in range(ROUNDS):
        fb = 0
        for t in TAPS:
            fb ^= v >> t
        v = ((v << 1) | (fb & 1)) & 0xFFFFFFFF
    return v


def key_for_level(seed_bytes, level):
    """seed as 4 big-endian bytes + requestSeed subfunction -> key bytes."""
    if level not in SECRETS:
        raise ValueError("no secret known for SecurityAccess level 0x%02X" % level)
    if len(seed_bytes) != 4:
        raise ValueError("expected a 4-byte seed, got %d bytes" % len(seed_bytes))
    seed = int.from_bytes(seed_bytes, "big")
    return compute_key(seed, SECRETS[level]).to_bytes(4, "big")


def self_test(verbose=False):
    """Reproduce every known pair. Returns (n_ok, n_total)."""
    ok = 0
    for label, seed, key, secret in KNOWN_PAIRS:
        got = compute_key(seed, secret)
        good = got == key
        ok += good
        if verbose:
            print("  %-20s seed=%08X expect=%08X got=%08X  %s"
                  % (label, seed, key, got, "OK" if good else "MISMATCH"))
    return ok, len(KNOWN_PAIRS)


if __name__ == "__main__":
    n, total = self_test(verbose=True)
    print("\n%d/%d known seed/key pairs reproduce" % (n, total))
    raise SystemExit(0 if n == total else 1)
