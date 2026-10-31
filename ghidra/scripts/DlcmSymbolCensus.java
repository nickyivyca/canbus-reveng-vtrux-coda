// @category Analysis
// Census of USER-APPLIED knowledge in the Ghidra database, as opposed to
// knowledge that lives only in notes files and loose .txt dumps.
//
// Why this exists: on 2026-10-07 the user asked whether the decompiled structure
// is tracked in something repeatably readable or whether every function has to be
// re-derived by hand. Answering that needs a measurement, not an impression:
// how many functions carry a real name rather than Ghidra's FUN_<addr>, how many
// data addresses carry a label rather than DAT_<addr>, and how many comments
// exist. A near-zero count means the database holds no accumulated knowledge and
// every session starts from raw addresses.
//
// Args: <outpath>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class DlcmSymbolCensus extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String outPath = (a.length > 0 && a[0].length() > 0) ? a[0]
                : System.getProperty("user.home")
                  + "/ghidra-projects/dlcm_export/symbol_census.txt";
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        FunctionManager fm = currentProgram.getFunctionManager();
        int fnTotal = 0, fnNamed = 0;
        StringBuilder named = new StringBuilder();
        for (Function f : fm.getFunctions(true)) {
            fnTotal++;
            String n = f.getName();
            if (!n.startsWith("FUN_") && !n.startsWith("thunk_FUN_")) {
                fnNamed++;
                named.append("    ").append(f.getEntryPoint()).append("  ")
                     .append(n).append("\n");
            }
        }

        SymbolTable st = currentProgram.getSymbolTable();
        int symUser = 0, symDefault = 0;
        StringBuilder labels = new StringBuilder();
        for (Symbol s : st.getAllSymbols(false)) {
            if (s.getSource() == SourceType.USER_DEFINED) {
                symUser++;
                if (symUser <= 80) {
                    labels.append("    ").append(s.getAddress()).append("  ")
                          .append(s.getName()).append("\n");
                }
            } else {
                symDefault++;
            }
        }

        // Comments are the other place a finding can be durably recorded.
        int cmt = 0;
        Listing lst = currentProgram.getListing();
        AddressIterator it = lst.getCommentAddressIterator(
                currentProgram.getMemory(), true);
        while (it.hasNext()) { it.next(); cmt++; }

        out.println("=== Ghidra database knowledge census ===");
        out.println("program: " + currentProgram.getName());
        out.println();
        out.println("functions total              : " + fnTotal);
        out.println("functions with a REAL name   : " + fnNamed);
        out.println("functions still FUN_<addr>   : " + (fnTotal - fnNamed));
        out.println();
        out.println("USER_DEFINED symbols         : " + symUser);
        out.println("auto/default symbols         : " + symDefault);
        out.println();
        out.println("addresses carrying a comment : " + cmt);
        out.println();
        out.println("--- named functions ---");
        out.print(named.length() == 0 ? "    (none)\n" : named.toString());
        out.println();
        out.println("--- user-defined labels (first 80) ---");
        out.print(labels.length() == 0 ? "    (none)\n" : labels.toString());
        out.close();
        println("census -> " + outPath);
    }
}
