// Ghidra post-analysis script: export function list and cross-refs near gap zone
// Run via analyzeHeadless -postScript

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class dlcm_analysis_export extends GhidraScript {

    @Override
    public void run() throws Exception {
        String outDir = System.getProperty("ghidra.export.dir", "%LOCALAPPDATA%/ghidra-projects/dlcm_export");
        new File(outDir).mkdirs();

        exportFunctions(outDir + "/functions.txt");
        exportGapContext(outDir + "/gap_context.txt");
        exportMemoryMap(outDir + "/memory_map.txt");
        println("Export complete -> " + outDir);
    }

    void exportFunctions(String path) throws Exception {
        FunctionManager fm = currentProgram.getFunctionManager();
        FunctionIterator fi = fm.getFunctions(true);
        PrintWriter pw = new PrintWriter(new FileWriter(path));
        pw.println("# Functions found by Ghidra auto-analysis");
        pw.println("# addr_start  addr_end  size  name");
        int count = 0;
        while (fi.hasNext()) {
            Function f = fi.next();
            long start = f.getEntryPoint().getOffset();
            long end   = f.getBody().getMaxAddress().getOffset();
            long size  = end - start + 1;
            pw.printf("0x%08X  0x%08X  %6d  %s%n", start, end, size, f.getName());
            count++;
        }
        pw.close();
        println("Wrote " + count + " functions to " + path);
    }

    void exportGapContext(String path) throws Exception {
        long GAP_START = 0x8006A738L;
        long GAP_END   = 0x8006CCA0L;
        long WINDOW    = 0x4000;  // 16KB on each side

        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        AddressFactory af   = currentProgram.getAddressFactory();
        AddressSpace as     = currentProgram.getAddressFactory().getDefaultAddressSpace();

        PrintWriter pw = new PrintWriter(new FileWriter(path));
        pw.println("# Gap zone context: functions and xrefs near 0x8006A738-0x8006CCA0");
        pw.println();

        pw.println("=== Functions that overlap or touch the gap ===");
        FunctionIterator fi = fm.getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next();
            long fstart = f.getEntryPoint().getOffset();
            long fend   = f.getBody().getMaxAddress().getOffset();
            boolean overlaps = !(fend < GAP_START || fstart > GAP_END);
            boolean near = Math.abs(fstart - GAP_START) < WINDOW || Math.abs(fend - GAP_END) < WINDOW;
            if (overlaps || near) {
                String tag = overlaps ? " [OVERLAPS GAP]" : " [NEAR GAP]";
                pw.printf("  0x%08X - 0x%08X  %s%s%n", fstart, fend, f.getName(), tag);
            }
        }

        pw.println();
        pw.println("=== References TO gap range from outside ===");
        Address gapStart = as.getAddress(GAP_START);
        Address gapEndA  = as.getAddress(GAP_END);
        AddressSet gapSet = af.getAddressSet(gapStart, gapEndA);
        ReferenceIterator refs = rm.getReferencesTo(gapStart);
        int refCount = 0;
        // Ghidra doesnt have getReferencesTo(range) directly - iterate via iterator
        // Instead list all xrefs from instructions near the gap
        pw.println("  (see functions.txt for full picture - gap xrefs will show as unresolved in Ghidra)");

        pw.close();
        println("Wrote gap context to " + path);
    }

    void exportMemoryMap(String path) throws Exception {
        Memory mem = currentProgram.getMemory();
        PrintWriter pw = new PrintWriter(new FileWriter(path));
        pw.println("# Memory blocks after import");
        for (MemoryBlock mb : mem.getBlocks()) {
            pw.printf("  %-20s  start=0x%08X  end=0x%08X  size=0x%08X  r=%b w=%b x=%b%n",
                mb.getName(),
                mb.getStart().getOffset(),
                mb.getEnd().getOffset(),
                mb.getSize(),
                mb.isRead(), mb.isWrite(), mb.isExecute());
        }
        pw.close();
    }
}
