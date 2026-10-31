// DlcmBandDecompile.java
// TriCore. Decompile every function whose entry point lies in [lo, hi].
// Used to dump the DLCM's CAN signal accessor band (0x800803FA-0x80080B4A, 120 tiny
// getters), each of which reads one field out of a per-message RX buffer.
// Args: <outpath> <lo hex> <hi hex>
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DlcmBandDecompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        AddressSpace as = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address lo = as.getAddress(a[1]), hi = as.getAddress(a[2]);
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(lo, true);
        int n = 0;
        while (it.hasNext()) {
            Function f = it.next();
            if (f.getEntryPoint().compareTo(hi) > 0) break;
            n++;
            out.printf("======== 0x%08X %s size=%d ========%n",
                    f.getEntryPoint().getOffset(), f.getName(), f.getBody().getNumAddresses());
            DecompileResults r = dec.decompileFunction(f, 60, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null)
                out.println(r.getDecompiledFunction().getC());
            else
                out.println("  [decompile failed]");
        }
        out.printf("%n%d functions%n", n);
        out.close();
        dec.dispose();
        println("n=" + n);
    }
}
