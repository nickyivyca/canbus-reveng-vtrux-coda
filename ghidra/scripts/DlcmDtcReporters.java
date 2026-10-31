// DlcmDtcReporters.java
// Enumerate every DTC event this firmware build can actually raise.
//
// The DLCM reports a diagnostic result through a single function with the event
// id as a literal first argument, e.g. in FUN_80077b10:
//
//     uVar4 = FUN_8007f6c8(0x19, condition, 1, 1, 1);
//
// The event id indexes the DTC event table in CAL at 0xA002451F (stride 6), which
// artifacts/dtc_event_table.py already decoded.  Event 18 is B2100 "Regenerative
// brake lamp relay circuit" and event 19 is B2101 "Reverse lamp relay circuit".
//
// This settles a question no amount of calibration reading can: whether the regen
// brake lamp relay is diagnosed -- and so driven -- by this build at all, or only
// by the specification.  A CAL byte can disable a DTC that the code still raises;
// only the code says whether the call site exists.
//
// Args: <outpath> [reporter function names, comma separated]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class DlcmDtcReporters extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = (args.length > 0 && !args[0].isEmpty())
                ? args[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/dtc_reporters.txt";
        String[] names = (args.length > 1 && !args[1].isEmpty())
                ? args[1].split(",")
                : new String[] { "FUN_8007f6c8" };
        new File(outPath).getParentFile().mkdirs();
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        FunctionManager fnMgr = currentProgram.getFunctionManager();
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        for (String name : names) {
            name = name.trim();
            Function target = null;
            for (Function f : fnMgr.getFunctions(true)) {
                if (f.getName().equals(name)) { target = f; break; }
            }
            out.println("================================================================");
            out.println("call sites of " + name);
            out.println("================================================================");
            if (target == null) { out.println("  NOT FOUND"); out.println(); continue; }

            Pattern p = Pattern.compile(Pattern.quote(name) + "\\s*\\(([^;]*?)\\)");
            Set<Function> callers = target.getCallingFunctions(monitor);
            out.printf("  entry %s   callers: %d%n%n", target.getEntryPoint(), callers.size());

            // first-arg literal -> call sites
            Map<Long, Set<String>> byEvent = new TreeMap<>();
            List<String> nonLiteral = new ArrayList<>();
            for (Function c : callers) {
                if (monitor.isCancelled()) break;
                DecompileResults r = decomp.decompileFunction(c, 90, monitor);
                if (r == null || !r.decompileCompleted() || r.getDecompiledFunction() == null) {
                    nonLiteral.add(c.getName() + " @" + c.getEntryPoint() + "  [decompile failed]");
                    continue;
                }
                Matcher m = p.matcher(r.getDecompiledFunction().getC());
                while (m.find()) {
                    String a0 = m.group(1).split(",")[0].trim();
                    Long ev = parseLit(a0);
                    String site = c.getName() + " @" + c.getEntryPoint()
                                + "   ->   " + name + "(" + m.group(1).trim() + ")";
                    if (ev == null) nonLiteral.add(site);
                    else byEvent.computeIfAbsent(ev, k -> new TreeSet<>()).add(site);
                }
            }

            out.println("  --- literal event ids ---");
            for (Map.Entry<Long, Set<String>> e : byEvent.entrySet()) {
                out.printf("  event %3d (0x%02X)%n", e.getKey(), e.getKey());
                for (String s : e.getValue()) out.println("        " + s);
            }
            out.println();
            out.println("  distinct literal event ids: " + byEvent.size());
            out.print("  ids: ");
            for (Long k : byEvent.keySet()) out.print(k + " ");
            out.println();
            out.println();
            out.println("  --- call sites whose event id is not a literal ---");
            for (String s : nonLiteral) out.println("        " + s);
            out.println();
        }

        out.flush();
        out.close();
        println("DlcmDtcReporters: wrote " + outPath);
    }

    static Long parseLit(String s) {
        try {
            s = s.trim();
            if (s.startsWith("0x") || s.startsWith("0X")) return Long.parseLong(s.substring(2), 16);
            return Long.parseLong(s);
        } catch (Exception e) { return null; }
    }
}
