// @category Analysis
// Print the EXISTING instruction listing over an address range, non-destructively.
//
// Why this exists: DlcmDisasmRange.java clears and re-disassembles, which is the right
// tool for checking alignment of a suspect region but the wrong one for asking "does the
// code at 0x80055A9A fall through into FUN_80055AA0, or does it return?".  That question
// only needs to read what Ghidra already decoded, and clearing the listing to answer it
// risks losing correct boundaries in a band that is already known to be fragmented
// (the ECM2 band 0x80050000-0x80056000).
//
// Marks each instruction that is a function entry, and each flow terminator, so a
// fallthrough across a recorded function boundary is visible at a glance.
//
// Args: <outpath> <lo> <hi>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DlcmListRange extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Address lo = toAddr(a[1]), hi = toAddr(a[2]);

        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();

        out.println("=== existing listing " + lo + " .. " + hi + " (read-only) ===");
        out.println();
        InstructionIterator it = listing.getInstructions(new AddressSet(lo, hi), true);
        int n = 0;
        Address prevEnd = null;
        while (it.hasNext()) {
            Instruction ins = it.next();
            Address at = ins.getAddress();
            if (prevEnd != null && !at.equals(prevEnd)) {
                out.printf("  ---- gap: no instruction from %s to %s ----%n", prevEnd, at);
            }
            Function f = fm.getFunctionAt(at);
            String tag = (f != null) ? ("  <== ENTRY " + f.getName()) : "";
            String term = ins.getFlowType().isTerminal() ? "  [TERMINATOR]" : "";
            String call = ins.getFlowType().isCall() ? "  [call]" : "";
            out.printf("  %s  %-40s%s%s%s%n", at, ins.toString(), term, call, tag);
            prevEnd = at.add(ins.getLength());
            n++;
        }
        out.println();
        out.println("  instructions listed: " + n);
        out.flush();
        out.close();
        println("DlcmListRange: " + n + " instructions -> " + a[0]);
    }
}
