#!/usr/bin/env python3
"""Autonomous CODACAN sweep orchestrator.

Runs a whole queue of CODACAN replay experiments end-to-end with NO second
terminal and no human in the loop. It replaces the old two-terminal workflow
(cowork_replay.py sweep-byte in one terminal + codacan_capture.py watch in
another) with a single controller that:

  * spawns cowork_replay.py as a background SUBPROCESS (it owns the CAN TX and
    writes cowork_state.json) -- one isolated, already-tested TX process, and
  * does the screen capture IN-PROCESS by importing codacan_capture's navigate/
    screenshot/OCR helpers -- so exactly one process touches the GUI and the
    controller decides precisely when to capture, merge, and advance.

Between experiments it can restart CODACAN.exe for a clean baseline (the
"always close and reopen" rule from codacan-signal-decode-notes.md).

Capture/TX sync: cowork_replay holds each sweep step for --dwell seconds. Since
capture (navigate + screenshot + OCR of a tab) takes ~2-3 s per tab, the runner
bumps each sweep's effective dwell up to n_tabs * PER_TAB_SECS + margin so a
step is never overwritten before it is read. Coarse sweeps (step 16, 17 steps)
therefore finish in a couple of minutes; fine 256-step sweeps take longer but
run unattended.

Sub-commands:
  check    Validate preconditions (Kvaser TX, CODACAN window, layout, queue).
           Sends no frames. Use --launch-codacan to start CODACAN first.
  run      Execute a queue JSON. Use --dry-run to validate + print the plan
           with no hardware access.

Queue format: a JSON list of experiment objects. See sweep_queue_test.json for
a minimal example and codacan-replay-verification-queue.md for the full worklist.

Experiment fields:
  name        (str)  label used for output filenames             [required]
  mode        (str)  sweep-byte | inject | solo-id | drop-id | baseline
  tabs        (list) CODACAN tabs to capture, e.g. ["BMS"]        [required]
  log         (str)  path to CAN log (all modes except inject)
  target      (str)  hex CAN ID (sweep-byte / solo-id / drop-id)
  byte        (str)  byte index or range, e.g. "2" or "2-3"       (sweep-byte)
  dwell       (num)  requested per-step hold seconds              (sweep-byte)
  step        (int)  sweep step size (default 16 = coarse)        (sweep-byte)
  id          (str)  hex CAN ID to inject                         (inject)
  data        (str)  hex bytes, e.g. "64 32 80 00 01 5E 00 DD"    (inject)
  interval    (num)  inject frame interval seconds (default 0.1)  (inject)
  duration    (num)  inject / bounded-run seconds (default 20)
  start_time  (num)  log time-slice start seconds                 (optional)
  end_time    (num)  log time-slice end seconds                   (optional)
  settle      (num)  seconds to wait before snapshot (non-sweep)  (optional)
  note        (str)  free-text description                        (optional)

Python: py -3.11 (32-bit) on the bench machine -- it has python-can + Kvaser
canlib AND Pillow/pyautogui/pytesseract. Invoke from the project root.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TOOLS_DIR.parent.parent.parent))  # repo root, so cowork_replay's `import canre` works

import codacan_capture as cc  # noqa: E402  (navigate/screenshot/OCR helpers + layout)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('autosweep')

# ---------------------------------------------------------------------------
# Defaults / config
# ---------------------------------------------------------------------------
REPO_ROOT       = TOOLS_DIR.parent.parent.parent          # .../reverse-it
REPLAY_SCRIPT   = TOOLS_DIR / 'cowork_replay.py'
CODACAN_EXE     = TOOLS_DIR.parent / 'CODACAN' / 'CODACAN.exe'
CODACAN_DIR     = CODACAN_EXE.parent
LAYOUT_FILE     = TOOLS_DIR.parent / 'CODACAN' / 'ui_layout.json'
DEFAULT_OUTDIR  = TOOLS_DIR.parent / 'notes' / 'artifacts' / 'cowork-results' / 'autosweep'
WINDOW_TITLE    = cc.DEFAULT_WINDOW_TITLE                  # "CODACAN.vi"

PY_EXE          = ['py', '-3.11']    # replay subprocess interpreter
BRANDS          = 'kvaser'           # TX dongle on this bench (Kvaser Leaf Light v2)
BITRATE         = 500000

PER_TAB_SECS    = 7.0                # measured capture cost per tab, ALL fields (navigate+shot+OCR of ~32 fields)
PER_FIELD_SECS  = 0.25               # incremental OCR cost per field when a 'fields' filter is used
NAV_SHOT_SECS   = 1.6                # fixed navigate+screenshot cost per tab
SETTLE_SECS     = 1.2                # fixed wait for CODACAN to render the new value before capture
DWELL_MARGIN    = 1.0
POLL            = 0.4                # state-file poll interval

# CODACAN launches to a splash screen with a "Connect to CAN" button that must be
# clicked before it connects to the bus and shows the tabbed data view. Button
# centre as a fraction of the window (measured on the 1936x1380 live window).
CONNECT_BTN_REL = (0.311, 0.565)


# ---------------------------------------------------------------------------
# CODACAN window / lifecycle
# ---------------------------------------------------------------------------
def find_window(title=WINDOW_TITLE, retries=1, wait=1.0):
    """Return the CODACAN window, or None. Does NOT sys.exit (unlike cc.find_codacan_window)."""
    import pyautogui
    for _ in range(max(1, retries)):
        matches = pyautogui.getWindowsWithTitle(title)
        if matches:
            return matches[0]
        time.sleep(wait)
    return None


def launch_codacan(warmup=10.0, window_wait=25.0):
    """Launch CODACAN.exe and wait for its window. Returns the window or None."""
    if not CODACAN_EXE.exists():
        logger.error("CODACAN.exe not found at %s", CODACAN_EXE)
        return None
    logger.info("Launching CODACAN.exe ...")
    subprocess.Popen([str(CODACAN_EXE)], cwd=str(CODACAN_DIR))
    deadline = time.monotonic() + window_wait
    win = None
    while time.monotonic() < deadline:
        win = find_window()
        if win:
            break
        time.sleep(1.0)
    if not win:
        logger.error("CODACAN window '%s' did not appear within %.0fs", WINDOW_TITLE, window_wait)
        return None
    logger.info("CODACAN window up; connecting to CAN ...")
    if not connect_codacan(win):
        logger.error("Could not confirm CODACAN reached the data screen after 'Connect to CAN'")
        return None
    logger.info("Connected; warming up %.0fs for CAN RX ...", warmup)
    time.sleep(warmup)
    return win


def _on_data_screen(shot):
    """Confirm CODACAN connected: a bright-green CAN LED lights the bottom strip.

    On the splash screen both CAN LEDs are dark green (G < 120). After 'Connect to
    CAN' succeeds, CAN 1 turns bright green -- hundreds of matching pixels appear in
    the bottom-centre strip. Robust to tab-bar detection quirks.
    """
    rgb = shot.convert('RGB')
    W, H = rgb.size
    px = rgb.load()
    y0, y1 = int(H * 0.90), H
    x0, x1 = int(W * 0.35), int(W * 0.62)   # spans the CAN 2 / CAN 1 indicator LEDs
    cnt = 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            r, g, b = px[x, y]
            if g >= 120 and g > r + 40 and g > b + 20:
                cnt += 1
    return cnt > 20


def connect_codacan(win, attempts=4, diag_path=None):
    """Click 'Connect to CAN' on the splash screen; verify the data view appears."""
    import pyautogui
    shot = cc.activate_and_screenshot(win)
    if _on_data_screen(shot):
        return True  # already connected (data screen showing)
    for a in range(attempts):
        bx = win.left + int(CONNECT_BTN_REL[0] * win.width)
        by = win.top + int(CONNECT_BTN_REL[1] * win.height)
        logger.info("  clicking 'Connect to CAN' at (%d,%d) [attempt %d]", bx, by, a + 1)
        pyautogui.click(bx, by)
        time.sleep(4.0)
        shot = cc.activate_and_screenshot(win)
        if diag_path and a == 0:
            shot.save(str(diag_path))
        if _on_data_screen(shot):
            logger.info("  data screen confirmed")
            return True
    return False


def kill_codacan():
    """Terminate any running CODACAN.exe (ignore if none)."""
    subprocess.run(['taskkill', '/F', '/IM', 'CODACAN.exe'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)


def restart_codacan():
    """Close and reopen CODACAN for a clean baseline. Returns the window or None."""
    kill_codacan()
    return launch_codacan()


# ---------------------------------------------------------------------------
# Hardware / preconditions
# ---------------------------------------------------------------------------
def detect_kvaser():
    """Return the list of detected Kvaser TX interfaces (empty if none)."""
    try:
        import cowork_replay as r
        return r.detect_all_can_interfaces(BITRATE, {BRANDS})
    except Exception as e:  # noqa: BLE001
        logger.error("CAN detection failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Capture helpers (in-process, via codacan_capture)
# ---------------------------------------------------------------------------
def snapshot_tabs(layout, win, tabs, ref_size, fields=None, save_dir=None):
    """Navigate each tab, screenshot, OCR fields. Returns {tab: {field: result}}.

    If `fields` is given, only those field names are OCR'd (much faster -- use for
    targeted sweeps where only a few candidate fields matter).
    If `save_dir` is given, the raw tab screenshot is saved there (for visual
    verification when OCR of a text/enum field is unreliable).
    """
    out = {}
    for tab in tabs:
        if tab not in layout.get('tabs', {}):
            logger.warning("Tab '%s' not in layout -- skipping", tab)
            continue
        cc.navigate_to_tab(tab, layout, win)
        shot = cc.activate_and_screenshot(win)
        if save_dir is not None:
            shot.save(str(Path(save_dir) / f"shot_{tab.replace(' ', '_').replace('/', '_')}.png"))
        tab_defs = layout['tabs'][tab]
        if fields:
            sub = {'fields': {k: v for k, v in tab_defs.get('fields', {}).items() if k in fields}}
            out[tab] = cc.capture_tab_fields(shot, sub, ref_size)
        else:
            out[tab] = cc.capture_tab_fields(shot, tab_defs, ref_size)
    return out


def summarize_tabs(tab_results):
    """Return (ok_count, total_count) across all captured fields."""
    total = sum(len(fields) for fields in tab_results.values())
    ok = sum(1 for fields in tab_results.values()
             for v in fields.values() if v.get('ok'))
    return ok, total


# ---------------------------------------------------------------------------
# Replay subprocess
# ---------------------------------------------------------------------------
def build_replay_cmd(exp, state_file, dwell=None):
    """Build the cowork_replay.py argv for an experiment."""
    mode = exp['mode']
    cmd = list(PY_EXE) + [str(REPLAY_SCRIPT), mode]
    if mode != 'inject':
        cmd.append(str(exp['log']))
    common = ['--brands', BRANDS, '--bitrate', str(BITRATE),
              '--no-wait', '--state-file', str(state_file)]
    if exp.get('start_time') is not None and mode != 'inject':
        common += ['--start-time', str(exp['start_time'])]
    if exp.get('end_time') is not None and mode != 'inject':
        common += ['--end-time', str(exp['end_time'])]

    if mode == 'sweep-byte':
        cmd += ['--target', exp['target'], '--byte', str(exp['byte']),
                '--dwell', str(dwell if dwell is not None else exp.get('dwell', 3)),
                '--step', str(exp.get('step', 16))]
    elif mode in ('solo-id', 'drop-id'):
        cmd += ['--target', exp['target']]
        # bounded single pass (no --loop) so the process exits cleanly
    elif mode == 'inject':
        cmd += ['--id', exp['id'], '--data', exp['data'],
                '--interval', str(exp.get('interval', 0.1)),
                '--duration', str(exp.get('duration', 20))]
    elif mode == 'baseline':
        pass  # single pass, no --loop
    cmd += common
    return cmd


def start_replay(cmd, log_path):
    """Launch the replay subprocess, redirecting its output to log_path."""
    logf = open(log_path, 'w', encoding='utf-8')
    logf.write('CMD: ' + ' '.join(cmd) + '\n\n')
    logf.flush()
    # A script run via `py x.py` does NOT put cwd on sys.path, so cowork_replay's
    # `import canre` (repo-root package) fails. Put the repo root on PYTHONPATH.
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                            cwd=str(REPO_ROOT), env=env)
    return proc, logf


# ---------------------------------------------------------------------------
# Experiment runners
# ---------------------------------------------------------------------------
def effective_dwell(exp, n_tabs):
    """Bump dwell so SETTLE + capture completes within one step (no skipped steps).

    Capture cost per tab is ~PER_TAB_SECS for all fields, or NAV_SHOT_SECS +
    k*PER_FIELD_SECS when a 'fields' filter narrows it to k fields.
    """
    fields = exp.get('fields')
    if fields:
        per_tab = NAV_SHOT_SECS + len(fields) * PER_FIELD_SECS
    else:
        per_tab = PER_TAB_SECS
    floor = SETTLE_SECS + n_tabs * per_tab + DWELL_MARGIN
    return max(float(exp.get('dwell', 3.0)), floor)


def run_sweep(exp, layout, win, ref_size, state_file, results_dir, replay_log):
    """Run a sweep-byte experiment: subprocess sweeps, we capture each step."""
    tabs = exp['tabs']
    dwell = effective_dwell(exp, len(tabs))
    if dwell > float(exp.get('dwell', 3.0)):
        logger.info("  dwell bumped %.1fs -> %.1fs for %d tab(s) of capture",
                    float(exp.get('dwell', 3.0)), dwell, len(tabs))
    if state_file.exists():
        state_file.unlink()

    cmd = build_replay_cmd(exp, state_file, dwell=dwell)
    proc, logf = start_replay(cmd, replay_log)
    logger.info("  replay pid=%s: %s", proc.pid, ' '.join(cmd[len(PY_EXE):]))

    last_step = None
    last_status = None
    captured = 0
    try:
        while True:
            state = cc.read_state_file(state_file)
            proc_done = proc.poll() is not None

            if state and state.get('mode') == 'sweep-byte':
                status = state.get('status')
                step = state.get('step')
                if status == 'running' and step != last_step and step is not None:
                    total = state.get('total_steps', '?')
                    val = state.get('current_value_hex', state.get('current_value'))
                    logger.info("  step %s/%s value=%s -- settling %.1fs then capturing %s",
                                step, total, val, SETTLE_SECS, tabs)
                    time.sleep(SETTLE_SECS)
                    tab_results = snapshot_tabs(layout, win, tabs, ref_size, exp.get('fields'))
                    step_data = {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'mode': 'autosweep',
                        'state': state,
                        'tabs': tab_results,
                    }
                    out_path = cc._step_output_path(results_dir, state)
                    out_path.write_text(json.dumps(step_data, indent=2), encoding='utf-8')
                    captured += 1
                    last_step = step
                if status == 'done' and last_status == 'running':
                    logger.info("  sweep done -- merging %d step files", captured)
                    cc.merge_sweep_results(results_dir, state)
                    break
                last_status = status

            if proc_done and (state is None or state.get('status') == 'done'):
                if state and state.get('status') == 'done' and last_status != 'done':
                    cc.merge_sweep_results(results_dir, state)
                break
            time.sleep(POLL)
    finally:
        _reap(proc, logf)
    return {'captured_steps': captured}


def run_snapshot_mode(exp, layout, win, ref_size, state_file, results_dir, replay_log):
    """Run inject/solo-id/drop-id/baseline: hold traffic, snapshot once."""
    tabs = exp['tabs']
    settle = float(exp.get('settle', 4.0))
    if state_file.exists():
        state_file.unlink()

    cmd = build_replay_cmd(exp, state_file)
    proc, logf = start_replay(cmd, replay_log)
    logger.info("  replay pid=%s: %s", proc.pid, ' '.join(cmd[len(PY_EXE):]))

    result = {'snapshot': None}
    try:
        # Wait for frames to start flowing (status running) or the process to have run.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = cc.read_state_file(state_file)
            if state and state.get('status') in ('running', 'done'):
                break
            if proc.poll() is not None:
                break
            time.sleep(POLL)

        logger.info("  settling %.1fs then snapshotting %s", settle, tabs)
        time.sleep(settle)
        tab_results = snapshot_tabs(layout, win, tabs, ref_size, exp.get('fields'),
                                    save_dir=results_dir)
        snap = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'mode': exp['mode'],
            'experiment': exp,
            'tabs': tab_results,
        }
        out_path = results_dir / f"snapshot_{exp['name']}.json"
        out_path.write_text(json.dumps(snap, indent=2), encoding='utf-8')
        ok, total = summarize_tabs(tab_results)
        logger.info("  snapshot %s: %d/%d fields OCR-ok -> %s", exp['name'], ok, total, out_path.name)
        result['snapshot'] = str(out_path)
        result['ok'] = ok
        result['total'] = total
    finally:
        _reap(proc, logf)
    return result


def _reap(proc, logf, timeout=20):
    """Wait for a replay subprocess to exit; terminate if it overruns."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("  replay overran %ds -- terminating", timeout)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        try:
            logf.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Queue loading / validation
