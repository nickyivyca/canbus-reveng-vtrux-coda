// DlcmVarXref.java
// All references to given absolute addresses, split into reads and writes, with
// the containing function and (optionally) its decompilation.
//
// Written to find the writer of DAT_d0006831, the DLCM's commanded brake-lamp
// state.  The brake-lamp-diagnosis module compares it against the B_K2 feedback
// input (port P1.10):
//
//     FUN_8006eb8c   reads B_K2 into a0-0x27f6, then calls
//     FUN_8006ec06   which calls three comparators, each of the form
//                      (a0-0x27f6 == 0) vs (DAT_d0006831 == 0)
//                    and reports DTC event 18 (B2100, regen brake lamp relay
//                    circuit) and event 15 (C0023, brake switch lamp relay circuit)
//
// so whatever writes DAT_d0006831 is the relay command, and its inputs are the
// answer to whether regen lights the brake lamps.
//
// Args: <outpath> <comma-separated hex addresses> [decompile: 1|0]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmVarXref extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = (args.length > 0 && !args[0].isEmpty())
                ? args[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/var_xref.txt";
        String[] addrs = (args.length > 1 && !args[1].isEmpty())
                ? args[1].split(",")
                : new String[] { "d0006831" };
        boolean doDecomp = args.length > 2 && args[2].equals("1");

        new File(outPath).getParentFile().mkdirs();
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        FunctionManager fnMgr = currentProgram.getFunctionManager();
        DecompInterface decomp = new DecompInterface();
        if (doDecomp) decomp.openProgram(currentProgram);

        LinkedHashSet<Function> writers = new LinkedHashSet<>();
        for (String a : addrs) {
            a = a.trim();
            Address addr = toAddr(a.startsWith("0x") ? a.substring(2) : a);
            out.println("================================================================");
            out.println("references to " + addr);
            out.println("================================================================");
            int nr = 0, nw = 0;
            for (Reference r : getReferencesTo(addr)) {
                Function fn = fnMgr.getFunctionContaining(r.getFromAddress());
                String kind = r.getReferenceType().isWrite() ? "WRITE" : "read ";
                if (r.getReferenceType().isWrite()) { nw++; if (fn != null) writers.add(fn); }
                else nr++;
                Instruction ins = getInstructionAt(r.getFromAddress());
                out.printf("  %s  %s  %-34s  in %s%n", kind, r.getFromAddress(),
                        ins != null ? ins.toString() : "",
                        fn != null ? fn.getName() + " @" + fn.getEntryPoint() : "(none)");
            }
            out.printf("%n  reads: %d   writes: %d%n%n", nr, nw);
        }

        if (doDecomp) {
            out.println("================================================================");
            out.println("decompilation of the writing functions");
            out.println("================================================================");
            for (Function fn : writers) {
                out.println();
                out.println("---------------------------------------------------------------");
                out.printf("%s @%s%n", fn.getName(), fn.getEntryPoint());
                out.println("---------------------------------------------------------------");
                DecompileResults r = decomp.decompileFunction(fn, 90, monitor);
                if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                    out.println(r.getDecompiledFunction().getC());
                } else {
                    out.println("  [decompile failed]");
                }
            }
        }

        out.flush();
        out.close();
        println("DlcmVarXref: wrote " + outPath);
    }
}
