# Simulators, virtual CAN buses and background processes

Rules for any session that runs a multi-process CAN simulator, or any
background process that transmits: Coda's `flash_sim`, the Vtrux benches, and
anything new. Moved here from the ESP firmware development
notes (internal-only) on 2026-10-23 (user), since they are not specific to the ESP work.

**This file has a twin** in the `canbus-esp-fw-vtrux` repo's `AGENTS.md`,
section "Simulators, virtual CAN buses and background processes", which covers
the ESP projects' simulators. The methodology owner (the "Git based esp methodology session" since
2026-10-23, user) keeps the two in step: a change to either goes through it and is made to both at once.
The deliberate differences: this copy covers Coda's `flash_sim` and its
kill recipe keeps the reverse-it interposer path; the repo copy describes the
shared tooling's run guard.

These rules exist because on 2026-09-01 the Vtrux interposer bench flooded the
house LAN with **66,450 packets/s (13.6 MB/s, ~109 Mbit/s)** for roughly twenty
minutes and disrupted the user's network. Read them before running any
multi-process simulator.

## A virtual CAN bus is not automatically local

`python-can`'s `udp_multicast` transport defaults to **`hop_limit=1`**, and the
kernel routes `239.0.0.0/8` out the default interface. So every simulated CAN
frame goes on the real wire:

```
$ ip route get 239.0.2.1
multicast 239.0.2.1 dev eno1 src 192.0.2.10      <- the LAN NIC, not loopback
```

Multicast is flooded to every switch port unless IGMP snooping filters it, and
APs transmit it at the lowest basic rate, so wireless clients suffer worst even
when the source is wired.

**Always pass `hop_limit=0`.** TTL 0 means the datagram is looped back to local
sockets and never transmitted on any interface. Delivery between processes on
the same host is unaffected (verified: 2092 frames/s sent, 2092 received, eno1
unchanged from idle).

Do **not** also pin `IP_MULTICAST_IF` to loopback. `python-can` joins the group
with `INADDR_ANY`, which the kernel resolves to the default multicast interface,
so sending via a different interface means receivers see nothing. TTL 0 alone is
both necessary and sufficient.

The interposer's `bus.py` (`charge-interposer/bus.py` in `canbus-esp-fw-vtrux`;
`projects/vtrux/tools/interposer/bus.py` until 2026-10-08) does this correctly
and asserts it at startup. **`projects/coda/tools/flash_sim/bus.py` now does the same** -- it
passes `hop_limit=0` and then re-reads the socket option to verify it, raising
rather than starting if traffic could reach the LAN (`_confine_to_host`, with the
2026-09-01 incident recorded in the comment above it).

*Corrected 2026-09-20.* This paragraph previously said `flash_sim/bus.py` used the
default `hop_limit` and had to be fixed before running those sims. That was true
when written; the fix has since landed. Verify before trusting either claim --
`grep -n hop_limit` on the file settles it in one command.

## Measure, do not assume

Before and after any sustained simulator run, check the interface counters:

```bash
t0=$(cat /sys/class/net/eno1/statistics/tx_packets); sleep 5
t1=$(cat /sys/class/net/eno1/statistics/tx_packets); echo $(( (t1-t0)/5 )) pps
```

Idle on `the Linux box` is single-digit pps. Anything in the thousands while a
sim runs means it is on the wire.

## Killing background processes

**The procedure differs by platform and the Linux one fails silently on
Windows.** Two traps on Linux first, then the Windows branch below -- read the
branch for your actual machine, not just the first one.

### Linux (`the Linux box`) -- two traps

1. **`pkill -f <pattern>` matches your own shell.** The Bash tool runs commands
   through `bash -c '<your command>'`, so the wrapper's command line contains
   the pattern you are searching for and `pkill -9` kills the shell running your
   script. Symptoms: exit code 1 or 143 with no output, and later statements in
   the same command silently never running -- which also means file edits you
   believed were applied were not. Several edits were lost this way before it
   was diagnosed.

2. **Anchoring on the bare interpreter name misses subprocesses.** A runner that
   spawns children via `sys.executable` gives them a command line starting with
   `/usr/bin/python3.13`, so `pgrep -f '^python3\.13 ...'` never matches them.
   Six orphaned simulators survived every cleanup this way and kept transmitting
   long after they were believed dead.

