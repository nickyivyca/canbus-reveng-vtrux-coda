"""Tests for hvac_packheat_offset.py against a fake HVAC (HVAC decompile notes section 8).

The fake answers on an in-process python-can 'virtual' bus (no network, no hardware) with
the firmware's rules as read from the listing (notes 6.2, 6.4): 0x22 needs length 3 (else
NRC 0x13) and reads 4 bytes of RAM at 0x2214 + 4 x (DID - 0xE100); 0x2E from 0x750 copies
exactly 4 bytes from the request buffer, whatever the request length, and answers 6E + DID.
Its RAM is the flash image's copy-down (hvacsim), so the script's constants are checked
against the image, not against themselves.

    python3.13 projects/coda/tools/test_hvac_packheat_offset.py
"""

import sys
import threading
from pathlib import Path

import can

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hvac_packheat_offset as H                         # noqa: E402
from hvacsim.startup import copy_down                    # noqa: E402

RAM_BASE = 0x0FE000
INIT = copy_down()


def ram_init(a):
    return INIT.get(RAM_BASE | (a & 0x1FFF), 0)


class FakeHvac:
    """ECU side. nrc={sid: nrc} answers that service negatively; pending=N sends N x 7F sid 78
    first; silent=True never answers. Records every frame it receives."""

    def __init__(self, channel, nrc=None, pending=0, silent=False, fingerprint=None):
        self.bus = can.Bus(interface="virtual", channel=channel)
        self.nrc = nrc or {}
        self.pending = pending
        self.silent = silent
        self.ram = {a: ram_init(a) for a in range(0x2214, 0x2537)}
        if fingerprint is not None:
            for i, b in enumerate(fingerprint):
                self.ram[0x24C4 + i] = b
        self.reqbuf = bytearray(16)
        self.frames = []
        self.requests = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _send(self, payload):
        f = bytes([len(payload)]) + bytes(payload)
        self.bus.send(can.Message(arbitration_id=H.RX_ID, is_extended_id=False,
                                  data=f + b"\x55" * (8 - len(f))))

    def _loop(self):
        while not self._stop.is_set():
            m = self.bus.recv(timeout=0.02)
            if m is None or m.arbitration_id != H.TX_ID:
                continue
            d = bytes(m.data)
            self.frames.append(d)
            n = d[0] & 0x0F
            assert d[0] >> 4 == 0, "fake HVAC handles single frames only"
            req = d[1:1 + n]
            self.reqbuf[:n] = req
            self.requests.append(req)
            if self.silent:
                continue
            sid = req[0]
            for _ in range(self.pending):
                self._send([0x7F, sid, 0x78])
            if sid in self.nrc:
                self._send([0x7F, sid, self.nrc[sid]])
                continue
            did = (req[1] << 8) | req[2]
            addr = 0x2214 + 4 * (did - 0xE100)
            if sid == 0x22:
                if n != 3:
                    self._send([0x7F, 0x22, 0x13])
                elif 0xE100 <= did <= 0xE1FE:
                    self._send(bytes([0x62, req[1], req[2]])
                               + bytes(self.ram[addr + i] for i in range(4)))
                else:
                    self._send([0x7F, 0x22, 0x31])
            elif sid == 0x2E and 0xE100 <= did <= 0xE1FE:
                for i in range(4):
                    self.ram[addr + i] = self.reqbuf[3 + i]
                self._send([0x6E, req[1], req[2]])
            else:
                self._send([0x7F, sid, 0x11])

    def close(self):
        self._stop.set()
        self._t.join()
        self.bus.shutdown()


_n = [0]


def session(**kw):
    _n[0] += 1
    ch = "hvac_test_%d" % _n[0]
    fake = FakeHvac(ch, **kw)
    tester_bus = can.Bus(interface="virtual", channel=ch)
    return fake, tester_bus, H.Tester(tester_bus, timeout=0.3)


def run_case(raw, confirm=None, **kw):
    fake, bus, t = session(**kw)
    try:
        try:
            rc = H.run(t, raw, confirm=confirm)
        except H.Refused as e:
            rc = e
    finally:
        bus.shutdown()
        fake.close()
    return rc, fake


def sids(fake):
    return [r[0] for r in fake.requests]


# -- constants against the image --------------------------------------------------

def test_constants_match_image():
    assert 0x2214 + 4 * (H.DID_OFFSET - 0xE100) == 0x24C8
    assert bytes(ram_init(a) for a in range(0x24C4, 0x24C8)) == H.FINGERPRINT
    assert bytes(ram_init(a) for a in range(0x24C8, 0x24CC)) == H.STOCK
    assert ram_init(0x2A5A) == 0 and ram_init(0x2A5B) == 4      # the 4-byte E1xx write length


