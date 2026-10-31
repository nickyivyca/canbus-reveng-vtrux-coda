// DlcmGpioMap.java
// Enumerate every DLCM digital I/O pin the firmware actually drives or reads.
//
// The whole GPIO layer is three helpers, found by scanning for TriCore port
// registers (DlcmBrakeLamp.java phase 1) and decompiling the hits:
//
//   FUN_800635b8(id, level)  ->  P<n>_OMR   at 0xF0000C04 + port*0x100
//        OMR bits 0-15 = PS (set), 16-31 = PCL (clear); the helper picks
//        bit `pin` for level=1 and bit `pin+16` for level=0.  SET OUTPUT PIN.
//   FUN_8006358c(id)         ->  P<n>_IN    at 0xF0000C24 + port*0x100.  READ INPUT PIN.
//   FUN_800637f4(id, cfg)    ->  P<n>_IOCR* at 0xF0000C10 + ...          CONFIGURE PIN.
//
// In all three, `id` packs the port in bits [7:4] and the pin in bits [3:0].
//
// Why this settles the brake-lamp question: the relay command is connector pin
// C_A3, a low-side output, so it can only reach the world through a call to
// FUN_800635b8 with a constant id.  Enumerating those calls enumerates every
// output the firmware drives.  If the count matches the spec's six static digital
// outputs, the brake lamp is among them; if one is missing, it is not driven.
//
// Args: <outpath>
//
// Run: analyzeHeadless ~/ghidra-projects dlcm_tricore \
//        -process coda_dlcm_prog.bin -noanalysis \
//        -postScript DlcmGpioMap.java <out> \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
import java.util.regex.*;

public class DlcmGpioMap extends GhidraScript {

    static final String[] HELPERS = {
        "FUN_800635b8",   // set output pin   (P_OMR)
        "FUN_8006358c",   // read input pin   (P_IN)
        "FUN_800637f4",   // configure pin    (P_IOCR)
    };
    static final String[] ROLES = {"SET OUTPUT", "READ INPUT", "CONFIGURE"};

    PrintWriter out;
    DecompInterface decomp;

    @Override
    public void run() throws Exception {
        String outPath = (getScriptArgs().length > 0)
                ? getScriptArgs()[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/gpio_map.txt";
        new File(outPath).getParentFile().mkdirs();
        out = new PrintWriter(new FileWriter(outPath));

        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        FunctionManager fnMgr = currentProgram.getFunctionManager();
        out.println("DLCM GPIO map -- every pin the firmware drives or reads");
        out.println();

        // A call to a helper, with whatever literal arguments the decompiler recovered.
        Pattern callPat = Pattern.compile("(FUN_800635b8|FUN_8006358c|FUN_800637f4)\\s*\\(([^;)]*)\\)");

        for (int h = 0; h < HELPERS.length; h++) {
            String name = HELPERS[h];
            Function helper = null;
            for (Function f : fnMgr.getFunctions(true)) {
                if (f.getName().equals(name)) { helper = f; break; }
            }
            out.println("================================================================");
            out.printf("%s  --  %s%n", name, ROLES[h]);
            out.println("================================================================");
            if (helper == null) { out.println("  NOT FOUND"); continue; }

            Set<Function> callers = helper.getCallingFunctions(monitor);
            out.printf("  entry %s   callers: %d%n%n", helper.getEntryPoint(), callers.size());

            // id -> set of "caller  ::  call text"
            Map<String, Set<String>> byId = new TreeMap<>();
            for (Function c : callers) {
                if (monitor.isCancelled()) break;
                DecompileResults r = decomp.decompileFunction(c, 90, monitor);
                if (r == null || !r.decompileCompleted() || r.getDecompiledFunction() == null) {
                    out.printf("  %s @%s  [decompile failed]%n", c.getName(), c.getEntryPoint());
                    continue;
                }
                String code = r.getDecompiledFunction().getC();
                Matcher m = callPat.matcher(code);
                while (m.find()) {
                    if (!m.group(1).equals(name)) continue;
                    String args = m.group(2).trim();
                    String id = args.split(",")[0].trim();
                    byId.computeIfAbsent(id, k -> new TreeSet<>())
                        .add(c.getName() + " @" + c.getEntryPoint() + "   ->   "
                             + m.group(1) + "(" + args + ")");
                }
            }

            for (Map.Entry<String, Set<String>> e : byId.entrySet()) {
                String id = e.getKey();
                out.printf("  id = %s%s%n", id, decodeId(id));
                for (String s : e.getValue()) out.println("        " + s);
            }
            out.println();
        }

        // ---------------------------------------------------------------
        // Full decompilation of every caller of the output setter, so the
        // conditions around each pin write can be read.
        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("FULL DECOMPILATION: callers of the output setter FUN_800635b8");
        out.println("================================================================");
        Function setter = null;
        for (Function f : fnMgr.getFunctions(true)) {
            if (f.getName().equals("FUN_800635b8")) { setter = f; break; }
        }
        if (setter != null) {
            for (Function c : setter.getCallingFunctions(monitor)) {
                out.println();
                out.println("---------------------------------------------------------------");
                out.printf("%s @%s   size=%d%n", c.getName(), c.getEntryPoint(),
                        c.getBody().getNumAddresses());
                out.println("---------------------------------------------------------------");
                DecompileResults r = decomp.decompileFunction(c, 90, monitor);
                if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                    out.println(r.getDecompiledFunction().getC());
                } else {
                    out.println("  [decompile failed]");
                }
            }
        }

        out.flush();
        out.close();
        println("DlcmGpioMap: wrote " + outPath);
    }

    /** Decode a literal pin id into port/pin, when it is a literal at all. */
    static String decodeId(String id) {
        try {
            long v;
            String t = id.trim();
            if (t.startsWith("0x") || t.startsWith("0X")) v = Long.parseLong(t.substring(2), 16);
            else v = Long.parseLong(t);
            return String.format("   ->  P%d.%d", (v & 0xF0) >> 4, v & 0x0F);
        } catch (NumberFormatException e) {
            return "   (not a literal -- computed at runtime)";
        }
    }
}
