// @category Analysis
// Step 0 of bytecode-VM hunt: probe whether 0x8006C000-0x8006D200 in PROG is
// really a token-threaded bytecode stream vs normal SH-4 code, and dump the
// BSRF dispatch sites at 0x8006E7B0 / 0x8006E8A6 (suspected VM dispatcher core).
//
// Outputs:
//   - Raw disassembly of 0x8006C000-0x8006D200 (PROG)
//   - Raw disassembly of 0x8006E780-0x8006E900 (around the BSRF sites)
//   - Decompile of any function containing those BSRF sites
//   - Hex byte histogram of 0x8006C000-0x8006D200 to spot token-stream regularity
//
// All output -> dlcm_export\bytecode_probe.txt

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class DlcmBytecodeProbe extends GhidraScript {

    static final String OUT = "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\bytecode_probe.txt";

    static final long BC_START = 0x8006C000L;
    static final long BC_END   = 0x8006D200L;

    static final long DISP_START = 0x8006E780L;
    static final long DISP_END   = 0x8006E900L;

    static final long BSRF_1 = 0x8006E7B0L;
    static final long BSRF_2 = 0x8006E8A6L;

    @Override
    public void run() throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();

        PrintWriter out = new PrintWriter(new FileWriter(OUT));

        out.println("============================================================");
        out.println("PHASE 0a -- Hex byte histogram of 0x" + Long.toHexString(BC_START)
            + "-0x" + Long.toHexString(BC_END));
        out.println("============================================================");
        out.println("If this region is a token stream, byte-frequency will be highly skewed");
        out.println("toward a small number of opcode bytes. If it is SH-4 code, the high");
        out.println("nibble distribution should be roughly uniform across 0x0-0xf.");
        out.println();
        int[] byteCounts = new int[256];
        int[] nibbleCounts = new int[16];
        int total = 0;
        for (long addr = BC_START; addr < BC_END; addr++) {
            try {
                int b = mem.getByte(sp.getAddress(addr)) & 0xff;
                byteCounts[b]++;
                nibbleCounts[(b >> 4) & 0xf]++;
                total++;
            } catch (Exception ex) {
                out.println("  read error at 0x" + Long.toHexString(addr) + ": " + ex.getMessage());
            }
        }
        out.println("Total bytes read: " + total);
        out.println("\nHigh-nibble distribution:");
        for (int i = 0; i < 16; i++) {
            double pct = total > 0 ? 100.0 * nibbleCounts[i] / total : 0;
            out.println(String.format("  hi-nibble 0x%x: %5d  (%.2f%%)", i, nibbleCounts[i], pct));
        }
        out.println("\nTop 16 single-byte values by frequency:");
        Integer[] idx = new Integer[256];
        for (int i = 0; i < 256; i++) idx[i] = i;
        Arrays.sort(idx, (a, b) -> Integer.compare(byteCounts[b], byteCounts[a]));
        for (int i = 0; i < 16; i++) {
            int b = idx[i];
            double pct = total > 0 ? 100.0 * byteCounts[b] / total : 0;
            out.println(String.format("  0x%02x: %5d  (%.2f%%)", b, byteCounts[b], pct));
        }

        // Also show high-nibble distribution for a known-code region for comparison
        out.println();
        out.println("--- COMPARISON: high-nibble distribution for known-code 0x80040000-0x80041000 ---");
        int[] cmpNib = new int[16];
        int cmpTotal = 0;
        for (long addr = 0x80040000L; addr < 0x80041000L; addr++) {
            try {
                int b = mem.getByte(sp.getAddress(addr)) & 0xff;
                cmpNib[(b >> 4) & 0xf]++;
                cmpTotal++;
            } catch (Exception ex) {}
        }
        for (int i = 0; i < 16; i++) {
            double pct = cmpTotal > 0 ? 100.0 * cmpNib[i] / cmpTotal : 0;
            out.println(String.format("  hi-nibble 0x%x: %5d  (%.2f%%)", i, cmpNib[i], pct));
        }

        // Try to disassemble the bytecode region if it isn't already
        out.println();
        out.println("============================================================");
        out.println("PHASE 0b -- Disassemble 0x" + Long.toHexString(BC_START)
            + "-0x" + Long.toHexString(BC_END) + " as SH-4");
        out.println("============================================================");

        Address bcStart = sp.getAddress(BC_START);
        Address bcEnd = sp.getAddress(BC_END);

        // Force disassembly across the range
        AddressSet bcSet = new AddressSet(bcStart, bcEnd);
        DisassembleCommand dis = new DisassembleCommand(bcSet, null, true);
        dis.applyTo(currentProgram, monitor);

        dumpRange(listing, fm, sp, mem, BC_START, BC_END,
                  "BYTECODE-CANDIDATE REGION 0x" + Long.toHexString(BC_START)
                      + "-0x" + Long.toHexString(BC_END), out);

        // Disassemble around BSRF sites
        out.println();
        out.println("============================================================");
        out.println("PHASE 0c -- Disassemble BSRF dispatcher region 0x"
            + Long.toHexString(DISP_START) + "-0x" + Long.toHexString(DISP_END));
        out.println("============================================================");

        Address dispStart = sp.getAddress(DISP_START);
        Address dispEnd = sp.getAddress(DISP_END);
        AddressSet dispSet = new AddressSet(dispStart, dispEnd);
        DisassembleCommand dis2 = new DisassembleCommand(dispSet, null, true);
        dis2.applyTo(currentProgram, monitor);

        dumpRange(listing, fm, sp, mem, DISP_START, DISP_END,
                  "BSRF DISPATCHER REGION 0x" + Long.toHexString(DISP_START)
                      + "-0x" + Long.toHexString(DISP_END), out);

        // Decompile any function containing the BSRF sites
        out.println();
        out.println("============================================================");
        out.println("PHASE 0d -- Decompile function(s) containing BSRF sites");
        out.println("============================================================");

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        long[] bsrfSites = { BSRF_1, BSRF_2 };
        Set<Long> seenFns = new HashSet<>();
        for (long bsrfAddr : bsrfSites) {
            Address ba = sp.getAddress(bsrfAddr);
            Function f = fm.getFunctionContaining(ba);
            if (f == null) {
                out.println("\n// No function contains BSRF @ 0x" + Long.toHexString(bsrfAddr)
                    + " -- attempting to create one at the BSRF site itself");
                CreateFunctionCmd cmd = new CreateFunctionCmd(ba);
                cmd.applyTo(currentProgram, monitor);
                f = fm.getFunctionAt(ba);
            }
            if (f == null) {
                out.println("// FAIL: could not create function at BSRF 0x"
                    + Long.toHexString(bsrfAddr));
                continue;
            }
            long fEntry = f.getEntryPoint().getOffset();
            if (seenFns.contains(fEntry)) continue;
            seenFns.add(fEntry);

            long sz = f.getBody().getMaxAddress().getOffset()
                    - f.getBody().getMinAddress().getOffset() + 1;
            out.println();
            out.println("// --- " + f.getName() + " @ 0x" + Long.toHexString(fEntry)
                + "  body=" + sz + " bytes  (contains BSRF @ 0x"
                + Long.toHexString(bsrfAddr) + ") ---");
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("// FAIL: " + (res != null ? res.getErrorMessage() : "null"));
            }
        }

        decomp.dispose();
        out.flush();
        out.close();
        println("Wrote bytecode probe -> " + OUT);
    }

    void dumpRange(Listing listing, FunctionManager fm, AddressSpace sp,
                   Memory mem, long startVa, long endVa, String header, PrintWriter out) {
        out.println();
        out.println(header);
        out.println("------------------------------------------------------------");

        Address curr = sp.getAddress(startVa);
        Address end = sp.getAddress(endVa);
        String lastFn = "";
        int instrCount = 0;
        int dataCount = 0;

        while (curr.compareTo(end) < 0) {
            Function f = fm.getFunctionAt(curr);
            if (f != null && !f.getName().equals(lastFn)) {
                long sz = f.getBody().getMaxAddress().getOffset()
                        - f.getBody().getMinAddress().getOffset() + 1;
                out.println();
                out.println("  ;; --- " + f.getName() + "  body=" + sz + " bytes ---");
                lastFn = f.getName();
            }

            Instruction instr = listing.getInstructionAt(curr);
            if (instr != null) {
                instrCount++;
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  0x%08X  ", curr.getOffset()));
                int len = instr.getLength();
                byte[] bytes = new byte[len];
                try { instr.getBytesInCodeUnit(bytes, 0); } catch (Exception ex) {}
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                sb.append("  ");
                sb.append(instr.toString());
                out.println(sb.toString());
                try { curr = curr.add(instr.getLength()); } catch (Exception e) { break; }
            } else {
                dataCount++;
                int sz = 2;
                byte[] bytes = new byte[sz];
                try {
                    for (int i = 0; i < sz; i++) {
                        bytes[i] = (byte) mem.getByte(curr.add(i));
                    }
                } catch (Exception ex) {}
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  0x%08X  [data] ", curr.getOffset()));
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                out.println(sb.toString());
                try { curr = curr.add(sz); } catch (Exception e) { break; }
            }
        }
        out.println();
        out.println("  Range stats: " + instrCount + " instructions, " + dataCount
            + " un-disassemblable 2-byte slots");
    }
}
