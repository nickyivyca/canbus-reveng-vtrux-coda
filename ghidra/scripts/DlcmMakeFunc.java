// DlcmMakeFunc.java
// Disassemble at the given addresses, create a function at each, and decompile it.
//
// The TriCore rebuild (DlcmTricoreRebuild.java) seeds functions from call targets.
// Code reached only by a tail-call `j`, or only from an undefined region, can end up
// disassembled but with no function around it -- DlcmFuncContext then reports
// "(not inside any known function)" and cannot decompile it.  That is the state of
// the digital-output subsystem initialisers at 0x8008F07C / 0x8008F0D0, which hold
// the address of the channel configuration table this investigation needs.
//
// Args: <outpath> <comma-separated hex addresses>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.io.*;

public class DlcmMakeFunc extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args[0];
        String[] addrs = args[1].split(",");
        new File(outPath).getParentFile().mkdirs();
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        for (String a : addrs) {
            a = a.trim();
            Address addr = toAddr(a.startsWith("0x") ? a.substring(2) : a);
            out.println("================================================================");
            out.println("0x" + addr);
            out.println("================================================================");

            Function fn = getFunctionContaining(addr);
            if (fn == null) {
                if (getInstructionAt(addr) == null) {
                    out.println("  no instruction here -- disassembling");
                    disassemble(addr);
                }
                fn = createFunction(addr, null);
                if (fn == null) {
                    out.println("  createFunction FAILED -- raw listing instead:");
                    Instruction ins = getInstructionAt(addr);
                    for (int i = 0; i < 80 && ins != null; i++) {
                        out.printf("    %s  %s%n", ins.getAddress(), ins.toString());
                        ins = ins.getNext();
                    }
                    out.println();
                    continue;
                }
                out.println("  created function " + fn.getName());
            } else {
                out.println("  already inside " + fn.getName() + " @" + fn.getEntryPoint());
            }

            DecompileResults r = decomp.decompileFunction(fn, 120, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                out.println(r.getDecompiledFunction().getC());
            } else {
                out.println("  [decompile failed: "
                        + (r != null ? r.getErrorMessage() : "null") + "]");
            }
            out.println();
        }

        out.flush();
        out.close();
        println("DlcmMakeFunc: wrote " + outPath);
    }
}
