// DlcmLatchHunt.java
// Find the regen brake-lamp S-R latch by its shape rather than by data flow.
//
// The spec's flow chart (V4_2 s6.6, p37) is a hysteresis comparator:
//
//     set   when regen_level_Nm > 30
//     reset when regen_level_Nm < 20
//
// Whatever variable holds it, a function implementing that has BOTH thresholds
// as immediates.  Internal torque is 0.1 Nm per count, so the pair is 300/200;
// the Simulink signal is named _Nm, so 30/20 is possible too; and regen is
// negative in the DLCM's sign convention, so -300/-200 must be covered.
//
// Same for the second latch in the same block, on BrakePressure_bar: 5 / 1.
// Brake pressure is received on 0x208 as a raw 12-bit count of unknown scale, so
// that pair is only worth reporting alongside a torque pair, never alone.
//
// Phase 1 scans defined instructions for immediate operands and indexes them by
// containing function -- cheap, no decompiler.
// Phase 2 decompiles only functions holding a candidate pair.
//
// Args: <outpath>
//
// Run: analyzeHeadless ~/ghidra-projects dlcm_tricore \
//        -process coda_dlcm_prog.bin -noanalysis \
//        -postScript DlcmLatchHunt.java <out> \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class DlcmLatchHunt extends GhidraScript {

    // Candidate threshold pairs {set, reset}, with a parallel label array.
    // 30 Nm / 20 Nm in every torque scaling established for this ECU.  Scoping
    // this to the first two was the mistake in the 2026-09-25 first pass: the
    // lamp code need not work in internal counts at all.
    static final long[][] PAIRS = {
        {300, 200},       {-300, -200},
        {30, 20},         {-30, -20},
        {120, 80},        {-120, -80},
        {60, 40},         {-60, -40},
        {2120, 2080},     {1880, 1920},
        {32428, 32328},   {31828, 31928},
    };
    static final String[] LABELS = {
        "internal counts, 0.1 Nm",              "internal counts, negative",
        "whole Nm",                             "whole Nm, negative",
        "0.25 Nm/count",                        "0.25 Nm/count, negative",
        "0.5 Nm/count",                         "0.5 Nm/count, negative",
        "0x312/0x212 raw = Nm*4 + 2000",        "0x312/0x212 raw, negative",
        "0x1C0/DID raw = Nm*10 + 32128",        "0x1C0/DID raw, negative",
    };

    PrintWriter out;

    @Override
    public void run() throws Exception {
        String outPath = (getScriptArgs().length > 0)
                ? getScriptArgs()[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/latch_hunt.txt";
        new File(outPath).getParentFile().mkdirs();
        out = new PrintWriter(new FileWriter(outPath));

        Listing listing = currentProgram.getListing();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        out.println("DLCM regen brake-lamp latch -- threshold-pair hunt");
        out.println("functions defined: " + fnMgr.getFunctionCount());
        out.println();

        // fn -> value -> list of "addr  instruction"
        Map<Function, Map<Long, List<String>>> imms = new HashMap<>();
        Set<Long> wanted = new HashSet<>();
        for (long[] p : PAIRS) { wanted.add(p[0]); wanted.add(p[1]); }

        InstructionIterator it = listing.getInstructions(true);
        long scanned = 0;
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            scanned++;
            Function fn = fnMgr.getFunctionContaining(ins.getAddress());
            if (fn == null) continue;
            for (int op = 0; op < ins.getNumOperands(); op++) {
                for (Object o : ins.getOpObjects(op)) {
                    if (!(o instanceof Scalar s)) continue;
                    long sv = s.getSignedValue();
                    long uv = s.getUnsignedValue();
                    for (long w : wanted) {
                        if (sv == w || uv == w) {
                            imms.computeIfAbsent(fn, k -> new HashMap<>())
                                .computeIfAbsent(w, k -> new ArrayList<>())
                                .add(ins.getAddress() + "  " + ins.toString());
                        }
                    }
                }
            }
        }
        out.println("instructions scanned: " + scanned);
        out.println("functions holding at least one candidate immediate: " + imms.size());
        out.println();

        // Which functions hold a complete pair?
        LinkedHashSet<Function> hits = new LinkedHashSet<>();
        out.println("================================================================");
        out.println("PHASE 1: functions containing BOTH thresholds of a pair");
        out.println("================================================================");
        for (Map.Entry<Function, Map<Long, List<String>>> e : imms.entrySet()) {
            Map<Long, List<String>> m = e.getValue();
            for (int pi = 0; pi < PAIRS.length; pi++) {
                long[] p = PAIRS[pi];
                if (!m.containsKey(p[0]) || !m.containsKey(p[1])) continue;
                hits.add(e.getKey());
                out.printf("%n  %s @%s   pair %d / %d  [%s]%n",
                        e.getKey().getName(), e.getKey().getEntryPoint(), p[0], p[1],
                        LABELS[pi]);
                for (String s : m.get(p[0])) out.println("      set:   " + s);
                for (String s : m.get(p[1])) out.println("      reset: " + s);
            }
        }
        if (hits.isEmpty()) out.println("  none");
        out.println();

        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("PHASE 2: decompilation of the functions above");
        out.println("================================================================");
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        for (Function fn : hits) {
            out.println();
            out.println("---------------------------------------------------------------");
            out.printf("%s @%s   size=%d%n", fn.getName(), fn.getEntryPoint(),
                    fn.getBody().getNumAddresses());
            out.println("---------------------------------------------------------------");
            DecompileResults r = decomp.decompileFunction(fn, 90, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                out.println(r.getDecompiledFunction().getC());
            } else {
                out.println("  [decompile failed: "
                        + (r != null ? r.getErrorMessage() : "null result") + "]");
            }
        }

        out.flush();
        out.close();
        println("DlcmLatchHunt: wrote " + outPath);
    }

}
