// @category Analysis
// HVAC step 1a: test hypothesis H1 (S12X, global map) on the packed image, with checks
// that can fail. See projects/coda/notes/hvac/coda-hvac-decompile-notes.md section 3.
//
//  1. Sets PPAGE over each flashed page so in-window (0x8000-0xBFFF) operands resolve.
//  2. Reads the 120 words at 0x7FEE10-0x7FEEFF (seg2, H2: relocated vector table),
//     translates each as an S12X local address, and disassembles from every distinct
//     target that lies in flashed bytes.
//  3. Iterates: every CALL (opcode 0x4A, extended form: 4A hh ll pg) found in decoded
//     code is a further seed. Its page byte is the test: under H1 it must name a page that
//     was flashed, and its target must land in flashed bytes.
//  4. Reports instruction count, bad-instruction bookmarks, vector targets that decode vs
//     fail, and the CALL page histogram.
//
// Args: <outpath> <flashed ranges as lo-hi,lo-hi,... (global hex)>
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import java.io.*;
import java.math.BigInteger;
import java.util.*;

public class HvacMapCheck extends GhidraScript {

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

        Register ppage = currentProgram.getRegister("PPAGE");
        out.println("PPAGE register: " + ppage);
        if (ppage != null) {
            for (int pg = 0xE0; pg <= 0xFF; pg++) {
                long lo = 0x400000L | ((long) pg << 14);
                try {
                    currentProgram.getProgramContext().setValue(ppage, toAddr(lo), toAddr(lo + 0x3FFF),
                            BigInteger.valueOf(pg));
                } catch (Exception e) {
                    out.println("  set PPAGE " + Integer.toHexString(pg) + " failed: " + e);
                }
            }
        }

        out.println("\n=== vector table words 0x7FEE10-0x7FEEFF ===");
        Map<Long, List<Integer>> targets = new TreeMap<>();
        int fill = 0;
        for (int i = 0; i < 120; i++) {
            long va = 0x7FEE10L + 2 * i;
            int w = (mem.getShort(toAddr(va)) & 0xFFFF);
            long g = toGlobal(w, 0xFF);
            targets.computeIfAbsent(g, k -> new ArrayList<>()).add(i);
        }
        Deque<Long> seeds = new ArrayDeque<>();
        int vecFlashed = 0, vecUnflashed = 0;
        for (Map.Entry<Long, List<Integer>> e : targets.entrySet()) {
            long g = e.getKey();
            boolean f = g >= 0 && isFlashed(g);
            out.printf("  target %06X  flashed=%s  used by %d vector slot(s) %s%n", g, f, e.getValue().size(),
                    e.getValue().size() > 6 ? e.getValue().subList(0, 6) + "..." : e.getValue());
            if (f) { vecFlashed++; seeds.add(g); } else vecUnflashed++;
        }
        out.printf("  distinct targets: %d flashed, %d not%n", vecFlashed, vecUnflashed);

        Set<Long> seen = new HashSet<>();
        Map<Long, String> seedResult = new TreeMap<>();
        Map<Integer, Integer> callPages = new TreeMap<>();
        int callTotal = 0, callBad = 0;
        List<String> badCalls = new ArrayList<>();
        int round = 0;
        while (!seeds.isEmpty()) {
            round++;
            List<Long> batch = new ArrayList<>(seeds);
            seeds.clear();
            for (long g : batch) {
                if (!seen.add(g)) continue;
                Address at = toAddr(g);
                if (listing.getInstructionAt(at) == null) {
                    DisassembleCommand cmd = new DisassembleCommand(at, null, true);
                    cmd.applyTo(currentProgram, monitor);
                }
                Instruction ins = listing.getInstructionAt(at);
                seedResult.put(g, ins == null ? "NO-DECODE" : ins.toString());
            }
            InstructionIterator it = listing.getInstructions(true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                byte[] b = ins.getBytes();
                if ((b[0] & 0xFF) != 0x4A || b.length < 4) continue;
                int local = ((b[1] & 0xFF) << 8) | (b[2] & 0xFF);
                int pg = b[3] & 0xFF;
                long g = toGlobal(local, pg);
                if (seen.contains(g) && round > 1) continue;
                if (round == 1 || !seen.contains(g)) {
                    if (g >= 0 && isFlashed(g)) seeds.add(g);
                }
            }
            if (round > 50) break;
        }

        InstructionIterator it = listing.getInstructions(true);
        int nIns = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            nIns++;
            byte[] b = ins.getBytes();
            if ((b[0] & 0xFF) != 0x4A || b.length < 4) continue;
            int local = ((b[1] & 0xFF) << 8) | (b[2] & 0xFF);
            int pg = b[3] & 0xFF;
            long g = toGlobal(local, pg);
            callTotal++;
            callPages.merge(pg, 1, Integer::sum);
            boolean ok = g >= 0 && isFlashed(g) && listing.getInstructionAt(toAddr(g)) != null;
            if (!ok) {
                callBad++;
                if (badCalls.size() < 30) badCalls.add(String.format("  %s  %s  -> %06X flashed=%s",
                        ins.getAddress(), ins, g, g >= 0 && isFlashed(g)));
            }
        }
        int bad = currentProgram.getBookmarkManager().getBookmarkCount("Error");

        out.println("\n=== seeds (vector targets and CALL targets) ===");
        int noDecode = 0;
        for (Map.Entry<Long, String> e : seedResult.entrySet()) {
            if (e.getValue().equals("NO-DECODE")) noDecode++;
        }
        out.printf("  seeds: %d, failed to decode at entry: %d%n", seedResult.size(), noDecode);
        for (Map.Entry<Long, String> e : seedResult.entrySet())
            if (e.getValue().equals("NO-DECODE")) out.printf("    NO-DECODE %06X%n", e.getKey());

        out.println("\n=== totals ===");
        out.println("  instructions decoded: " + nIns);
        out.println("  error bookmarks (bad instruction etc.): " + bad);
        out.println("  CALL ext instructions: " + callTotal + ", target not flashed or not an instruction start: " + callBad);
        out.println("  CALL page histogram:");
        for (Map.Entry<Integer, Integer> e : callPages.entrySet())
            out.printf("    page %02X: %d%n", e.getKey(), e.getValue());
        out.println("  failing CALLs (first 30):");
        for (String s : badCalls) out.println(s);

        out.println("\n=== error bookmarks (first 40) ===");
        Iterator<Bookmark> bi = currentProgram.getBookmarkManager().getBookmarksIterator("Error");
        int k = 0;
        while (bi.hasNext() && k < 40) {
            Bookmark bm = bi.next();
            out.printf("  %s  %s  %s%n", bm.getAddress(), bm.getCategory(), bm.getComment());
            k++;
        }
        out.flush();
        out.close();
        println("HvacMapCheck: " + nIns + " instructions, " + bad + " errors -> " + a[0]);
    }
}
