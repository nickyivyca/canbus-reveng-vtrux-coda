// @category Analysis
// Trace the DLCM module-init region that populates the torque task's RAM
// context struct (0xD9047B5C) and its [R13+0x34] module-data-block pointer.
//
// Background: R13 = 0xD9047B5C is loaded as a BIG-ENDIAN pool literal at
// 0x800676B8 (torque task). The gradient tables are reached at runtime via
// [[R13+0x34]+0x34]. This script seeds disassembly in the init/handler band
// 0x80066000-0x80069000, then dumps listing + decompile for the functions
// containing the key sites:
//   0x8006704C  torque stub's bsr target (module body)
//   0x80066F60  bsr target from the 0xD9047B5C slot-A context
//   0x80066AE8  store r14 -> [R13+0x34]  (MDB writer candidate)
//   0x800670F8  mov.l @(0x3fc,pc),r9 = 0xD9047B5C (slot A referrer)
//
// Run: analyzeHeadless <projdir> dlcm_analysis -process coda_dlcm_prog.bin
//      -noanalysis -postScript DlcmInitTrace.java -scriptPath <scripts>

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import java.io.*;
import java.util.*;

public class DlcmInitTrace extends GhidraScript {

    static final String OUT = System.getProperty("user.home")
        + "/ghidra-projects/dlcm_export/init_trace.txt";

    static final long[] SEEDS = {
        0x80066E00L, 0x80066F60L, 0x8006704CL, 0x80067480L,
        0x80067568L, 0x80067A00L, 0x80066A00L,
    };

    static final long[] DUMP_FNS = {
        0x8006704CL,   // torque stub target
        0x80066F60L,   // bsr from slot-A context
        0x80066AE8L,   // [R13+0x34] store site (function containing it)
        0x800670F8L,   // slot A referrer (function containing it)
    };

    Listing listing;
    FunctionManager fm;
    AddressSpace sp;
    PrintWriter out;

    @Override
    public void run() throws Exception {
        sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        fm = currentProgram.getFunctionManager();
        listing = currentProgram.getListing();

        out = new PrintWriter(new FileWriter(OUT));
        out.println("=== DlcmInitTrace ===");

        // Seed disassembly + functions.
        for (long a : SEEDS) {
            Address ad = sp.getAddress(a);
            new DisassembleCommand(ad, null, true).applyTo(currentProgram, monitor);
            new CreateFunctionCmd(ad).applyTo(currentProgram, monitor);
        }

        // Report function coverage of the band.
        out.println();
        out.println("--- functions in 0x80066000-0x80069000 ---");
        FunctionIterator fit = fm.getFunctions(sp.getAddress(0x80066000L), true);
        while (fit.hasNext()) {
            Function f = fit.next();
            if (f.getEntryPoint().getOffset() > 0x80069000L) break;
            out.println(String.format("  %s @0x%08x  body 0x%08x..0x%08x",
                f.getName(), f.getEntryPoint().getOffset(),
                f.getBody().getMinAddress().getOffset(),
                f.getBody().getMaxAddress().getOffset()));
        }

        // Dump listing + decompile for the targets.
        for (long a : DUMP_FNS) {
            Address ad = sp.getAddress(a);
            Function f = fm.getFunctionContaining(ad);
            out.println();
            out.println("=====================================================");
            if (f == null) {
                out.println("NO FUNCTION containing 0x" + Long.toHexString(a));
                continue;
            }
            out.println(String.format("FUNCTION %s @0x%08x (site 0x%08x) body 0x%08x..0x%08x",
                f.getName(), f.getEntryPoint().getOffset(), a,
                f.getBody().getMinAddress().getOffset(),
                f.getBody().getMaxAddress().getOffset()));
            out.println("--- listing ---");
            InstructionIterator ii = listing.getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction ins = ii.next();
                out.println(String.format("  0x%08x  %s",
                    ins.getAddress().getOffset(), ins.toString()));
            }
            out.println("--- decompile ---");
            DecompInterface ifc = new DecompInterface();
            ifc.openProgram(currentProgram);
            DecompileResults res = ifc.decompileFunction(f, 60, monitor);
            if (res != null && res.getDecompiledFunction() != null) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("(decompile failed)");
            }
            ifc.dispose();
        }

        out.flush();
        out.close();
        println("DlcmInitTrace complete -> " + OUT);
    }
}