# ---------------------------------------------------------------------------
VALID_MODES = {'sweep-byte', 'inject', 'solo-id', 'drop-id', 'baseline'}


def load_queue(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'experiments' in data:
        data = data['experiments']
    if not isinstance(data, list):
        raise ValueError("Queue must be a JSON list (or {'experiments': [...]})")
    return data


def validate_exp(exp, idx):
    errs = []
    name = exp.get('name', f'#{idx}')
    mode = exp.get('mode')
    if mode not in VALID_MODES:
        errs.append(f"{name}: bad mode {mode!r}")
    if not exp.get('tabs'):
        errs.append(f"{name}: no tabs")
    if mode in ('sweep-byte', 'solo-id', 'drop-id', 'baseline') and not exp.get('log'):
        errs.append(f"{name}: mode {mode} needs 'log'")
    if mode in ('sweep-byte', 'solo-id', 'drop-id') and not exp.get('target'):
        errs.append(f"{name}: mode {mode} needs 'target'")
    if mode == 'sweep-byte' and exp.get('byte') is None:
        errs.append(f"{name}: sweep-byte needs 'byte'")
    if mode == 'inject' and (not exp.get('id') or not exp.get('data')):
        errs.append(f"{name}: inject needs 'id' and 'data'")
    log = exp.get('log')
    if log and not (REPO_ROOT / log).exists() and not Path(log).exists():
        errs.append(f"{name}: log not found: {log}")
    return errs


def plan_line(exp, idx):
    mode = exp.get('mode')
    tabs = ','.join(exp.get('tabs', []))
    if mode == 'sweep-byte':
        detail = f"{exp.get('target')} byte {exp.get('byte')} step {exp.get('step', 16)}"
    elif mode == 'inject':
        detail = f"{exp.get('id')} data [{exp.get('data')}]"
    elif mode in ('solo-id', 'drop-id'):
        detail = f"{exp.get('target')}"
    else:
        detail = str(exp.get('log', ''))
    return f"  [{idx}] {exp.get('name'):<28} {mode:<10} {detail}  -> tabs {tabs}"


# ---------------------------------------------------------------------------
# check / run commands
# ---------------------------------------------------------------------------
def cmd_check(args):
    ok = True
    kv = detect_kvaser()
    if kv:
        logger.info("Kvaser TX: %s", kv)
    else:
        logger.error("Kvaser TX: NONE DETECTED"); ok = False

    if args.launch_codacan:
        win = launch_codacan()
    else:
        win = find_window()
    if win:
        logger.info("CODACAN window: '%s' at (%d,%d) %dx%d",
                    win.title, win.left, win.top, win.width, win.height)
    else:
        logger.error("CODACAN window: NOT FOUND (open CODACAN.exe or pass --launch-codacan)")
        ok = False

    if LAYOUT_FILE.exists():
        layout = cc.load_layout(LAYOUT_FILE)
        ntabs = len(layout.get('tabs', {}))
        logger.info("Layout: %s (%d tabs)", LAYOUT_FILE.name, ntabs)
    else:
        logger.error("Layout missing: %s", LAYOUT_FILE); ok = False

    if args.queue:
        try:
            q = load_queue(args.queue)
            all_errs = []
            for i, exp in enumerate(q):
                all_errs += validate_exp(exp, i)
            logger.info("Queue %s: %d experiments", args.queue, len(q))
            for i, exp in enumerate(q):
                print(plan_line(exp, i))
            if all_errs:
                ok = False
                for e in all_errs:
                    logger.error("  QUEUE ERROR: %s", e)
        except Exception as e:  # noqa: BLE001
            logger.error("Queue load failed: %s", e); ok = False

    print()
    logger.info("CHECK %s", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_run(args):
    queue = load_queue(args.queue)
    all_errs = []
    for i, exp in enumerate(queue):
        all_errs += validate_exp(exp, i)
    if all_errs:
        for e in all_errs:
            logger.error("QUEUE ERROR: %s", e)
        return 1

    if args.only:
        keep = set(args.only.split(','))
        queue = [e for e in queue if e.get('name') in keep]
        logger.info("Filtered to %d experiment(s): %s", len(queue), args.only)

    print("=" * 68)
    print(f"AUTOSWEEP PLAN -- {len(queue)} experiment(s)")
    print("=" * 68)
    for i, exp in enumerate(queue):
        print(plan_line(exp, i))
    print("=" * 68)

    if args.dry_run:
        logger.info("DRY RUN -- no hardware access, no frames sent.")
        return 0

    # Preconditions for a live run
    if not detect_kvaser():
        logger.error("No Kvaser TX detected -- aborting."); return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    layout = cc.load_layout(LAYOUT_FILE)
    ref_size = layout.get('reference_size')

    # Initial CODACAN bring-up
    restart_mode = args.restart          # 'each' | 'first' | 'never'
    win = None
    if restart_mode in ('each', 'first'):
        win = restart_codacan()
    else:
        win = find_window(retries=2)
    if win is None and restart_mode == 'never':
        win = launch_codacan()
    if win is None:
        logger.error("CODACAN not available -- aborting."); return 1

    run_log = outdir / 'autosweep_run.log'
    results = []
    started = datetime.now(timezone.utc).isoformat()

    for i, exp in enumerate(queue):
        name = exp['name']
        logger.info("=" * 60)
        logger.info("[%d/%d] %s (%s)", i + 1, len(queue), name, exp['mode'])
        if exp.get('note'):
            logger.info("  note: %s", exp['note'])

        if restart_mode == 'each' and i > 0:
            win = restart_codacan()
            if win is None:
                logger.error("  CODACAN relaunch failed -- skipping %s", name)
                results.append({'name': name, 'status': 'skipped_no_codacan'})
                continue

        exp_dir = outdir / name
        exp_dir.mkdir(parents=True, exist_ok=True)
        state_file = exp_dir / 'state.json'
        replay_log = exp_dir / 'replay.log'

        try:
            if exp['mode'] == 'sweep-byte':
                r = run_sweep(exp, layout, win, ref_size, state_file, exp_dir, replay_log)
            else:
                r = run_snapshot_mode(exp, layout, win, ref_size, state_file, exp_dir, replay_log)
            results.append({'name': name, 'status': 'done', **r})
        except Exception as e:  # noqa: BLE001
            logger.exception("  experiment %s failed: %s", name, e)
            results.append({'name': name, 'status': 'error', 'error': str(e)})

    summary = {
        'started': started,
        'finished': datetime.now(timezone.utc).isoformat(),
        'queue': str(args.queue),
        'results': results,
    }
    run_log.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    logger.info("=" * 60)
    logger.info("RUN COMPLETE -- %d experiments. Summary: %s", len(queue), run_log)
    for r in results:
        logger.info("  %-28s %s", r['name'], r['status'])
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(description="Autonomous CODACAN sweep orchestrator")
    sub = p.add_subparsers(dest='command', required=True)

    pc = sub.add_parser('check', help="Validate preconditions; send no frames")
    pc.add_argument('--queue', default=None, help="Optional queue JSON to validate")
    pc.add_argument('--launch-codacan', action='store_true',
                    help="Launch CODACAN.exe if not already open")

    pr = sub.add_parser('run', help="Execute a queue JSON")
    pr.add_argument('--queue', required=True, help="Path to queue JSON")
    pr.add_argument('--outdir', default=str(DEFAULT_OUTDIR), help="Output directory")
    pr.add_argument('--dry-run', action='store_true',
                    help="Validate + print plan, no hardware access")
    pr.add_argument('--only', default=None,
                    help="Comma-separated experiment names to run (subset)")
    pr.add_argument('--restart', choices=['each', 'first', 'never'], default='each',
                    help="CODACAN restart policy (default: each experiment)")
    return p


def main():
    args = build_parser().parse_args()
    if args.command == 'check':
        return cmd_check(args)
    if args.command == 'run':
        return cmd_run(args)
    return 1


if __name__ == '__main__':
    sys.exit(main())
