// @category Analysis
// Clean rebuild: remove all aggressive-sweep function artifacts, then
// recursively disassemble from every confirmed entry point.
// Run with: analyzeHeadless ... -process binary -noanalysis -postScript DlcmCleanSetup.java

import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.util.*;

public class DlcmCleanSetup extends GhidraScript {

    @Override
    public void run() throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing    = currentProgram.getListing();

        // ----------------------------------------------------------------
        // Step 1: Remove every existing function (the aggressive-sweep crud)
        // ----------------------------------------------------------------
        println("Removing existing functions...");
        List<Address> existing = new ArrayList<>();
        for (Function f : fm.getFunctions(true)) {
            existing.add(f.getEntryPoint());
        }
        for (Address a : existing) {
            fm.removeFunction(a);
        }
        println("Removed " + existing.size() + " functions.");

        // ----------------------------------------------------------------
        // Step 2: Clear code units in the PROG and VBR ranges so
        //         DisassembleCommand has a clean slate to work with.
        // ----------------------------------------------------------------
        println("Clearing code units...");
        listing.clearCodeUnits(
            sp.getAddress(0x80040000L),
            sp.getAddress(0x80095CB2L),
            false, monitor);
        println("Code units cleared.");

        // ----------------------------------------------------------------
        // Step 3: Seed entry points
        //
        // Sources for these addresses:
        //   - Startup chain analysis (dlcm_goals13_final.py)
        //   - VBR candidate 0x8005DED8 (score 3/3, dlcm_vbr_scan.py)
        //   - Goal 3 dispatch table scan (dlcm_goals13_final.py)
        //   - State machine object handler pointers
        // ----------------------------------------------------------------
        long[] seeds = {
            // --- Startup / reset ---
            0x80040052L,   // reset_entry (BRA target from header BRA at 0x80040030)

            // --- VBR exception handlers (VBR = 0x8005DED8) ---
            0x8005DFD8L,   // general exception  VBR+0x100
            0x8005E2D8L,   // TLB miss           VBR+0x400
            0x8005E4D8L,   // interrupt          VBR+0x600

            // --- VBR setup functions ---
            0x8005D22AL,   // contains LDC R1,VBR
            0x8005E2ACL,   // contains LDC R9,VBR

            // --- State machine entry and default stub ---
            0x80042036L,   // state machine main entry (called 0x8004136C, 0x800427E4)
            0x800422AEL,   // default no-op handler stub

            // --- Dispatch table section 1 (0x80041E00, LE ptrs -> 0x8007Fxxx/0x80080xxx) ---
            0x80080C08L, 0x80080B86L, 0x80080B90L, 0x8007FFDEL,
            0x80080B9AL, 0x80080BA4L, 0x8007FFF4L, 0x80080000L,
            0x80080016L, 0x80080022L, 0x80080BAEL, 0x800803FAL,
            0x80080416L, 0x80080432L, 0x80080BB8L, 0x80080BC2L,
            0x80080BCCL, 0x80080BD6L, 0x80080BE0L, 0x80080046L,
            0x80080BEAL, 0x80080BF4L, 0x80080BFEL, 0x80080A50L,
            0x80080A5AL, 0x80080A46L, 0x80080A64L, 0x80080A6EL,
            0x80080A78L, 0x80080A82L, 0x80080A8CL, 0x80080A96L,
            0x80080B22L, 0x80080AA0L, 0x80080AAAL, 0x80080AB4L,
            0x80080ABEL, 0x80080AC8L, 0x80080AD2L, 0x80080ADCL,
            0x80080AE6L, 0x80080AF0L, 0x80080AFAL, 0x80080B04L,
            0x80080B0EL, 0x80080B18L,

            // --- Dispatch table section 2 (0x80041EBC, LE ptrs -> 0x80068Bxx) ---
            0x80068BB2L, 0x80068BC2L, 0x80068BDEL, 0x80068BFAL,
            0x80068C16L, 0x80068C32L, 0x80068C4EL, 0x80068BBAL,
            0x80068BD0L, 0x80068BECL, 0x80068C08L, 0x80068C24L,
            0x80068C40L, 0x80068C5CL,

            // --- State machine object handler pointers (dlcm_goals13_final.py Part D) ---
            0x8008A82AL, 0x8008AC54L, 0x800617B0L, 0x80061828L,
            0x80061AFCL, 0x80061BACL, 0x80061A00L, 0x800619D4L,
            0x8008AD20L, 0x80060C64L, 0x80061D6AL, 0x80061D40L,
            0x8005E018L, 0x8008EA3EL, 0x80064520L, 0x80064574L,

            // --- BSR callers of state machine region (partial; seeds adjacent code) ---
            0x80042688L, 0x8004270CL, 0x800427D0L, 0x800427D4L,
            0x800427E4L, 0x800428ACL,
        };

        // ----------------------------------------------------------------
        // Step 4: Disassemble recursively from each seed
        // DisassembleCommand with followFlow=true traces branches/calls
        // and disassembles all reachable code.
        // ----------------------------------------------------------------
        println("Disassembling from " + seeds.length + " seed addresses...");
        int ok = 0;
        for (long addr : seeds) {
            Address a = sp.getAddress(addr);
            DisassembleCommand dc = new DisassembleCommand(a, null, true);
            if (dc.applyTo(currentProgram, monitor)) {
                ok++;
            } else {
                println("  WARN: disassemble failed at 0x" + Long.toHexString(addr));
            }
        }
        println("Disassembled from " + ok + "/" + seeds.length + " seeds.");

        // ----------------------------------------------------------------
        // Step 5: Create function objects at each seed address
        // Now that code is disassembled with proper flow, CreateFunctionCmd
        // can trace the correct function body extent.
        // ----------------------------------------------------------------
        println("Creating functions at seed addresses...");
        int created = 0;
        for (long addr : seeds) {
            Address a = sp.getAddress(addr);
            if (fm.getFunctionAt(a) == null) {
                CreateFunctionCmd fc = new CreateFunctionCmd(a);
                if (fc.applyTo(currentProgram, monitor)) {
                    created++;
                }
            } else {
                created++;
            }
        }
        println("Created/confirmed " + created + " functions.");
        println("DlcmCleanSetup complete.");
    }
}
