// DlcmSpanDecompile.java -- decompile a function over its TRUE ret-to-ret span.
// Run ONLY on a throwaway COPY of dlcm_tricore, with -readOnly (it rewrites function boundaries).
// Ghidra marks FUN_80082EAA (redundancy-mismatch trap) no-return and splits functions at every
// call to it.  This clears no-return on the given trap(s), removes every function whose entry
// lies inside [start, end], creates one function at start with body start..end, decompiles it.
// Args: <outpath> <start> <end> [<trap,trap,...>]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.SourceType;
import java.io.*;
import java.util.*;

public class DlcmSpanDecompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        // GUARD: this rewrites function boundaries.  Refuse to run on the shared project location.
        String loc = state.getProject().getProjectLocator().getLocation();
        if (new File(loc).getCanonicalPath().equals(new File(System.getProperty("user.home"), "ghidra-projects").getCanonicalPath())) {
            printerr("REFUSED: project is in the shared ~/ghidra-projects; copy it to a scratch dir first");
            return;
        }
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Address s = toAddr(a[1].replace("0x", "")), e = toAddr(a[2].replace("0x", ""));
        String traps = a.length > 3 ? a[3] : "80082EAA";
        for (String t : traps.split(",")) {
            Function f = getFunctionAt(toAddr(t.replace("0x", "")));
            if (f != null) { f.setNoReturn(false); out.println("// no-return cleared: " + f.getName()); }
        }
        // re-flow call fallthroughs that were cut
        AddressSet body = new AddressSet(s, e);
        List<Function> kill = new ArrayList<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(body, true)) kill.add(f);
        for (Function f : kill) { out.println("// removed " + f.getName()); removeFunction(f); }
        AddressSetView un = currentProgram.getListing().getUndefinedRanges(body, false, monitor);
        out.println("// undefined inside span: " + un);
        Function fn = createFunction(s, "Span_" + a[1]);
        if (fn == null) { out.println("createFunction FAILED"); out.close(); return; }
        fn.setBody(body);
        out.println("// body " + fn.getBody());
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        DecompileResults r = d.decompileFunction(fn, 300, monitor);
        out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : ("FAILED " + r.getErrorMessage()));
        out.close();
    }
}