Use this instead -- it matches by path fragment, filters to real interpreter
processes via `/proc/<pid>/comm`, and cannot match the bash wrapper:

```bash
for pid in $(pgrep -f 'charge-interposer|gen-inhibit/tools|tools/interposer' || true); do
  case "$(cat /proc/$pid/comm 2>/dev/null)" in
    python*) kill -9 "$pid" 2>/dev/null || true ;;
  esac
done
```

Always verify afterwards (`pgrep -af <fragment>`, `ss -uanp | grep <port>`), and
remember `pgrep`/`pkill` return exit 1 when nothing matches, which aborts the
rest of the command under `set -e` -- append `|| true`.

### The recipe above is Linux-only. On Windows it silently does nothing.

**Everything above assumes `/proc` and a Linux process table. On the Windows
machines (`the bench laptop`, `Desktop`) it matches nothing, kills nothing, and
reports success.** Discovered 2026-09-19, after it let two complete interposer
benches run at once on the same multicast groups, each re-forwarding the
other's traffic in a bridge loop -- 5,780 fps mean against 351 fps for a clean
run. The scenario "failed" on a trip that meant nothing, and the whole
measurement was thrown away.

Three separate failures, and the third is the dangerous one:

1. **`pgrep` under Git Bash does not see native Windows processes.** It sees
   only the MSYS process table. A Python simulator launched via `py -3.11` or
   PowerShell is invisible to it.
2. **`/proc/<pid>/comm` does not exist for native Windows processes**, so the
   `case` filter rejects even the few PIDs `pgrep` does return.
3. **The documented verification cannot fail.** `pgrep -af 'tools/interposer'`
   returns empty for the same reason the kill matched nothing, so you get a
   green check for a cleanup that never ran. Proof at the time: `pgrep -af
   'tools/interposer'` returned empty while a scenario was demonstrably
   mid-run and flooding the bus.

**On Windows, do this instead.**

*Stop the task, not the process.* If you started it with the Bash or PowerShell
tool's `run_in_background`, kill the background **task** -- the process tree
goes with it. That is the primary mechanism and it is more reliable than
hunting PIDs.

*If you must go by PID*, use `Get-CimInstance` and **exclude your own PID**:

```powershell
$me = $PID
$pat = '(charge-interposer|gen-inhibit[/\\]tools|tools[/\\]interposer)'   # build the pattern in a variable
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -match $pat } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

**Trap 1 has a PowerShell form and it is easy to miss.** A `CommandLine -like`
filter matches *the PowerShell process running the filter*, because the pattern
you are searching for is literally in your own command line. This kills your
own shell -- exit 255, and any later statements in that command never run.
Same failure as `pkill -f`, different shell. Two things follow: always exclude
`$PID`, and be aware that a process count taken this way **includes your own
invocation**, so a reading of "1 process alive" may be entirely phantom. Both
happened on 2026-09-19 within minutes of each other.

*Verify by observing effect, not absence.* A process-absence check is exactly
the check that cannot fail here. Confirm the thing actually stopped:

- watch the bus and see 0 fps on every segment (the real check);
- `Get-Process -Name ninja,cmake,python -ErrorAction SilentlyContinue` for
  native processes, which `pgrep` will not show you;
- `Get-NetUDPEndpoint` or `netstat -ano | findstr <port>` for a listener that
  outlived its parent.

A check whose failure mode is indistinguishable from success is not a check.
When cleaning up anything that transmits, prefer evidence that the traffic
stopped over evidence that a process is missing.

**This is the process-cleanup instance of a general failure.** The same shape
shows up in log analysis and in code scans — see
[Filters that fail silently](AGENTS.md#filters-that-fail-silently) under Data
Analysis Rules in AGENTS.md.

## Run long simulations one at a time

Four concurrent scenario runs multiplied the frame rate by four. Run one, watch
it, then run the next.

## One simulator run per machine

Two benches on one machine see each other's frames even with `hop_limit=0`,
since both are on the same host (the 2026-09-19 bridge loop). So only one
simulator run is active per machine at a time (user, 2026-10-23). Before
starting a run, check for a running bench: UDP sockets on its ports, and
Python processes running simulator scripts. If you find one, find out whose
it is before you kill anything: it may be another session's run.

For the ESP benches, the firmware repo's shared bench tooling will enforce
this itself, by those checks plus listening on its segments before it starts
its own simulators (see the repo twin).
