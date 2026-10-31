// @category Analysis
// Diagnostic: print the stored PPAGE register value at given addresses (does the
// per-page PPAGE context set by HvacFlowSeed actually persist?).
// Args: <outpath> <comma-separated hex addresses>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.lang.Register;
import java.io.*;

public class HvacPpageProbe extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Register r = currentProgram.getRegister("PPAGE");
        out.println("register " + r + " addr=" + r.getAddress() + " processorContext=" + r.isProcessorContext());
        for (String s : a[1].split(",")) {
            out.println(s + " value=" + currentProgram.getProgramContext().getValue(r, toAddr(s), false)
                    + " default=" + currentProgram.getProgramContext().getDefaultValue(r, toAddr(s)));
        }
        out.close();
    }
}
