// DlcmA0Base.java
// Recover the value of TriCore global address register A0 (the small-data base).
//
// Large parts of the DLCM's decompilation are written against A0, e.g. the
// digital-output descriptor table in FUN_8007b9b8:
//
//     iVar7 = *(int *)(*(int *)(a0 + -0x3db4) + 4) + channel * 0x14;
//     FUN_800635b8(*(undefined2 *)(iVar7 + 6), *(byte *)(iVar7 + 0x12) == state);
//
// Without A0 those offsets cannot be turned into addresses, so the table cannot
// be read out of the image.  A0 is set once during startup and never reloaded,
// so every write to it in the whole program is worth printing.
//
// Args: <outpath>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.Register;
import java.io.*;

public class DlcmA0Base extends GhidraScript {

    @Override
    public void run() throws Exception {
        String outPath = (getScriptArgs().length > 0)
                ? getScriptArgs()[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/a0_base.txt";
        new File(outPath).getParentFile().mkdirs();
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        Listing listing = currentProgram.getListing();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        out.println("Every instruction that writes TriCore A0 / A1 (small-data bases)");
        out.println();

        InstructionIterator it = listing.getInstructions(true);
        int n = 0;
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            boolean writesA0 = false;
            for (Object o : ins.getResultObjects()) {
                if (o instanceof Register r) {
                    String rn = r.getName().toLowerCase();
                    if (rn.equals("a0") || rn.equals("a1")) writesA0 = true;
                }
            }
            if (!writesA0) continue;
            Function fn = fnMgr.getFunctionContaining(ins.getAddress());
            out.printf("  %s  %-40s  in %s%n", ins.getAddress(), ins.toString(),
                    fn != null ? fn.getName() + " @" + fn.getEntryPoint() : "(none)");
            // Print a little context either side -- A0 is usually built by a pair.
            Instruction p = ins.getPrevious();
            if (p != null) out.printf("        prev: %s  %s%n", p.getAddress(), p.toString());
            Instruction q = ins.getNext();
            if (q != null) out.printf("        next: %s  %s%n", q.getAddress(), q.toString());
            n++;
        }
        out.println();
        out.println("total writes to A0/A1: " + n);
        out.flush();
        out.close();
        println("DlcmA0Base: wrote " + outPath + " (" + n + " sites)");
    }
}
