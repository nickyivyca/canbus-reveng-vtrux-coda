"""Measured DLCM/Gateway timing profile from the real reflash capture.

Source: projects/coda/logs/flash/coda_dlcm_flash6.log (54m27s capture of a
complete real Omitec reflash), extracted by
projects/coda/notes/dlcm/artifacts/flash_timing_profile.py.

These are the delays the ECU imposes; the gateway simulator sleeps by these
amounts so a tester (real Omitec or our omitec_sim) sees a realistic cadence.
All values in seconds unless noted.

Key finding: the ECU answers each TransferData block in ~7-8 ms. The ~217 ms
median block-to-block gap in the real log is the OMITEC's own pacing, not the
DLCM. So the block-accept delay below is small; the tester controls throughput.
"""

# --- ECU response latencies (request fully received -> response sent) ---
# TransferData 0x36 -> 0x76 : min 0.0 p50 8.1 p90 11.1 p99 16.0 max 17.4 mean 7.4 ms
TRANSFER_DATA_LATENCY_S = 0.008
# RequestDownload 0x34 -> 0x74 : mean 6.6 ms
REQUEST_DOWNLOAD_LATENCY_S = 0.007
# DiagnosticSessionControl 0x10 -> 0x50 : mean 6.7 ms
DIAG_SESSION_LATENCY_S = 0.007
# SecurityAccess 0x27 -> 0x67 : seed/key mean ~15 ms
SECURITY_ACCESS_LATENCY_S = 0.015
# ReadDataByIdentifier / generic short service default
GENERIC_LATENCY_S = 0.007
# RequestTransferExit 0x37 -> 0x77 (not separately measured; short)
TRANSFER_EXIT_LATENCY_S = 0.007

# --- RoutineControl episodes (0x31) ---
# Each entry: (routine_id, data_hex, total_walltime_s, num_response_pending,
#              response_pending_interval_s)
# From the log:
#   0xFF00 data=02 (PROG erase): 36.5 s, 6 pendings, ~10.4 s apart (the erase)
#   0xFF01 data=--  (verify)   :  2.4 s, 1 pending
#   0xFF00 data=03 (CAL erase) :  2.7 s, 1 pending
#   0xFF01 data=--  (verify)   :  2.4 s, 1 pending
# The gateway sim looks these up by (routine_id, data) to reproduce the delay.
ROUTINE_PROFILE = {
    (0xFF00, "02"): dict(walltime_s=36.5, pendings=6, pending_interval_s=10.4,
                         response_data=bytes.fromhex("ff00")),
    (0xFF00, "03"): dict(walltime_s=2.7, pendings=1, pending_interval_s=2.6,
                         response_data=bytes.fromhex("ff00")),
    (0xFF01, ""):   dict(walltime_s=2.4, pendings=1, pending_interval_s=2.4,
                         response_data=bytes.fromhex("ff010000000c")),
}
# Fallback for an unknown routine: brief, one pending.
ROUTINE_DEFAULT = dict(walltime_s=0.5, pendings=1, pending_interval_s=0.4,
                       response_data=b"")

# Interval the tester should assume between responsePending frames when waiting
# (P2* extended timeout). The real ECU paced pendings up to ~10.4 s apart, so
# the tester must tolerate at least that.
RESPONSE_PENDING_TESTER_TIMEOUT_S = 12.0
