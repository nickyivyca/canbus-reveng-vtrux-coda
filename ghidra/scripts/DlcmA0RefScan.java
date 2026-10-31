// DlcmA0RefScan.java
// Scan every instruction in the program for references to a small-data (A0/A1)
// relative offset matching a substring, and print them with their containing
// function. Used to find who writes the SecurityAccess per-level key constants,
// which live at a0-0x4078 + index*4 (RAM) rather than at an absolute address.
//
// Args: <outpath> <comma-separated substrings, e.g. "]-0x407,]-0x408">
//
// Run: analyzeHeadless <projdir> dlcm_tricore -process coda_dlcm_prog.bin \
//        -noanalysis -postScript DlcmA0RefScan.java <out> "]-0x407" \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DlcmA0RefScan extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/a0_refs.txt";
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];
        String[] needles = { "]-0x407" };
        if (args.length > 1 && args[1].length() > 0) needles = args[1].split(",");

        PrintWriter out = new PrintWriter(new FileWriter(outPath));
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();

        out.println("=== A0/A1-relative reference scan ===");
        out.print("needles:");
        for (String s : needles) out.print("  \"" + s + "\"");
        out.println();
        out.println();

        // Make sure the whole content region is disassembled, not just the
        // functions earlier scripts seeded.
        int scanned = 0, hits = 0;
        InstructionIterator it = listing.getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            scanned++;
            String text = ins.toString();
            boolean match = false;
            for (String s : needles) {
                if (text.contains(s.trim())) { match = true; break; }
            }
            if (!match) continue;
            hits++;
            Function f = fm.getFunctionContaining(ins.getAddress());
            String fname = (f == null) ? "-" : f.getName();
            String kind = ins.getFlowType().isCall() ? "call"
                        : (ins.getMnemonicString().startsWith("st") ? "STORE"
                        : (ins.getMnemonicString().startsWith("ld") ? "load"
                        : (ins.getMnemonicString().startsWith("lea") ? "lea" : "other")));
            out.printf("  %08X  %-6s %-40s  in %s%n",
                    ins.getAddress().getOffset(), kind, text, fname);
        }
        out.println();
        out.printf("scanned %d instructions, %d hits%n", scanned, hits);
        out.flush();
        out.close();
        println("Done. " + hits + " hits of " + scanned + " instructions -> " + outPath);
    }
}