# -- encoding ------------------------------------------------------------------------

def test_encoding():
    assert H.raw_from_c(5) == 20
    assert H.raw_from_c(-0.25) == -1
    assert H.raw_from_c(31.75) == 127 and H.raw_from_c(-32) == -128
    for bad in (0.1, 32, -32.25):
        try:
            H.raw_from_c(bad)
        except ValueError:
            continue
        raise AssertionError("accepted %r" % bad)
    assert H.with_offset(H.STOCK, -1) == bytes([0x00, 0xFF, 0x14, 0x14])
    assert H.c_from_byte(0xFF) == -0.25 and H.c_from_byte(20) == 5.0


def test_frames():
    assert H.single_frame(H.read_request(0xE1AD)) == bytes.fromhex("0322E1ADAAAAAAAA")
    w = H.write_request(0xE1AD, H.with_offset(H.STOCK, 20))
    assert H.single_frame(w) == bytes.fromhex("072EE1AD00141414")


def test_guard():
    for p in (b"\x2E\xE1\xAD\x00\x14", b"\x2E\xE1\xAC\x9C\x09\x0A\x01", b"\x10\x02",
              b"\x31\x01\xFF\x00", b"\x22\xF1\x90", b"\x2E\xE1\xAD\x00\x14\x14\x14\x00"):
        try:
            H.Tester._guard(p)
        except AssertionError:
            continue
        raise AssertionError("guard let %s through" % p.hex(" "))
    try:
        H.write_request(0xE1AD, b"\x00\x14")
    except ValueError:
        pass
    else:
        raise AssertionError("short write built")


# -- sequences against the fake --------------------------------------------------------

def test_write_and_read_back():
    rc, fake = run_case(20)
    assert rc == 0, rc
    assert fake.ram[0x24C9] == 20
    assert [fake.ram[a] for a in (0x24C8, 0x24CA, 0x24CB)] == [0, 20, 20]
    assert sids(fake) == [0x22, 0x22, 0x2E, 0x22]
    assert fake.frames[2] == bytes.fromhex("072EE1AD00141414")


def test_frames_on_the_bus_are_the_dry_run_frames():
    rc, fake = run_case(-8)
    assert rc == 0
    want = [H.single_frame(H.read_request(H.DID_FINGERPRINT)),
            H.single_frame(H.read_request(H.DID_OFFSET)),
            H.single_frame(H.write_request(H.DID_OFFSET, H.with_offset(H.STOCK, -8))),
            H.single_frame(H.read_request(H.DID_OFFSET))]
    assert fake.frames == want


def test_negative_response_to_write():
    rc, fake = run_case(20, nrc={0x2E: 0x11})
    assert isinstance(rc, H.Refused) and "serviceNotSupported" in str(rc), rc
    assert sids(fake) == [0x22, 0x22, 0x2E]            # no read back after a refusal
    assert fake.ram[0x24C9] == 0


def test_negative_response_to_read_stops_before_write():
    rc, fake = run_case(20, nrc={0x22: 0x31})
    assert isinstance(rc, H.Refused) and "requestOutOfRange" in str(rc), rc
    assert 0x2E not in sids(fake)


def test_response_pending_then_positive():
    rc, fake = run_case(4, pending=2)
    assert rc == 0, rc
    assert fake.ram[0x24C9] == 4


def test_no_answer_stops_before_write():
    rc, fake = run_case(20, silent=True)
    assert isinstance(rc, H.Refused) and "awake" in str(rc), rc
    assert sids(fake) == [0x22]


def test_other_firmware_is_refused():
    rc, fake = run_case(20, fingerprint=b"\x9C\x09\x0A\x02")
    assert isinstance(rc, H.Refused) and "different HVAC firmware" in str(rc), rc
    assert 0x2E not in sids(fake)


def test_read_only_and_already_set_and_declined():
    rc, fake = run_case(None)
    assert rc == 0 and 0x2E not in sids(fake)
    rc, fake = run_case(0)
    assert rc == 0 and 0x2E not in sids(fake)
    rc, fake = run_case(20, confirm=lambda old, new: False)
    assert rc == 1 and 0x2E not in sids(fake) and fake.ram[0x24C9] == 0


def test_restore_after_write():
    fake, bus, t = session()
    try:
        assert H.run(t, 20) == 0 and fake.ram[0x24C9] == 20
        assert H.run(t, H.STOCK[H.OFFSET_BYTE]) == 0 and fake.ram[0x24C9] == 0
    finally:
        bus.shutdown()
        fake.close()


def test_dry_run_opens_nothing():
    assert H.main(["--offset-c", "5", "--dry-run"]) == 0
    assert H.main(["--read", "--dry-run"]) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
