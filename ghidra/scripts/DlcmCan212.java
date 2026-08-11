// @category Analysis
// Analyze the CAN 0x212 transmit path in DLCM firmware.
// Seeds the gap region around 0x8006A738-0x8006CCA0 and the
// 0x8006D9E2 enclosing function, then decompiles the relevant functions.
//
// Run: analyzeHeadless %PROJ% dlcm_analysis -process coda_dlcm_prog.bin
//      -noanalysis -postScript DlcmCan212.java -scriptPath %SCRIPTS%

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmCan212 extends GhidraScript {

    static final String OUT =
        "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\can212_analysis.txt";

    // The confirmed 0x212 CAN ID load site
    static final long LOAD_SITE  = 0x8006D9E2L;
    // BSR target from load site (CAN send helper)
    static final long CAN_SEND_1 = 0x8006CE4CL;
    // BSR target for 0x211 (same pattern, confirms the call convention)
    static final long CAN_SEND_2 = 0x8006D06EL;

    // Addresses called/jumped into the gap or from gap boundaries,
    // extracted from gap_xrefs.txt.  Using these as seeds gives Ghidra's
    // recursive disassembler a foothold inside the gap.
    static final long[] GAP_SEEDS = {
        // Frequently-called helper inside gap
        0x8006C630L, 0x8006C644L, 0x8006C688L, 0x8006C69CL,
        0x8006C6E0L, 0x8006C6F4L, 0x8006C738L, 0x8006C74CL,
        0x8006C900L, 0x8006C95AL, 0x8006C984L,
        0x8006CAA2L, 0x8006CAB6L, 0x8006CB2AL,
        // Gap interior targets from xrefs
        0x8006BF1AL, 0x8006BF2AL, 0x8006C19AL,
        0x8006C32CL, 0x8006C406L, 0x8006C594L, 0x8006C5A8L,
        // Gap start / near-start addresses from xref READ targets
        0x8006A738L, 0x8006A744L, 0x8006A748L, 0x8006A74CL,
        0x8006A764L, 0x8006A770L, 0x8006A77CL, 0x8006A780L,
        0x8006A7A2L, 0x8006A7A4L, 0x8006A7AEL, 0x8006A7BAL,
        0x8006A7E6L, 0x8006A7ECL, 0x8006A7F4L,
        0x8006A818L, 0x8006A84CL, 0x8006A84EL,
        0x8006B056L, 0x8006B070L, 0x8006B07AL,
        0x8006B08AL, 0x8006B0A4L, 0x8006B0BEL,
        0x8006B0DAL, 0x8006B114L, 0x8006B52CL,
        // Addresses in the post-gap region discovered via gap_context
        0x8006CCB6L, 0x8006CCC6L, 0x8006CD94L,
        0x8006CE4CL, 0x8006CE60L, 0x8006CEA4L, 0x8006CEB8L,
        0x8006CEFCL, 0x8006CF10L, 0x8006CF54L, 0x8006CF68L,
        0x8006CFCCL, 0x8006D06EL,
        // D0xx helpers called repeatedly from outer function (discovered 2026-04-30)
        // These are BSR targets seen at D892, D8A6, D8EA, D8FE in the outer function body
        0x8006D076L, 0x8006D08AL, 0x8006D0CEL, 0x8006D0E2L,
        // Additional Cxxx BSR targets (called directly from D342-D400 filter blocks)
        // These are called with R15=0x7F0F0880 to determine if they read or write the buffer
        0x8006CB3EL, 0x8006CB82L, 0x8006CB96L, 0x8006CBDAL, 0x8006CBEEL,
        0x8006CC32L, 0x8006CC46L, 0x8006CCAAL,
        // D342 region seeds -- filter tap groups that use R15=0x7F0F0880
        0x8006D342L, 0x8006D39AL, 0x8006D3F2L,
        // Additional BSR targets seen in D500-D800 region of outer function
        0x8006CB6EL, 0x8006CB94L, 0x8006C984L,
        0x8006DF50L, 0x8006DF5EL, 0x8006DF9CL,
        0x8006E060L, 0x8006E0B8L, 0x8006E180L,
        0x8006E202L, 0x8006E262L, 0x8006E270L,
        0x8006E282L, 0x8006E2ACL, 0x8006E2C4L,
        0x8006E2DAL, 0x8006E304L,
        // The 0x212 load site and neighbors
        0x8006D9E2L, 0x8006D96EL, 0x8006D916L, 0x8006D5EAL,
        0x8006D384L, 0x8006D31EL, 0x8006D29CL,
        0x8006D17EL, 0x8006D192L,
        // DB1C: forward-called from D518 within outer function
        0x8006DB1CL,
        // Delay slots / fallthrough addresses that get stale-cached as gaps
        // when their opcode was previously unrecognized by Ghidra.
        // Must seed explicitly so DisassembleCommand revisits them.
        0x8006D07EL, 0x8006CE4EL, 0x8006CE62L, 0x8006D0B6L,
        0x8006DA00L, 0x8006D0C8L, 0x8006D11EL, 0x8006CE68L,
        // D0C7/D11E/DA00/CE68 — decompiler keeps hitting these; seed to force disassembly
        0x8006D0C7L, 0x8006D11FL, 0x8006DA01L, 0x8006CE69L,
        // CD02: 0x8FFF (BF/S self-referential trap) -- now patched as NOP in Sleigh
        // Seed CD02 and D0C8/D11E (now have NOP constructors) explicitly
        0x8006CD02L, 0x8006D0C8L, 0x8006D11EL,
        // D128: 0xA021 (BRA self-trap) and D12A: 0xA03F (nested BRA in delay slot)
        // Both now patched as NOPs in Sleigh -- blocks D076/D08A/D0CE/D0E2/CFCC decompiles
        0x8006D128L, 0x8006D12AL,
        // CDB0: BSR 0x8006C594 with 0xFF0F delay slot at CDB2 -- patched as NOP
        // CDB2 BEFORE CDB0: delay slot must be in Listing before parent BSR is validated
        0x8006CDB2L, 0x8006CDB0L,
        // DB-region: gradient limiter helpers (added 2026-05-03)
        // DBC0: called from D1BE, loads gradient compare values from CAL
        // DBEE: positive gradient path (TrqLast rate limit computation)
        // DBD4: target of BRA from D7B2 (join after negative gradient path)
        // DD36: filter tap pairing helper (adjacent, needed for clean disassembly)
        0x8006DBC0L, 0x8006DBEEL, 0x8006DBD4L, 0x8006DD36L,
        // Neighbors to anchor disassembly across pool-constant gaps in DB region
        0x8006DC00L, 0x8006DC20L, 0x8006DC40L, 0x8006DC60L,
        0x8006DC80L, 0x8006DCA0L, 0x8006DCC0L, 0x8006DCE0L,
        0x8006DD00L, 0x8006DD20L,
        // E-region: gradient limit table interpolation functions (added 2026-05-03)
        // E5CC: called by DBC0 (compare loader); E606: called by DBEE (positive path)
        // E672, E686, E6CE, E71A: same mac.w interpolation kernel, called from DC helpers
        0x8006E5CCL, 0x8006E606L, 0x8006E672L, 0x8006E686L,
        0x8006E6CEL, 0x8006E71AL,
        // Common BSR target from the repeating B4FF pattern at each interpolation entry
        0x8006EFD0L, 0x8006EFCCL, 0x8006EFD4L,
        // Init code region: FFFF-delimited module descriptor blocks (added 2026-05-03)
        // Block starts after each FFFF-pair delimiter at 0x80041964, 80041998, 800419CC
        0x80041968L, 0x8004199CL, 0x800419D0L,
        // Known instruction anchor (mov.l @(0x14,r0),r12 + literal pool 0x80021400)
        0x80041A04L, 0x80041A08L,
        // Broader init region - try PROG start area and surrounding blocks
        0x80040000L, 0x80040004L, 0x80040008L, 0x80040010L, 0x80040020L,
        0x80041800L, 0x80041820L, 0x80041840L, 0x80041860L, 0x80041880L,
        0x80041900L, 0x80041920L, 0x80041940L, 0x80041960L,
        0x80041A10L, 0x80041A14L, 0x80041A20L, 0x80041A40L,
        0x80041B00L, 0x80041B40L, 0x80041C00L,
        // Large 2300-byte init loop at 0x8004270C -- module descriptor iterator (added 2026-05-03)
        0x8004270CL,
    };

    @Override
    public void run() throws Exception {
        AddressSpace sp   = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing   = currentProgram.getListing();

        PrintWriter out = new PrintWriter(new FileWriter(OUT));
        out.println("=== DlcmCan212 Analysis ===");
        out.println("Target: CAN 0x212 transmit path");
        out.println("Load site: 0x" + Long.toHexString(LOAD_SITE));
        out.println("CAN send fn: 0x" + Long.toHexString(CAN_SEND_1));
        out.println();

        // ----------------------------------------------------------------
        // Step 0: Clear stale code units in target range so Ghidra doesn't
        //         skip re-disassembly when it hits previously-stored gaps or
        //         bad-instruction records from before the Sleigh patch.
        // ----------------------------------------------------------------
        println("Step 0: Clearing code units in C000-DA80 and CE00-D200...");
        long[][] clearRanges = {
            {0x8006C000L, 0x8006DA80L},
            {0x8006CE00L, 0x8006D200L},
            {0x8006CCC0L, 0x8006CD20L},  // CD02 nested-delay-slot trap region
            {0x8006DA80L, 0x8006DD80L},  // DB/DC region: gradient limiter helpers
            {0x8006E580L, 0x8006F000L},  // E-region: table interpolation functions
            {0x80040000L, 0x80044000L},  // init region: FFFF-delimited module init table
        };
        for (long[] r : clearRanges) {
            Address rStart = sp.getAddress(r[0]);
            Address rEnd   = sp.getAddress(r[1]);
            listing.clearCodeUnits(rStart, rEnd, false);
        }
        println("  Done.");

        // ----------------------------------------------------------------
        // Step 1: Disassemble recursively from all seeds
        // ----------------------------------------------------------------
        println("Step 1: Disassembling from " + GAP_SEEDS.length + " seeds...");
        int disasmOk = 0;
        for (long addr : GAP_SEEDS) {
            Address a = sp.getAddress(addr);
            DisassembleCommand dc = new DisassembleCommand(a, null, true);
            if (dc.applyTo(currentProgram, monitor)) {
                disasmOk++;
            }
        }
        println("  Disassembled " + disasmOk + "/" + GAP_SEEDS.length);
        out.println("Disassembled from " + disasmOk + "/" + GAP_SEEDS.length + " seeds.");

        // Diagnostic: check what Ghidra sees at problem addresses + new BRA/delay-slot addresses
        long[] diagAddrs = {0x8006D0C8L, 0x8006D11EL, 0x8006CE68L, 0x8006DA00L,
                            0x8006D128L, 0x8006D12AL, 0x8006CDB0L, 0x8006CDB2L};
        out.println("=== Diagnostic: stale-address probe ===");
        for (long da : diagAddrs) {
            Address dAddr = sp.getAddress(da);
            Instruction dInstr = listing.getInstructionAt(dAddr);
            if (dInstr != null) {
                out.println("  " + String.format("%08X", da) + "  INSTRUCTION: " + dInstr.toString());
            } else {
                Data dData = listing.getDataAt(dAddr);
                out.println("  " + String.format("%08X", da) + "  gap/data: "
                    + (dData != null ? dData.toString() : "(null)"));
            }
        }
        out.println();

        // ----------------------------------------------------------------
        // Step 2: Create functions at key addresses
        // ----------------------------------------------------------------
        println("Step 2: Creating functions...");
        int fnCreated = 0;
        for (long addr : GAP_SEEDS) {
            Address a = sp.getAddress(addr);
            if (fm.getFunctionAt(a) == null) {
                CreateFunctionCmd fc = new CreateFunctionCmd(a);
                if (fc.applyTo(currentProgram, monitor)) {
                    fnCreated++;
                }
            }
        }
        println("  Created " + fnCreated + " new functions.");
        out.println("Created " + fnCreated + " new functions.");
        out.println();

        // ----------------------------------------------------------------
        // Step 3: Find function containing the 0x212 load site
        // ----------------------------------------------------------------
        Address loadAddr = sp.getAddress(LOAD_SITE);
        Function loadFn  = fm.getFunctionContaining(loadAddr);
        if (loadFn == null) {
            out.println("WARNING: No function found containing 0x" + Long.toHexString(LOAD_SITE));
            out.println("Trying to find by scanning backward for RTS...");
            // Scan backward for an RTS instruction (0x000B) to bound the function
            for (long back = LOAD_SITE - 2; back >= LOAD_SITE - 0x2000; back -= 2) {
                Address sa = sp.getAddress(back);
                Instruction ins = listing.getInstructionAt(sa);
                if (ins != null) {
                    String mn = ins.getMnemonicString().toLowerCase();
                    if (mn.equals("rts") || mn.equals("rte")) {
                        // Function starts just after the delay slot (RTS + 2 bytes)
                        Address fnEntry = sp.getAddress(back + 4);
                        out.println("  Found " + mn.toUpperCase() + " at 0x" + Long.toHexString(back)
                            + " -> trying function at 0x" + Long.toHexString(back + 4));
                        CreateFunctionCmd fc2 = new CreateFunctionCmd(fnEntry);
                        fc2.applyTo(currentProgram, monitor);
                        loadFn = fm.getFunctionAt(fnEntry);
                        if (loadFn != null) break;
                    }
                }
            }
        }

        // ----------------------------------------------------------------
        // Step 4: Get (or create) the CAN send function
        // ----------------------------------------------------------------
        Address canSendAddr = sp.getAddress(CAN_SEND_1);
        Function canSendFn  = fm.getFunctionAt(canSendAddr);
        if (canSendFn == null) {
            canSendFn = fm.getFunctionContaining(canSendAddr);
        }

        // ----------------------------------------------------------------
        // Step 5: Report what function Ghidra found containing D9E2
        // ----------------------------------------------------------------
        out.println("=== Function containing 0x8006D9E2 ===");
        if (loadFn != null) {
            out.println("Entry: " + loadFn.getEntryPoint());
            out.println("Body:  " + loadFn.getBody().getMinAddress()
                + " - " + loadFn.getBody().getMaxAddress()
                + "  (" + (loadFn.getBody().getMaxAddress().getOffset()
                         - loadFn.getBody().getMinAddress().getOffset() + 1) + " bytes)");
            ReferenceManager rm0 = currentProgram.getReferenceManager();
            out.println("Callers (xrefs to entry):");
            for (Reference ref : rm0.getReferencesTo(loadFn.getEntryPoint())) {
                Function cfn = fm.getFunctionContaining(ref.getFromAddress());
                out.println("  <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + "  " + ref.getReferenceType()
                    + "  in: " + (cfn != null ? cfn.getName() + "@" + cfn.getEntryPoint() : "(no fn)"));
            }
        } else {
            out.println("WARNING: no function found containing 0x8006D9E2");
        }
        out.println();

        // ----------------------------------------------------------------
        // Step 6: Dump disassembly ranges
        // ----------------------------------------------------------------
        out.println("=== Disassembly 0x8006C000 - 0x8006D000 (filter tap + Cxxx helpers) ===");
        dumpRange(listing, fm, sp, 0x8006C000L, 0x8006D000L, out);
        out.println();
        out.println("=== Disassembly 0x8006D000 - 0x8006DA80 (outer fn + D0xx helpers) ===");
        dumpRange(listing, fm, sp, 0x8006D000L, 0x8006DA80L, out);
        out.println();
        out.println("=== Disassembly 0x8006DA80 - 0x8006DD80 (gradient limiter DB region) ===");
        dumpRange(listing, fm, sp, 0x8006DA80L, 0x8006DD80L, out);
        out.println();
        out.println("=== Disassembly 0x8006E580 - 0x8006F000 (E-region table interpolation) ===");
        dumpRange(listing, fm, sp, 0x8006E580L, 0x8006F000L, out);
        out.println();
        out.println("=== Disassembly 0x80041800 - 0x80041C00 (init FFFF-block region) ===");
        dumpRange(listing, fm, sp, 0x80041800L, 0x80041C00L, out);
        out.println();
        out.println("=== Disassembly 0x8004270C - 0x80042900 (init 270C function head) ===");
        dumpRange(listing, fm, sp, 0x8004270CL, 0x80042900L, out);
        out.println();

        // ----------------------------------------------------------------
        // Step 7: Decompile D0xx helpers and enclosing function
        // ----------------------------------------------------------------
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        long[] decompTargets = {
            0x8006D076L, 0x8006D08AL, 0x8006D0CEL, 0x8006D0E2L,
            CAN_SEND_1, CAN_SEND_2,
            // Cxxx functions called with R15=0x7F0F0880 -- do they read or write the buffer?
            0x8006CB2AL, 0x8006CB3EL, 0x8006CB82L, 0x8006CB96L,
            // C630: called from CAN TX functions; C900 / C95A: filter helpers
            0x8006C630L, 0x8006C900L, 0x8006C95AL,
            // CFCC: the 0x211 TX enclosing function
            0x8006CFCCL,
            // DB-region: gradient limiter helpers (added 2026-05-03)
            0x8006DBC0L, 0x8006DBEEL, 0x8006DBD4L,
            // E-region: table interpolation functions (added 2026-05-03)
            0x8006E5CCL, 0x8006E606L, 0x8006E672L,
            // Init region: FFFF-delimited module init blocks (added 2026-05-03)
            0x80041968L, 0x8004199CL, 0x800419D0L, 0x80041A04L, 0x80041A08L,
            // Large 2300-byte init loop -- module descriptor iterator (added 2026-05-03)
            0x8004270CL,
        };
        String[] decompLabels = {
            "D076 helper", "D08A helper", "D0CE helper", "D0E2 helper",
            "CAN TX 0x212 (CE4C)", "CAN TX 0x211 (D06E)",
            "CB2A (called w/ R15=SRAM)", "CB3E", "CB82", "CB96",
            "C630 (called by CAN TX)", "C900 helper", "C95A helper",
            "CFCC (0x211 TX enclosing)",
            "DBC0 (gradient compare loader)", "DBEE (positive gradient path)", "DBD4 (negative gradient join)",
            "E5CC (table interp, called by DBC0)", "E606 (table interp, called by DBEE)", "E672 (table interp)",
            "init block A (0x80041968)", "init block B (0x8004199C)", "init block C (0x800419D0)",
            "init A04", "init A08 (mov.l anchor)",
            "init 270C (2300-byte module descriptor loop)",
        };

        Function[] allToDecompile = new Function[decompTargets.length + 1];
        String[]   allLabels      = new String[decompTargets.length + 1];
        allToDecompile[0] = loadFn;
        allLabels[0] = "ENCLOSING fn of 0x212 send";
        for (int i = 0; i < decompTargets.length; i++) {
            allToDecompile[i + 1] = fm.getFunctionAt(sp.getAddress(decompTargets[i]));
            allLabels[i + 1] = decompLabels[i];
        }

        for (int i = 0; i < allToDecompile.length; i++) {
            Function f = allToDecompile[i];
            out.println("=== DECOMPILE: " + allLabels[i] + " ===");
            if (f == null) {
                out.println("NULL -- function not found/created");
                out.println();
                continue;
            }
            out.println("Function: " + f.getName() + " @ " + f.getEntryPoint());
            out.println("Body: " + f.getBody().getMinAddress()
                + " - " + f.getBody().getMaxAddress()
                + "  (" + (f.getBody().getMaxAddress().getOffset()
                         - f.getBody().getMinAddress().getOffset() + 1) + " bytes)");
            ReferenceManager rm = currentProgram.getReferenceManager();
            out.println("Callers:");
            for (Reference ref : rm.getReferencesTo(f.getEntryPoint())) {
                Function cfn = fm.getFunctionContaining(ref.getFromAddress());
                out.println("  <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + "  " + ref.getReferenceType()
                    + "  in: " + (cfn != null ? cfn.getName() + "@" + cfn.getEntryPoint() : "(no fn)"));
            }
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println("--- C DECOMPILE ---");
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("DECOMPILE FAILED: " + (res != null ? res.getErrorMessage() : "null"));
            }
            out.println();
        }

        // ----------------------------------------------------------------
        // Step 8: Xrefs to 0x8006C630 (the function called by CAN_SEND_1)
        // ----------------------------------------------------------------
        out.println("=== XREFS TO 0x8006C630 ===");
        Address c630 = sp.getAddress(0x8006C630L);
        ReferenceManager rm2 = currentProgram.getReferenceManager();
        for (Reference ref : rm2.getReferencesTo(c630)) {
            Function containing = fm.getFunctionContaining(ref.getFromAddress());
            out.println("  <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                + "  " + ref.getReferenceType()
                + "  in: " + (containing != null ? containing.getName() : "(no fn)"));
        }

        // ----------------------------------------------------------------
        // Step 9: Init region - inventory + decompile function at anchor
        // ----------------------------------------------------------------
        out.println("=== Init region function inventory (0x80040000-0x80044000) ===");
        {
            Address initStart2 = sp.getAddress(0x80040000L);
            Address initEnd2   = sp.getAddress(0x80044000L);
            FunctionIterator initFnIter = fm.getFunctions(initStart2, true);
            int initCount = 0;
            while (initFnIter.hasNext()) {
                Function f = initFnIter.next();
                if (f.getEntryPoint().compareTo(initEnd2) > 0) break;
                long fSz = f.getBody().getMaxAddress().getOffset()
                         - f.getBody().getMinAddress().getOffset() + 1;
                out.println("  fn @ " + f.getEntryPoint()
                    + "  body: " + f.getBody().getMinAddress()
                    + "-" + f.getBody().getMaxAddress()
                    + "  (" + fSz + " bytes)");
                initCount++;
            }
            out.println("Total: " + initCount + " functions in init region.");
            out.println();
        }

        out.println("=== Init region: function containing anchor 0x80041A08 ===");
        {
            Address anchor = sp.getAddress(0x80041A08L);
            Function anchorFn = fm.getFunctionContaining(anchor);
            if (anchorFn == null) anchorFn = fm.getFunctionAt(anchor);
            if (anchorFn != null) {
                long aSz = anchorFn.getBody().getMaxAddress().getOffset()
                         - anchorFn.getBody().getMinAddress().getOffset() + 1;
                out.println("Function @ " + anchorFn.getEntryPoint()
                    + "  body: " + anchorFn.getBody().getMinAddress()
                    + "-" + anchorFn.getBody().getMaxAddress()
                    + "  (" + aSz + " bytes)");
                ReferenceManager rm9 = currentProgram.getReferenceManager();
                out.println("Callers:");
                for (Reference ref : rm9.getReferencesTo(anchorFn.getEntryPoint())) {
                    Function cfn = fm.getFunctionContaining(ref.getFromAddress());
                    out.println("  <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                        + "  " + ref.getReferenceType()
                        + "  in: " + (cfn != null ? cfn.getName() + "@" + cfn.getEntryPoint() : "(no fn)"));
                }
                DecompileResults ar = decomp.decompileFunction(anchorFn, 60, monitor);
                if (ar != null && ar.decompileCompleted()) {
                    out.println("--- DECOMPILE ---");
                    out.println(ar.getDecompiledFunction().getC());
                } else {
                    out.println("DECOMPILE FAILED: " + (ar != null ? ar.getErrorMessage() : "null"));
                }
            } else {
                out.println("WARNING: no function found at or containing 0x80041A08");
            }
            out.println();
        }

        decomp.dispose();
        out.flush();
        out.close();
        println("DlcmCan212 complete -> " + OUT);
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
                sb.append(" ").append(instr.toString());
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
