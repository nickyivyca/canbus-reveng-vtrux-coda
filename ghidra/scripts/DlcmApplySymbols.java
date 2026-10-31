// @category Analysis
// Apply the repo-side symbol map to the Ghidra database.
//
// WHY THIS EXISTS. Measured 2026-10-07 with DlcmSymbolCensus: 2960 functions,
// 0 named, 0 labels, 0 comments. Every session opened the project, saw
// FUN_80056c20, and re-derived what the notes already recorded -- four times in
// one session (worklog 6H.1, 6H.26, 6H.29, 6H.32). Naming the functions makes a
// re-derivation visible the moment a decompile is read.
//
// DIRECTION OF TRUTH. The CSV in the repo is the source of truth; the Ghidra
// database is DERIVED and disposable. That is forced by the environment: Ghidra
// projects must live on a local path (tools-reference.md), so the database does
// not sync between machines and anything recorded only there is stranded -- the
// exact failure that produced dlcm-dtcs-investigation.md section 2b. Never hand-edit
// names in the GUI and expect them to survive; add the row to the CSV and re-run
// this script.
//
// FRAGMENTS. The ECM2 band is pervasively fragmented because FUN_80082EAA is
// wrongly marked "does not return" (worklog 6H.15), so Ghidra splits a function
// at every redundancy trap. Rows with kind=fragment are NOT functions. They are
// named with a _frag suffix and carry a plate comment naming their real parent,
// because a fragment label is not a stable identifier -- the same region was
// FUN_80050980 in one run and FUN_800509A6 in the next (worklog 6H.32b).
//
// Program-agnostic: also used for the HVAC (coda_hvac, hvac_symbols.csv), with an
// explicit <outpath>.
//
// Args: <csvpath> [<outpath>]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmApplySymbols extends GhidraScript {

    // Minimal CSV field splitter: handles "quoted, fields" with embedded commas.
    private static List<String> splitCsv(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean q = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') {
                if (q && i + 1 < line.length() && line.charAt(i + 1) == '"') {
                    cur.append('"');
                    i++;
                } else {
                    q = !q;
                }
            } else if (c == ',' && !q) {
                out.add(cur.toString());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        out.add(cur.toString());
        return out;
    }

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        if (a.length < 1 || a[0].isEmpty()) {
            println("ERROR: need <csvpath>");
            return;
        }
        String outPath = (a.length > 1 && !a[1].isEmpty()) ? a[1]
                : System.getProperty("user.home")
                  + "/ghidra-projects/dlcm_export/apply_symbols.txt";
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        BufferedReader br = new BufferedReader(new FileReader(a[0]));
        String header = br.readLine();
        List<String> cols = splitCsv(header == null ? "" : header);
        int iAddr = cols.indexOf("address"), iName = cols.indexOf("name");
        int iKind = cols.indexOf("kind"), iEnd = cols.indexOf("end");
        int iRole = cols.indexOf("role"), iSrc = cols.indexOf("source");
        int iConf = cols.indexOf("confidence");
        if (iAddr < 0 || iName < 0) {
            println("ERROR: csv missing address/name columns");
            br.close();
            out.close();
            return;
        }

        FunctionManager fm = currentProgram.getFunctionManager();
        SymbolTable st = currentProgram.getSymbolTable();
        AddressFactory af = currentProgram.getAddressFactory();
        Listing lst = currentProgram.getListing();

        int named = 0, labelled = 0, commented = 0, missing = 0, rows = 0;
        String line;
        out.println("=== apply symbol map ===");
        out.println("csv: " + a[0]);
        out.println();
        while ((line = br.readLine()) != null) {
            if (line.trim().isEmpty()) continue;
            List<String> f = splitCsv(line);
            if (f.size() <= iName) continue;
            rows++;
            String as = f.get(iAddr).trim();
            String nm = f.get(iName).trim();
            String kind = iKind >= 0 && f.size() > iKind ? f.get(iKind).trim() : "";
            String end = iEnd >= 0 && f.size() > iEnd ? f.get(iEnd).trim() : "";
            String role = iRole >= 0 && f.size() > iRole ? f.get(iRole).trim() : "";
            String src = iSrc >= 0 && f.size() > iSrc ? f.get(iSrc).trim() : "";
            String conf = iConf >= 0 && f.size() > iConf ? f.get(iConf).trim() : "";
            if (as.startsWith("0x") || as.startsWith("0X")) as = as.substring(2);

            Address addr;
            try {
                addr = af.getDefaultAddressSpace().getAddress(Long.parseLong(as, 16));
            } catch (Exception e) {
                out.println("  BAD ADDRESS  " + f.get(iAddr) + "  (" + nm + ")");
                missing++;
                continue;
            }

            // The comment is the durable part: it carries the span, the
            // provenance and the confidence, so a reader never has to trust the
            // name alone.
            StringBuilder cmt = new StringBuilder();
            cmt.append(nm).append("\n");
            if (!kind.isEmpty()) cmt.append("kind: ").append(kind).append("\n");
            if (!end.isEmpty()) cmt.append("span: ").append(f.get(iAddr).trim())
                                   .append("..").append(end).append("\n");
            if (!conf.isEmpty()) cmt.append("confidence: ").append(conf).append("\n");
            if (!src.isEmpty()) cmt.append("source: ").append(src).append("\n");
            if (!role.isEmpty()) cmt.append("\n").append(role).append("\n");
            cmt.append("\n[generated by DlcmApplySymbols from " + new File(a[0]).getName() + " -- "
                       + "edit the CSV, not the database]");

            Function fn = fm.getFunctionAt(addr);
            if (fn != null) {
                fn.setName(nm, SourceType.USER_DEFINED);
                named++;
                out.println("  fn    " + addr + "  " + nm);
            } else {
                // Not a function entry (common for fragments and data): a label
                // still makes the address self-describing in every listing.
                st.createLabel(addr, nm, SourceType.USER_DEFINED);
                labelled++;
                out.println("  label " + addr + "  " + nm);
            }
            lst.setComment(addr, CodeUnit.PLATE_COMMENT, cmt.toString());
            commented++;
        }
        br.close();

        out.println();
        out.println("rows read        : " + rows);
        out.println("functions named  : " + named);
        out.println("labels created   : " + labelled);
        out.println("comments applied : " + commented);
        out.println("bad addresses    : " + missing);
        out.close();
        println("applied " + named + " names, " + labelled + " labels, "
                + commented + " comments -> " + outPath);
    }
}
