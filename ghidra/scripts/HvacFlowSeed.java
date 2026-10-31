// @category Analysis
// HVAC (S12X, HCS-12X:BE:24) flow recovery. Run on the coda_hvac project after import,
// and again whenever new code is found. Idempotent; iterates to a fixed point.
//
// Why: Ghidra's stock HCS12 SLEIGH encodes JMP/JSR/CALL extended as `goto [opr16a]` /
// `call [opr16a]`, a computed target, so the disassembler never follows them and a fresh
// import decodes only the reset stub. This script computes those targets itself, under
// the S12X local -> global map, and adds them as flow references:
//   06 hh ll      JMP  ext     -> local hhll (window 0x8000-0xBFFF uses the page of the instruction)
//   16 hh ll      JSR  ext     -> same
//   4A hh ll pg   CALL ext     -> page pg, local hhll
// It also seeds every word of the relocated vector table (0x7FEE10-0x7FEEFF), sets the
// PPAGE context over each page, creates functions at call targets, and runs Ghidra's
// auto-analysis between rounds.
//
// Switch helpers (compiler runtime, page FF). A JSR to one of these never returns to
// the next byte: an inline table follows it. Each JSR site gets flow override BRANCH, the
// table is cleared of any code decoded over it, its targets become COMPUTED_JUMP
// references and seeds, and a decompiler JumpTable override is written. Formats, read
// from the helpers' code (notes file, step 1a); ret = address after the JSR:
//   0xCAEF  [N:u16][default:addr16][addr16 x N]     absolute local, D = selector
//   0xCAFA  [N:u8][dflt:u8][off:u8 x N]             target = ret + 2 + off, B = selector
//   0xCB0E  [max:u8][default:addr16]([key:u8][addr16])* up to key == max, sorted
//
// Targets in unflashed (0xFF-filled) bytes are counted and listed, never disassembled.
//
// Args: <outpath> <flashed ranges lo-hi,lo-hi,... (global hex)>
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.plugin.core.clear.ClearFlowAndRepairCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.pcode.JumpTable;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.math.BigInteger;
import java.util.*;

public class HvacFlowSeed extends GhidraScript {

    long[][] flashed;

    boolean isFlashed(long g) {
        for (long[] r : flashed) if (g >= r[0] && g <= r[1]) return true;
        return false;
    }

    static long toGlobal(int local, int page) {
        if (local >= 0x8000 && local < 0xC000) return 0x400000L | ((long) page << 14) | (local & 0x3FFF);
        if (local >= 0xC000) return 0x7FC000L | (local & 0x3FFF);
        if (local >= 0x4000) return 0x7F4000L | (local & 0x3FFF);
        return -1;
    }

    static int pageOf(long g) {
        return (int) ((g >> 14) & 0xFF);
    }

    static final long SW_WORD = 0x7FCAEFL, SW_BYTEOFF = 0x7FCAFAL, SW_SPARSE = 0x7FCB0EL;

    int u8(Memory m, long g) throws Exception { return m.getByte(toAddr(g)) & 0xFF; }
    int u16(Memory m, long g) throws Exception { return m.getShort(toAddr(g)) & 0xFFFF; }

    /** Returns {tableLength, target...} for the switch at JSR site `site` calling helper `h`. */
    long[] parseSwitch(Memory m, long h, long ret, int page) throws Exception {
        List<Long> t = new ArrayList<>();
        int len;
        if (h == SW_WORD) {
            int n = u16(m, ret);
            t.add(toGlobal(u16(m, ret + 2), page));
            for (int i = 0; i < n; i++) t.add(toGlobal(u16(m, ret + 4 + 2 * i), page));
            len = 4 + 2 * n;
        } else if (h == SW_BYTEOFF) {
            int n = u8(m, ret);
            t.add(ret + 2 + u8(m, ret + 1));
            for (int i = 0; i < n; i++) t.add(ret + 2 + u8(m, ret + 2 + i));
            len = 2 + n;
        } else {
            int max = u8(m, ret);
            t.add(toGlobal(u16(m, ret + 1), page));
            long p = ret + 3;
            int guard = 0;
            while (guard++ < 256) {
                int key = u8(m, p);
                t.add(toGlobal(u16(m, p + 1), page));
                p += 3;
                if (key == max) break;
            }
            len = (int) (p - ret);
        }
        long[] r = new long[t.size() + 1];
        r[0] = len;
        for (int i = 0; i < t.size(); i++) r[i + 1] = t.get(i);
        return r;
    }

    int scrubbed = 0, fixedWindowRefs = 0;
    Set<Long> bogus = new TreeSet<>();

