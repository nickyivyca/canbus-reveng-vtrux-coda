// For each address given: the containing function, its callers (2 levels up),
// and its decompilation.
//
// Written 2026-09-20 to identify the code region 0x8004E000-0x80052000, which
// builds the addresses of a SECOND complete set of gradient-limiter LUT
// descriptors at 0x80040920 -- a set the running torque path (0x80075-0x80077)
// never touches. The question it answers: is that region reachable from the
// application, i.e. is the second table set live?
//
// args: <outfile> <comma-separated hex addresses> [decompile: 1|0]
//@category DLCM
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.PrintWriter;
import java.util.*;

public class DlcmFuncContext extends GhidraScript {

    Set<Address> callersOf(Function f) {
        Set<Address> out = new LinkedHashSet<>();
        ReferenceIterator it = currentProgram.getReferenceManager()
                .getReferencesTo(f.getEntryPoint());
        while (it.hasNext()) {
            Reference r = it.next();
            Function c = getFunctionContaining(r.getFromAddress());
            if (c != null) out.add(c.getEntryPoint());
        }
        return out;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(args[0]);
        boolean doDecomp = args.length < 3 || args[2].equals("1");

        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);

        for (String tok : args[1].split(",")) {
            tok = tok.trim();
            if (tok.isEmpty()) continue;
            Address a = currentProgram.getAddressFactory().getDefaultAddressSpace()
                    .getAddress(Long.parseLong(tok.replace("0x", ""), 16));
            Function f = getFunctionContaining(a);
            out.printf("%n======== 0x%s ========%n", a);
            if (f == null) { out.println("  (not inside any known function)"); continue; }
            out.printf("  function %s @ %s size=%d%n", f.getName(),
                    f.getEntryPoint(), f.getBody().getNumAddresses());
            Set<Address> lvl1 = callersOf(f);
            out.printf("  callers (%d): %s%n", lvl1.size(), lvl1);
            Set<Address> lvl2 = new LinkedHashSet<>();
            for (Address ca : lvl1) {
                Function cf = getFunctionAt(ca);
                if (cf != null) lvl2.addAll(callersOf(cf));
            }
            out.printf("  callers-of-callers (%d): %s%n", lvl2.size(), lvl2);
            if (doDecomp) {
                DecompileResults res = d.decompileFunction(f, 60, monitor);
                out.println("  --- decompiled ---");
                out.println(res.decompileCompleted()
                        ? res.getDecompiledFunction().getC()
                        : "  (decompile failed: " + res.getErrorMessage() + ")");
            }
        }
        out.close();
    }
}
