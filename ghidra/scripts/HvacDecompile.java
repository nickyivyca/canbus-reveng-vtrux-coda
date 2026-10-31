// @category Analysis
// Decompile the functions at (or containing) each given address in the coda_hvac
// program and write the C, with the function's page and its callers. The general
// "decompile these addresses" runner for the HVAC (cf. DlcmSecurityAccess.java).
// Args: <outpath> <comma-separated hex global addresses> [timeoutSeconds]
import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class HvacDecompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        int timeout = a.length > 2 ? Integer.parseInt(a[2]) : 60;
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        FunctionManager fm = currentProgram.getFunctionManager();
        for (String s : a[1].split(",")) {
            Address at = toAddr(s);
            Function f = fm.getFunctionContaining(at);
            out.println("================================================================");
            if (f == null) {
                out.println("no function contains " + at);
                continue;
            }
            out.printf("%s @ %s  page %02X  body %d bytes%n", f.getName(), f.getEntryPoint(),
                    (f.getEntryPoint().getOffset() >> 14) & 0xFF, f.getBody().getNumAddresses());
            StringBuilder cs = new StringBuilder();
            for (Reference r : currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint())) {
                Function c = fm.getFunctionContaining(r.getFromAddress());
                cs.append(" ").append(r.getFromAddress()).append(c != null ? "(" + c.getName() + ")" : "");
            }
            out.println("callers/refs:" + cs);
            DecompileResults res = di.decompileFunction(f, timeout, monitor);
            if (res.decompileCompleted()) out.println(res.getDecompiledFunction().getC());
            else out.println("DECOMPILE FAILED: " + res.getErrorMessage());
        }
        di.dispose();
        out.close();
    }
}
