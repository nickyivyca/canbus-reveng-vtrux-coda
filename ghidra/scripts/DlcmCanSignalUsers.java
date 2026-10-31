// DlcmCanSignalUsers.java
// TriCore. The DLCM's CAN payloads are not touched directly by application code: the
// signal pool at a0-0x3a85 is reached only through two accessors,
//   FUN_800685C4(buf, sig)  -- TX publish  (sig & 0x8000 clear, 12-byte signal records)
//   FUN_800686D8(buf, sig)  -- RX fetch    (sig & 0x8000 set,    8-byte signal records)
// This script finds every call to them, recovers the constant signal index from the
// preceding instructions, and names the containing function -- which is the functional
// element that produces or consumes that CAN message.
//
// Args: <outpath> [comma-separated accessor addresses] [decompile callers 1|0]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class DlcmCanSignalUsers extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/can_signal_users.txt";
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];
        long[] accessors = { 0x800685C4L, 0x800686D8L };
        if (args.length > 1 && args[1].length() > 0) {
            String[] p = args[1].split(",");
            accessors = new long[p.length];
            for (int i = 0; i < p.length; i++)
                accessors[i] = Long.parseLong(p[i].trim().replaceFirst("^0[xX]", ""), 16);
        }
        boolean decomp = args.length < 3 || args[2].trim().equals("1");

        PrintWriter out = new PrintWriter(new FileWriter(outPath));
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager rm = currentProgram.getReferenceManager();
        AddressSpace as = currentProgram.getAddressFactory().getDefaultAddressSpace();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        LinkedHashSet<Function> callers = new LinkedHashSet<>();
        for (long acc : accessors) {
            Address target = as.getAddress(Long.toHexString(acc));
            out.printf("%n=== callers of 0x%08X ===%n", acc);
            out.println("  call site   sig   caller");
            ReferenceIterator it = rm.getReferencesTo(target);
            List<String> rows = new ArrayList<>();
            while (it.hasNext()) {
                Reference r = it.next();
                if (!r.getReferenceType().isCall()) continue;
                Address site = r.getFromAddress();
                Function f = fm.getFunctionContaining(site);
                if (f != null) callers.add(f);
                String sig = "?";
                Instruction ins = listing.getInstructionAt(site);
                for (int back = 0; back < 12 && ins != null; back++) {
                    ins = ins.getPrevious();
                    if (ins == null) break;
                    String m = ins.getMnemonicString();
                    if (!(m.equals("mov") || m.equals("mov.u"))) continue;
                    Object[] ops = ins.getOpObjects(0);
                    if (ops.length == 0 || !ops[0].toString().equals("d4")) continue;
                    Object[] v = ins.getOpObjects(1);
                    if (v.length > 0 && v[0] instanceof Scalar) {
                        sig = String.format("0x%X", ((Scalar) v[0]).getUnsignedValue());
                        break;
                    }
                }
                rows.add(String.format("  0x%08X  %-6s %s", site.getOffset(), sig,
                        f == null ? "-" : f.getName() + " @0x" + f.getEntryPoint()));
            }
            Collections.sort(rows);
            for (String s : rows) out.println(s);
            out.println("  (" + rows.size() + " call sites)");
        }

        if (decomp) {
            out.println("\n\n=== CALLER DECOMPILATIONS (" + callers.size() + ") ===");
            for (Function f : callers) {
                out.printf("%n%n================ %s @0x%08X size=%d ================%n",
                        f.getName(), f.getEntryPoint().getOffset(),
                        f.getBody().getNumAddresses());
                DecompileResults res = dec.decompileFunction(f, 120, monitor);
                if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null)
                    out.println(res.getDecompiledFunction().getC());
                else
                    out.println("  [decompile failed]");
            }
        }
        out.flush();
        out.close();
        dec.dispose();
        println("Done -> " + outPath);
    }
}
