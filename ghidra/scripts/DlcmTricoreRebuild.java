// DlcmTricoreRebuild.java
// Rebuild the DLCM TriCore analysis from a complete set of seeds.
//
// The earlier TriCore project was seeded from about a dozen hand-picked
// addresses and reached ~35k instructions of an estimated ~115k. This script
// finds every intra-image call/branch target by scanning the raw bytes for
// TriCore B-format instructions, seeds a function at each, then lets Ghidra's
// analyzers run and reports coverage.
//
// TriCore B format (32-bit, little-endian):
//   op8 = W & 0xFF                     0x6D = CALL, 0x1D = J
//   disp24 = ((W >> 16) & 0xFFFF) | (((W >> 8) & 0xFF) << 16)
//   target = PC + sign_extend(disp24, 24) * 2
//
// TriCore SB format (16-bit, little-endian):
//   op8 = B0                           0x5C = CALL
//   target = PC + sign_extend(disp8, 8) * 2
// The 16-bit CALL was missed by every earlier scan (2026-09-19). It accounts
// for 454 sites, and the gradient limiter FUN_80075DFA is reached only by one,
// so it was never in the seed set. disp8 == 0 (a call to itself) is treated as
// a decode false positive and dropped.
//
// Args: <outpath>
//
// Run: analyzeHeadless ~/ghidra-projects dlcm_tricore \
//        -process coda_dlcm_prog.bin -noanalysis \
//        -postScript DlcmTricoreRebuild.java <out> \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class DlcmTricoreRebuild extends GhidraScript {

    // Active code region; everything above CONTENT_END is a single zero run.
    static final long BASE = 0x80040000L;
    static final long CONTENT_END = 0x80095CB2L;

    @Override
    public void run() throws Exception {
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/tricore_rebuild.txt";
        String[] args = getScriptArgs();
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];

        PrintWriter out = new PrintWriter(new FileWriter(outPath));
        Memory mem = currentProgram.getMemory();
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        AddressSpace as = currentProgram.getAddressFactory().getDefaultAddressSpace();

        out.println("=== DLCM TriCore rebuild ===");
        out.println("language : " + currentProgram.getLanguageID());
        out.printf("region   : 0x%08X - 0x%08X  (%d bytes)%n",
                BASE, CONTENT_END, CONTENT_END - BASE);

        int len = (int) (CONTENT_END - BASE);
        byte[] img = new byte[len];
        mem.getBytes(as.getAddress(Long.toHexString(BASE)), img);

        // 1. Harvest every intra-image call and jump target.
        TreeSet<Long> callTargets = new TreeSet<>();
        TreeSet<Long> jumpTargets = new TreeSet<>();
        int n32 = 0, n16 = 0;
        for (int off = 0; off + 4 <= len; off += 2) {
            int op = img[off] & 0xFF;
            if (op == 0x5C) {                         // 16-bit CALL, SB format
                long disp8 = img[off + 1] & 0xFF;
                if (disp8 == 0) continue;             // call to self: false positive
                if ((disp8 & 0x80) != 0) disp8 -= 0x100L;
                long t16 = (BASE + off) + disp8 * 2;
                if (t16 < BASE || t16 >= CONTENT_END || (t16 & 1) != 0) continue;
                callTargets.add(t16);
                n16++;
                continue;
            }
            if (op != 0x6D && op != 0x1D) continue;
            long W = ((long) (img[off] & 0xFF))
                    | ((long) (img[off + 1] & 0xFF) << 8)
                    | ((long) (img[off + 2] & 0xFF) << 16)
                    | ((long) (img[off + 3] & 0xFF) << 24);
            long disp = ((W >> 16) & 0xFFFF) | (((W >> 8) & 0xFF) << 16);
            if ((disp & 0x800000) != 0) disp -= 0x1000000L;
            long tgt = (BASE + off) + disp * 2;
            if (tgt < BASE || tgt >= CONTENT_END || (tgt & 1) != 0) continue;
            if (op == 0x6D) { callTargets.add(tgt); n32++; } else jumpTargets.add(tgt);
        }
        out.printf("call sites: %d 32-bit (op 0x6D), %d 16-bit (op 0x5C)%n", n32, n16);
        out.printf("call targets (both widths): %d%n", callTargets.size());
        out.printf("jump targets (op 0x1D): %d%n", jumpTargets.size());

        // 2. Seed a function at every call target. Jump targets are usually
        //    intra-function labels, so they are disassembled but not promoted.
        int created = 0, existed = 0, failed = 0;
        for (Long t : callTargets) {
            Address a = as.getAddress(Long.toHexString(t));
            if (fm.getFunctionAt(a) != null) { existed++; continue; }
            if (listing.getInstructionAt(a) == null) {
                try { disassemble(a); } catch (Exception e) { /* keep going */ }
            }
            Function f = null;
            try { f = createFunction(a, null); } catch (Exception e) { /* keep going */ }
            if (f != null) created++; else failed++;
        }
        out.printf("functions: %d created, %d already present, %d failed%n",
                created, existed, failed);

        for (Long t : jumpTargets) {
            Address a = as.getAddress(Long.toHexString(t));
            if (listing.getInstructionAt(a) == null) {
                try { disassemble(a); } catch (Exception e) { /* keep going */ }
            }
        }

        // 3. Let the analyzers propagate from the seeds.
        out.println("running analyzers...");
        analyzeAll(currentProgram);

        // 4. Coverage report.
        long insnBytes = 0;
        int insnCount = 0;
        InstructionIterator it = listing.getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            insnCount++;
            insnBytes += ins.getLength();
        }
        int fnCount = 0;
        long fnBytes = 0;
        FunctionIterator fi = fm.getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next();
            fnCount++;
            fnBytes += f.getBody().getNumAddresses();
        }
        out.println();
        out.println("=== COVERAGE ===");
        out.printf("instructions      : %d  (%d bytes, %.1f%% of region)%n",
                insnCount, insnBytes, 100.0 * insnBytes / len);
        out.printf("functions         : %d  (%d bytes in bodies, %.1f%% of region)%n",
                fnCount, fnBytes, 100.0 * fnBytes / len);
        out.printf("call targets seeded: %d of %d resolved to a function%n",
                countResolved(fm, as, callTargets), callTargets.size());

        // 5. Largest undisassembled stretches -- likely data tables, worth knowing.
        out.println();
        out.println("=== LARGEST UNDISASSEMBLED RUNS (candidate data regions) ===");
        List<long[]> gaps = new ArrayList<>();
        long runStart = -1;
        for (long a = BASE; a < CONTENT_END; a += 2) {
            Address ad = as.getAddress(Long.toHexString(a));
            boolean isCode = listing.getInstructionContaining(ad) != null;
            if (!isCode && runStart < 0) runStart = a;
            if (isCode && runStart >= 0) { gaps.add(new long[]{runStart, a - runStart}); runStart = -1; }
        }
        if (runStart >= 0) gaps.add(new long[]{runStart, CONTENT_END - runStart});
        gaps.sort((x, y) -> Long.compare(y[1], x[1]));
        for (int i = 0; i < Math.min(20, gaps.size()); i++) {
            out.printf("  0x%08X  %6d bytes%n", gaps.get(i)[0], gaps.get(i)[1]);
        }
        long gapTotal = 0;
        for (long[] g : gaps) gapTotal += g[1];
        out.printf("total undisassembled: %d bytes (%.1f%%) in %d runs%n",
                gapTotal, 100.0 * gapTotal / len, gaps.size());

        out.flush();
        out.close();
        println("Done -> " + outPath + "  (" + fnCount + " functions, "
                + insnCount + " instructions)");
    }

    int countResolved(FunctionManager fm, AddressSpace as, Collection<Long> targets)
            throws Exception {
        int n = 0;
        for (Long t : targets) {
            if (fm.getFunctionAt(as.getAddress(Long.toHexString(t))) != null) n++;
        }
        return n;
    }
}