    /**
     * Ghidra's constant propagator resolves 0x8000-0xBFFF operands with the pspec's tracked
     * PPAGE (0xFE), ignoring the per-page value stored in the program context (PPAGE is a
     * RAM-space byte, not a register). For code in a banked page P other than FE, move
     * every non-user reference into the FE window onto page P. CALL (explicit page) and
     * G-prefixed global instructions are left alone. Returns the number of refs moved.
     */
    int scrubWindowRefs(Listing listing, ReferenceManager refs) throws Exception {
        int moved = 0;
        AddressSet banked = new AddressSet(toAddr(0x780000L), toAddr(0x7F3FFFL));
        InstructionIterator it = listing.getInstructions(banked, true);
        List<Address> sites = new ArrayList<>();
        while (it.hasNext()) sites.add(it.next().getAddress());
        for (Address at : sites) {
            Instruction ins = listing.getInstructionAt(at);
            if (ins == null) continue;
            int op = ins.getByte(0) & 0xFF;
            if (op == 0x4A || op == 0x4B || ins.getMnemonicString().startsWith("G")) continue;
            int page = pageOf(at.getOffset());
            for (Reference r : refs.getReferencesFrom(at)) {
                long to = r.getToAddress().getOffset();
                if (r.getSource() == SourceType.USER_DEFINED || to < 0x7F8000L || to > 0x7FBFFFL) continue;
                long fix = 0x400000L | ((long) page << 14) | (to & 0x3FFF);
                refs.delete(r);
                if (isFlashed(fix))
                    refs.addMemoryReference(at, toAddr(fix), r.getReferenceType(), SourceType.USER_DEFINED, r.getOperandIndex());
                if (r.getReferenceType().isFlow()) bogus.add(to);
                moved++;
            }
        }
        return moved;
    }

