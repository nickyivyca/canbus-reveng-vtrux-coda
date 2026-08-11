// @category Analysis
// Analyze the MCM CAN handler region (0x8008B000-0x8008E000) in DLCM firmware.
// Goals:
//   1. Disassemble and create functions at all MCM handler entry points
//   2. Decompile the function containing 0x8008D730 (outer context of BSR->D11A)
//   3. Find what R10 holds at the @(0x30,R10) writes in 0x8008D16A-0x8008D1FA
//   4. Look for any references to 0xD9047B5C / 0xD9047B8C (struct base / filter cell)
//   5. Dump disassembly of D11A function body and D730 context
//
// Run: analyzeHeadless %PROJ% dlcm_analysis -process coda_dlcm_prog.bin
//      -noanalysis -postScript DlcmMcmHandler.java -scriptPath %SCRIPTS%

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmMcmHandler extends GhidraScript {

    static final String OUT =
        "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\mcm_handler_analysis.txt";

    // Key addresses in MCM handler
    static final long D730_CALLER   = 0x8008D730L;  // BSR to D11A from here
    static final long D11A_ENTRY    = 0x8008D11AL;  // inner MCM decode entry
    static final long CACE_DECODE   = 0x8008CACEL;  // CMP/EQ#47 decode sub
    static final long FILTER_CELL   = 0xD9047B8CL;  // R13+0x30 filter input
    static final long STRUCT_BASE   = 0xD9047B5CL;  // R13 value

    // Entry points from BxXXX callers (found by antilash_search_p9b_mcm_seeds.py)
    static final long[] MCM_ENTRIES = {
        // BRA/BSR targets from 0x8008B000-0x8008C000
        0x8008C090L, 0x8008C116L, 0x8008C142L, 0x8008C144L,
        0x8008C16CL, 0x8008C180L, 0x8008C190L, 0x8008C1B4L,
        0x8008C1C0L, 0x8008C1DEL, 0x8008C21CL, 0x8008C278L,
        0x8008C30CL, 0x8008C33CL, 0x8008C39AL, 0x8008C3EEL,
        0x8008C42EL, 0x8008C438L, 0x8008C4C6L, 0x8008C4FEL,
        0x8008C52CL,
        // BRA entry points into D2xx from C4EC/C5DA
        0x8008C4ECL, 0x8008C5DAL,
        0x8008D2ECL, 0x8008D2DCL,
        // Direct BSR target
        0x8008D11AL,
        // Decode sub
        0x8008CACEL,
        // Additional interior points from known CAN ID dispatch
        0x8008C000L, 0x8008C374L, 0x8008C5E8L, 0x8008CF6EL,
        // D730 caller context and its BSR targets
        0x8008D460L, 0x8008CE72L, 0x8008D530L,
        0x8008C810L, 0x8008D016L,
        // D680-D800 region (D730 BSR caller) -- explicit seeds
        0x8008D680L, 0x8008D700L, 0x8008D730L,
        // B000 region -- outer state machine
        0x8008B000L, 0x8008B200L, 0x8008B400L, 0x8008B600L,
        0x8008B800L, 0x8008BA00L, 0x8008BC00L, 0x8008BE00L,
    };

    @Override
    public void run() throws Exception {
        AddressSpace sp   = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing   = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();

        PrintWriter out = new PrintWriter(new FileWriter(OUT));
        out.println("=== DlcmMcmHandler Analysis ===");
        out.println("Date: 2026-05-01");
        out.println("Goal: Confirm R10 value at @(0x30,R10) writes in D11A region");
        out.println("      and find MCM->filter input data path");
        out.println();

        // ----------------------------------------------------------------
        // Step 0: Clear stale code units in MCM handler range
        // ----------------------------------------------------------------
        println("Step 0: Clearing code units in B000-E000...");
        Address clearStart = sp.getAddress(0x8008B000L);
        Address clearEnd   = sp.getAddress(0x8008DFFFL);
        listing.clearCodeUnits(clearStart, clearEnd, false);
        println("  Done.");

        // ----------------------------------------------------------------
        // Step 1: Disassemble from all seeds
        // ----------------------------------------------------------------
        println("Step 1: Disassembling from " + MCM_ENTRIES.length + " seeds...");
        int disOk = 0;
        for (long addr : MCM_ENTRIES) {
            Address a = sp.getAddress(addr);
            DisassembleCommand dc = new DisassembleCommand(a, null, true);
            if (dc.applyTo(currentProgram, monitor)) disOk++;
        }
        println("  OK: " + disOk + "/" + MCM_ENTRIES.length);
        out.println("Disassembled from " + disOk + "/" + MCM_ENTRIES.length + " seeds.");
        out.println();

        // ----------------------------------------------------------------
        // Step 2: Create function objects at seed addresses
        // ----------------------------------------------------------------
        println("Step 2: Creating functions at seeds...");
        int fnCreated = 0;
        for (long addr : MCM_ENTRIES) {
            Address a = sp.getAddress(addr);
            if (fm.getFunctionAt(a) == null) {
                CreateFunctionCmd fc = new CreateFunctionCmd(a);
                if (fc.applyTo(currentProgram, monitor)) fnCreated++;
            }
        }
        println("  Created: " + fnCreated);
        out.println("Created " + fnCreated + " new functions.");
        out.println();

        // ----------------------------------------------------------------
        // Step 3: Dump disassembly of key ranges
        // ----------------------------------------------------------------
        out.println("=== Disassembly 0x8008D100 - 0x8008D240 (D11A decode body) ===");
        dumpRange(listing, fm, sp, 0x8008D100L, 0x8008D240L, out);
        out.println();

        out.println("=== Disassembly 0x8008D680 - 0x8008D800 (D730 caller context) ===");
        dumpRange(listing, fm, sp, 0x8008D680L, 0x8008D800L, out);
        out.println();

        out.println("=== Disassembly 0x8008B300 - 0x8008BA00 (outer dispatch) ===");
        dumpRange(listing, fm, sp, 0x8008B300L, 0x8008BA00L, out);
        out.println();

        // ----------------------------------------------------------------
        // Step 4: Decompile functions at key addresses
        // ----------------------------------------------------------------
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        long[] decompAddrs = {
            D11A_ENTRY,   // inner MCM decode
            D730_CALLER,  // outer context of BSR
            0x8008D680L,  // D680 function (contains D730 BSR)
            CACE_DECODE,  // CMP/EQ#47 decode sub
            0x8008D530L,  // called from D70C (context before D730)
            0x8008D460L,  // called from D62C
            0x8008C000L,  // CAN dispatch start
            0x8008C374L,  // 0x01D0 handler
            0x8008C5E8L,  // 0x01C8 handler
            0x8008CF6EL,  // 0x00F0 handler
            0x8008C4ECL,  // BRA->D2EC (0x01C0 path A)
            0x8008C5DAL,  // BRA->D2DC (0x01C0 path B)
        };
        String[] decompLabels = {
            "D11A (MCM decode inner fn)",
            "D730 outer context",
            "D680 (fn containing D730 BSR)",
            "CACE (CMP/EQ#47 decode sub)",
            "D530 (called from D70C)",
            "D460 (called from D62C)",
            "C000 (CAN dispatch start)",
            "C374 (0x01D0 handler)",
            "C5E8 (0x01C8 handler)",
            "CF6E (0x00F0 handler)",
            "C4EC (BRA->D2EC, 0x01C0 path A)",
            "C5DA (BRA->D2DC, 0x01C0 path B)",
        };

        out.println("=== DECOMPILE RESULTS ===");
        for (int i = 0; i < decompAddrs.length; i++) {
            Address addr = sp.getAddress(decompAddrs[i]);
            Function fn = fm.getFunctionAt(addr);
            if (fn == null) fn = fm.getFunctionContaining(addr);

            out.println("--- " + decompLabels[i] + " @ 0x"
                + Long.toHexString(decompAddrs[i]) + " ---");
            if (fn == null) {
                out.println("  (no function found)");
                out.println();
                continue;
            }
            out.println("  Function: " + fn.getName() + " @ " + fn.getEntryPoint());
            out.println("  Body: " + fn.getBody().getMinAddress()
                + " - " + fn.getBody().getMaxAddress());

            out.println("  Callers:");
            for (Reference ref : rm.getReferencesTo(fn.getEntryPoint())) {
                Function cfn = fm.getFunctionContaining(ref.getFromAddress());
                out.println("    <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + "  " + ref.getReferenceType()
                    + "  in: " + (cfn != null ? cfn.getName() + "@" + cfn.getEntryPoint() : "(no fn)"));
            }

            DecompileResults res = decomp.decompileFunction(fn, 90, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println("  --- C DECOMPILE ---");
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("  DECOMPILE FAILED: "
                    + (res != null ? res.getErrorMessage() : "null"));
            }
            out.println();
        }

        // ----------------------------------------------------------------
        // Step 5: Explicit probe of @(0x30,R10) write sites
        // ----------------------------------------------------------------
        out.println("=== @(0x30,Rx) write sites in D100-D200 ===");
        long[] writeSites = {
            0x8008D16AL, 0x8008D170L, 0x8008D17EL,
            0x8008D1B0L, 0x8008D1B8L, 0x8008D1FAL,
        };
        for (long ws : writeSites) {
            Address wa = sp.getAddress(ws);
            Instruction ins = listing.getInstructionAt(wa);
            Function fn = fm.getFunctionContaining(wa);
            out.println("  0x" + Long.toHexString(ws) + ": "
                + (ins != null ? ins.toString() : "[gap]")
                + "  in fn: " + (fn != null ? fn.getName() + "@" + fn.getEntryPoint() : "(no fn)"));

            // Look for xrefs TO this write site (who jumps here?)
            for (Reference ref : rm.getReferencesTo(wa)) {
                out.println("    xref from: 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + "  " + ref.getReferenceType());
            }
        }
        out.println();

        // ----------------------------------------------------------------
        // Step 6: Check if Ghidra has any references TO SRAM 0xD9047B8C
        //         or pool constants = 0xD9047B5C in the B-E range
        // ----------------------------------------------------------------
        out.println("=== Instructions referencing 0xD9047B5C or 0xD9047B8C ===");
        // Scan instructions in B000-E000 for operand values matching struct base
        Address scanStart = sp.getAddress(0x8008B000L);
        Address scanEnd   = sp.getAddress(0x8008E000L);
        InstructionIterator iter = listing.getInstructions(scanStart, true);
        int refCount = 0;
        while (iter.hasNext() && refCount < 200) {
            Instruction ins = iter.next();
            if (ins.getAddress().compareTo(scanEnd) >= 0) break;
            for (Object opObj : ins.getOpObjects(0)) {
                if (opObj instanceof Long || opObj instanceof Integer) {
                    long val = (opObj instanceof Long) ? (Long) opObj : (long)(Integer) opObj;
                    if (val == STRUCT_BASE || val == FILTER_CELL) {
                        out.println("  " + ins.getAddress() + ": " + ins.toString()
                            + "  VALUE=0x" + Long.toHexString(val));
                        refCount++;
                    }
                }
            }
            for (Object opObj : ins.getOpObjects(1)) {
                if (opObj instanceof Long || opObj instanceof Integer) {
                    long val = (opObj instanceof Long) ? (Long) opObj : (long)(Integer) opObj;
                    if (val == STRUCT_BASE || val == FILTER_CELL) {
                        out.println("  " + ins.getAddress() + ": " + ins.toString()
                            + "  VALUE=0x" + Long.toHexString(val));
                        refCount++;
                    }
                }
            }
        }
        if (refCount == 0) {
            out.println("  (none found in B000-E000)");
        }
        out.println();

        // ----------------------------------------------------------------
        // Step 7: Dump B000-B200 outer caller context with full disassembly
        // ----------------------------------------------------------------
        out.println("=== Disassembly 0x8008B000 - 0x8008B200 (outer state machine entry) ===");
        dumpRange(listing, fm, sp, 0x8008B000L, 0x8008B200L, out);
        out.println();

        decomp.dispose();
        out.flush();
        out.close();
        println("DlcmMcmHandler complete -> " + OUT);
    }

    void dumpRange(Listing listing, FunctionManager fm, AddressSpace sp,
                   long startVa, long endVa, PrintWriter out) {
        Address curr = sp.getAddress(startVa);
        Address end  = sp.getAddress(endVa);
        String lastFn = "";
        while (curr.compareTo(end) <= 0) {
            Function f = fm.getFunctionContaining(curr);
            if (f != null && !f.getName().equals(lastFn)) {
                out.println("  ;; [" + f.getName() + " @ " + f.getEntryPoint() + "]");
                lastFn = f.getName();
            }
            Instruction instr = listing.getInstructionAt(curr);
            if (instr != null) {
                byte[] bytes = new byte[instr.getLength()];
                try { instr.getBytesInCodeUnit(bytes, 0); } catch (Exception ex) {}
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  %08X  ", curr.getOffset()));
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                while (sb.length() < 22) sb.append(" ");
                sb.append(" ").append(instr.toString());
                // Flag @(0x30,Rx) writes
                String instrStr = instr.toString();
                if (instrStr.contains("0x30")) sb.append("  << @+0x30");
                out.println(sb.toString());
                try { curr = curr.add(instr.getLength()); } catch (Exception e) { break; }
            } else {
                Data d = listing.getDataAt(curr);
                int sz = (d != null && d.getLength() > 0) ? d.getLength() : 2;
                byte[] bytes = new byte[sz];
                try {
                    for (int i = 0; i < sz; i++) {
                        bytes[i] = (byte) currentProgram.getMemory().getByte(curr.add(i));
                    }
                } catch (Exception ex) {}
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  %08X  [gap] ", curr.getOffset()));
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                out.println(sb.toString());
                try { curr = curr.add(sz); } catch (Exception e) { break; }
            }
        }
    }
}