    /** Clear code seeded only through a scrubbed reference, then re-decode the holes. */
    void clearBogus(Listing listing, ReferenceManager refs, FunctionManager fm, PrintWriter out) throws Exception {
        for (long w : bogus) {
            Address at = toAddr(w);
            if (refs.getReferenceCountTo(at) > 0) {
                out.printf("  bogus target %06X kept: still referenced%n", w);
                continue;
            }
            // Fall-through is not a reference: code reached by falling off the instruction
            // before it is real even when the scrubbed ref was the only ref to it. Clearing
            // it cut 7FA371-7FA6DD (the tail of 7FA1D5) out of the 2026-10-26 build.
            Instruction prev = listing.getInstructionBefore(at);
            if (prev != null && at.equals(prev.getFallThrough())) {
                out.printf("  bogus target %06X kept: fall-through from %s%n", w, prev.getAddress());
                continue;
            }
            Function f = fm.getFunctionAt(at);
            if (f != null) fm.removeFunction(at);
            if (listing.getInstructionAt(at) != null)
                new ClearFlowAndRepairCmd(at, true, false, false).applyTo(currentProgram, monitor);
            out.printf("  bogus target %06X cleared%n", w);
        }
        bogus.clear();
        BookmarkManager bm = currentProgram.getBookmarkManager();
        List<Bookmark> errs = new ArrayList<>();
        Iterator<Bookmark> bi = bm.getBookmarksIterator("Error");
        while (bi.hasNext()) errs.add(bi.next());
        for (Bookmark b : errs) {
            Address at = b.getAddress();
            bm.removeBookmark(b);
            if (listing.getCodeUnitAt(at) instanceof Data && ((Data) listing.getCodeUnitAt(at)).isDefined()) continue;
            if (listing.getInstructionContaining(at) == null && isFlashed(at.getOffset())
                    && !inSwitchTable(at.getOffset()))
                new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor);
        }
    }

    List<long[]> tables = new ArrayList<>();

    boolean inSwitchTable(long g) {
        for (long[] t : tables) if (g >= t[0] && g < t[0] + t[1]) return true;
        return false;
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        List<long[]> rs = new ArrayList<>();
        for (String s : a[1].split(",")) {
            String[] p = s.split("-");
            rs.add(new long[]{Long.parseLong(p[0], 16), Long.parseLong(p[1], 16)});
        }
        flashed = rs.toArray(new long[0][]);
        Memory mem = currentProgram.getMemory();
        Listing listing = currentProgram.getListing();
        ReferenceManager refs = currentProgram.getReferenceManager();
        FunctionManager fm = currentProgram.getFunctionManager();

        Register ppage = currentProgram.getRegister("PPAGE");
        for (int pg = 0xE0; pg <= 0xFF; pg++) {
            long lo = 0x400000L | ((long) pg << 14);
            currentProgram.getProgramContext().setValue(ppage, toAddr(lo), toAddr(lo + 0x3FFF), BigInteger.valueOf(pg));
        }

        Set<Long> jumpSeeds = new TreeSet<>(), callSeeds = new TreeSet<>();
        for (int i = 0; i < 120; i++) {
            Address va = toAddr(0x7FEE10L + 2 * i);
            int w = mem.getShort(va) & 0xFFFF;
            long g = toGlobal(w, 0xFF);
            if (g >= 0 && isFlashed(g)) {
                callSeeds.add(g);
                refs.addMemoryReference(va, toAddr(g), RefType.DATA, SourceType.USER_DEFINED, 0);
            }
        }

        for (long h : new long[]{SW_WORD, SW_BYTEOFF, SW_SPARSE}) {
            Address at = toAddr(h);
            if (listing.getInstructionAt(at) == null)
                new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor);
            if (fm.getFunctionAt(at) == null) new CreateFunctionCmd(at).applyTo(currentProgram, monitor);
            Function f = fm.getFunctionAt(at);
            if (f != null) f.setNoReturn(true);
        }
        Map<Long, List<Address>> switches = new TreeMap<>();
        List<String> switchLog = new ArrayList<>();
        Map<String, Integer> unflashedTargets = new TreeMap<>();
        int round = 0, added;
        do {
            round++;
            for (long g : callSeeds) {
                Address at = toAddr(g);
                if (listing.getInstructionAt(at) == null)
                    new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor);
                if (fm.getFunctionAt(at) == null && listing.getInstructionAt(at) != null)
                    new CreateFunctionCmd(at).applyTo(currentProgram, monitor);
            }
            for (long g : jumpSeeds) {
                Address at = toAddr(g);
                if (listing.getInstructionAt(at) == null)
                    new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor);
            }
            added = 0;
            InstructionIterator it = listing.getInstructions(true);
            List<Address> all = new ArrayList<>();
            while (it.hasNext()) all.add(it.next().getAddress());
            for (Address insAt : all) {
                Instruction ins = listing.getInstructionAt(insAt);
                if (ins == null) continue;
                byte[] b = ins.getBytes();
                int op = b[0] & 0xFF;
                if (!((op == 0x06 || op == 0x16) && b.length == 3) && !(op == 0x4A && b.length == 4)) continue;
                int local = ((b[1] & 0xFF) << 8) | (b[2] & 0xFF);
                int pg = op == 0x4A ? (b[3] & 0xFF) : pageOf(ins.getAddress().getOffset());
                long g = toGlobal(local, pg);
                if (g < 0 || !isFlashed(g)) {
                    unflashedTargets.merge(String.format("%s %s", ins.toString(), g < 0 ? "(non-flash)" : String.format("%06X", g)), 1, Integer::sum);
                    continue;
                }
                if (op == 0x16 && (g == SW_WORD || g == SW_BYTEOFF || g == SW_SPARSE)) {
                    long site = ins.getAddress().getOffset();
                    if (switches.containsKey(site)) continue;
                    long ret = site + 3;
                    long[] sw = parseSwitch(mem, g, ret, pageOf(site));
                    ins.setFlowOverride(FlowOverride.BRANCH);
                    Address tEnd = toAddr(ret + sw[0] - 1);
                    Instruction over = listing.getInstructionContaining(toAddr(ret));
                    if (over != null || listing.getInstructions(new AddressSet(toAddr(ret), tEnd), true).hasNext()) {
                        new ClearFlowAndRepairCmd(toAddr(ret), true, false, false).applyTo(currentProgram, monitor);
                        listing.clearCodeUnits(toAddr(ret), tEnd, false);
                    }
                    List<Address> dests = new ArrayList<>();
                    int bad = 0;
                    for (int i = 1; i < sw.length; i++) {
                        if (sw[i] < 0 || !isFlashed(sw[i])) { bad++; continue; }
                        Address d = toAddr(sw[i]);
                        if (!dests.contains(d)) dests.add(d);
                        ins.addOperandReference(0, d, RefType.COMPUTED_JUMP, SourceType.USER_DEFINED);
                        if (jumpSeeds.add(sw[i])) added++;
                    }
                    switches.put(site, dests);
                    tables.add(new long[]{ret, sw[0]});
                    switchLog.add(String.format("  %06X  helper %06X  table %06X+%d  cases %d  distinct dests %d  unflashed %d",
                            site, g, ret, sw[0], sw.length - 1, dests.size(), bad));
                    continue;
                }
                boolean isCall = op != 0x06;
                RefType rt = isCall ? RefType.UNCONDITIONAL_CALL : RefType.UNCONDITIONAL_JUMP;
                Address to = toAddr(g);
                boolean has = false;
                for (Reference r : refs.getReferencesFrom(ins.getAddress()))
                    if (r.getToAddress().equals(to)) has = true;
                if (!has) {
                    refs.addMemoryReference(ins.getAddress(), to, rt, SourceType.USER_DEFINED, 0);
                    if (!isCall) ins.setFlowOverride(FlowOverride.NONE);
                }
                if ((isCall ? callSeeds : jumpSeeds).add(g)) added++;
            }
            analyzeChanges(currentProgram);
            int moved = scrubWindowRefs(listing, refs);
            scrubbed += moved;
            clearBogus(listing, refs, fm, out);
            analyzeChanges(currentProgram);
            out.printf("round %d: %d new targets, %d window refs moved to own page, %d instructions, %d functions%n",
                    round, added, moved, listing.getNumInstructions(), fm.getFunctionCount());
            if (moved > 0) added++;
        } while (added > 0 && round < 60);
        int left = scrubWindowRefs(listing, refs);
        out.printf("window refs moved in total: %d (final pass found %d more)%n", scrubbed, left);

        int amb = 0;
        InstructionIterator fx = listing.getInstructions(new AddressSet(toAddr(0x7F4000L), toAddr(0x7FFFFFL)), true);
        while (fx.hasNext()) {
            Instruction ins = fx.next();
            if (pageOf(ins.getAddress().getOffset()) == 0xFE) continue;
            for (Reference r : refs.getReferencesFrom(ins.getAddress())) {
                long to = r.getToAddress().getOffset();
                if (r.getSource() != SourceType.USER_DEFINED && to >= 0x7F8000L && to <= 0x7FBFFFL) amb++;
            }
        }
        out.printf("window refs from fixed-page code (PPAGE at runtime unknown; left as page FE, unverified): %d%n", amb);

        FunctionIterator fi = fm.getFunctions(true);
        List<Function> fl = new ArrayList<>();
        while (fi.hasNext()) fl.add(fi.next());
        for (Function f : fl) CreateFunctionCmd.fixupFunctionBody(currentProgram, f, monitor);
        int ovr = 0;
        List<String> orphanSwitch = new ArrayList<>();
        for (Map.Entry<Long, List<Address>> e : switches.entrySet()) {
            if (fm.getFunctionContaining(toAddr(e.getKey())) == null)
                orphanSwitch.add(String.format("%06X", e.getKey()));
            Address site = toAddr(e.getKey());
            Function f = fm.getFunctionContaining(site);
            if (f == null || e.getValue().isEmpty()) continue;
            new JumpTable(site, new ArrayList<>(e.getValue()), true).writeOverride(f);
            CreateFunctionCmd.fixupFunctionBody(currentProgram, f, monitor);
            ovr++;
        }
        out.printf("%nswitch sites: %d (jumptable overrides written: %d; not inside any function: %s)%n",
                switches.size(), ovr, orphanSwitch);
        for (String l : switchLog) out.println(l);

        long covered = 0, total = 0;
        for (long[] r : flashed) {
            total += r[1] - r[0] + 1;
            AddressSet s = new AddressSet(toAddr(r[0]), toAddr(r[1]));
            InstructionIterator it = listing.getInstructions(s, true);
            while (it.hasNext()) covered += it.next().getLength();
        }
        int errs = currentProgram.getBookmarkManager().getBookmarkCount("Error");
        out.printf("%nflashed bytes covered by instructions: %d of %d (%.1f %%)%n", covered, total, 100.0 * covered / total);
        out.println("error bookmarks: " + errs);
        Iterator<Bookmark> bi = currentProgram.getBookmarkManager().getBookmarksIterator("Error");
        int k = 0;
        while (bi.hasNext() && k++ < 40) {
            Bookmark bm = bi.next();
            out.printf("  %s  %s%n", bm.getAddress(), bm.getComment());
        }
        out.println("\nJMP/JSR/CALL ext targets outside flashed bytes:");
        for (Map.Entry<String, Integer> e : unflashedTargets.entrySet())
            out.printf("  x%-4d %s%n", e.getValue(), e.getKey());

        out.println("\nper-segment coverage:");
        for (long[] r : flashed) {
            long c = 0;
            InstructionIterator it = listing.getInstructions(new AddressSet(toAddr(r[0]), toAddr(r[1])), true);
            while (it.hasNext()) c += it.next().getLength();
            out.printf("  %06X-%06X  %6d of %6d (%.1f %%)%n", r[0], r[1], c, r[1] - r[0] + 1, 100.0 * c / (r[1] - r[0] + 1));
        }
        out.close();
        println("HvacFlowSeed: " + listing.getNumInstructions() + " instructions, " + fm.getFunctionCount()
                + " functions, " + errs + " errors -> " + a[0]);
    }
}
