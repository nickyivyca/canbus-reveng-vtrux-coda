// DlcmBrakeLamp.java
// Trace the DLCM's Regen Brake Lamp Relay output (connector pin C_A3,
// "Brake_lamp_control_LS", low-side, 0.2 A) from the two inputs the functional
// spec says drive it.
//
// Spec (DLCM Functional Requirements V4_2 s6.6, flow chart p37):
//
//   RegenBrakeLampRelayCommand =
//        SR(set: regen_level_Nm > 30, reset: regen_level_Nm < 20)
//     OR (ManualBrakeLampRelay_FaultOpen AND BrakeSwitch)
//     OR (BrakeSwitch_FaultOpen AND BrakePressure_Valid
//         AND SR(set: BrakePressure_bar > 5, reset: < 1))
//
// Inputs to work back from:
//   B_F1  Brake_switch_in  -- digital, published as BrakeSW on 0x212/0x315 by
//         FUN_80080C14 from DAT_d00069E0 & 3 (CODA-D-CAN.dbc CM_ SG_ 530 BrakeSW)
//   BrakePressure / BrakePressure_Valid -- received on 0x208 from the ESC, read
//         through the accessor band 0x800803FA-0x80080B4A
//
// The output itself is a GPIO pin, so it never appears on CAN.  On TriCore the
// port registers live in peripheral space, so the driver is found by looking for
// stores to peripheral addresses rather than by following data flow.
//
// Phases:
//   1  peripheral-address census -- every instruction touching peripheral space,
//      grouped by function.  Candidate GPIO / output drivers.
//   2  functions referencing the brake-switch RAM mirror (0xD00069E0 and its
//      immediate neighbours).
//   3  accessor-band getters whose callers also appear in phase 1 or 2.
//   4  decompilation of everything that survived, for reading.
//
// Args: <outpath>
//
// Run: analyzeHeadless ~/ghidra-projects dlcm_tricore \
//        -process coda_dlcm_prog.bin -noanalysis \
//        -postScript DlcmBrakeLamp.java <out> \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmBrakeLamp extends GhidraScript {

    // TriCore peripheral space.  The DLCM's RAM mirror block is 0xD00069xx, so the
    // CPU is a TC17xx-class part whose ports sit in 0xF000_0000-0xF00F_FFFF.
    static final long PERIPH_LO = 0xF0000000L;
    static final long PERIPH_HI = 0xF00FFFFFL;

    // Brake switch mirror, per CODA-D-CAN.dbc CM_ SG_ 530.
    static final long BRAKE_SW_VAR = 0xD00069E0L;
    static final long BRAKE_SW_LO = 0xD00069D0L;
    static final long BRAKE_SW_HI = 0xD00069F0L;

    // RX accessor band (coda-dlcm-decompile-notes.md, "The accessor band").
    static final long BAND_LO = 0x800803FAL;
    static final long BAND_HI = 0x80080B4AL;

    PrintWriter out;
    DecompInterface decomp;

    @Override
    public void run() throws Exception {
        String outPath = (getScriptArgs().length > 0)
                ? getScriptArgs()[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/brake_lamp.txt";
        new File(outPath).getParentFile().mkdirs();
        out = new PrintWriter(new FileWriter(outPath));

        decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        Listing listing = currentProgram.getListing();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        out.println("DLCM regen brake lamp relay -- code trace");
        out.println("program: " + currentProgram.getName());
        out.println("language: " + currentProgram.getLanguageID());
        out.println("functions defined: " + fnMgr.getFunctionCount());
        out.println();

        // ---------------------------------------------------------------
        // Phase 1: every instruction that names a peripheral-space address.
        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("PHASE 1: peripheral-space accesses (0x%08X-0x%08X)"
                .formatted(PERIPH_LO, PERIPH_HI));
        out.println("================================================================");

        // fn entry -> (periph addr -> sample instruction text)
        Map<Function, Map<Long, String>> periphByFn = new LinkedHashMap<>();
        Map<Long, Integer> periphHist = new TreeMap<>();
        int noFn = 0;

        InstructionIterator instrs = listing.getInstructions(true);
        while (instrs.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = instrs.next();
            Set<Long> hits = new LinkedHashSet<>();

            for (int op = 0; op < ins.getNumOperands(); op++) {
                for (Object o : ins.getOpObjects(op)) {
                    long v = Long.MIN_VALUE;
                    if (o instanceof Scalar s) {
                        v = s.getUnsignedValue();
                        // movh.a %aN, #0xF000 builds the high half of a port address
                        if (v >= 0xF000L && v <= 0xF00FL) {
                            hits.add(v << 16);
                            continue;
                        }
                    } else if (o instanceof Address a) {
                        v = a.getOffset();
                    }
                    if (v >= PERIPH_LO && v <= PERIPH_HI) hits.add(v);
                }
            }
            // references Ghidra resolved for us (covers ABS-format absolute stores)
            for (Reference r : ins.getReferencesFrom()) {
                long v = r.getToAddress().getOffset();
                if (v >= PERIPH_LO && v <= PERIPH_HI) hits.add(v);
            }
            if (hits.isEmpty()) continue;

            Function fn = fnMgr.getFunctionContaining(ins.getAddress());
            if (fn == null) { noFn++; continue; }
            Map<Long, String> m = periphByFn.computeIfAbsent(fn, k -> new TreeMap<>());
            for (long h : hits) {
                m.putIfAbsent(h, ins.getAddress() + "  " + ins.toString());
                periphHist.merge(h, 1, Integer::sum);
            }
        }

        out.printf("functions touching peripheral space: %d   (hits outside any function: %d)%n%n",
                periphByFn.size(), noFn);
        for (Map.Entry<Function, Map<Long, String>> e : periphByFn.entrySet()) {
            out.printf("  %s @%s   %d distinct peripheral address(es)%n",
                    e.getKey().getName(), e.getKey().getEntryPoint(), e.getValue().size());
            for (Map.Entry<Long, String> h : e.getValue().entrySet()) {
                out.printf("      0x%08X   %s%n", h.getKey(), h.getValue());
            }
        }
        out.println();
        out.println("  --- peripheral address histogram (address, referencing instructions) ---");
        for (Map.Entry<Long, Integer> e : periphHist.entrySet()) {
            out.printf("      0x%08X  %d%n", e.getKey(), e.getValue());
        }
        out.println();

        // ---------------------------------------------------------------
        // Phase 2: consumers of the brake-switch RAM mirror.
        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("PHASE 2: references to the brake-switch mirror 0x%08X (+/- window)"
                .formatted(BRAKE_SW_VAR));
        out.println("================================================================");
        Set<Function> brakeFns = new LinkedHashSet<>();
        for (long a = BRAKE_SW_LO; a <= BRAKE_SW_HI; a++) {
            Address addr = toAddr(a);
            for (Reference r : getReferencesTo(addr)) {
                Function fn = fnMgr.getFunctionContaining(r.getFromAddress());
                out.printf("  0x%08X <- %s  [%s]  in %s%n", a, r.getFromAddress(),
                        r.getReferenceType(),
                        fn != null ? fn.getName() + " @" + fn.getEntryPoint() : "(none)");
                if (fn != null) brakeFns.add(fn);
            }
        }
        out.printf("%n  distinct functions: %d%n%n", brakeFns.size());

        // ---------------------------------------------------------------
        // Phase 3: accessor-band getters and who calls them.
        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("PHASE 3: accessor-band getters, and callers that also appear above");
        out.println("================================================================");
        Set<Function> interesting = new LinkedHashSet<>();
        interesting.addAll(periphByFn.keySet());
        interesting.addAll(brakeFns);

        FunctionIterator fit = fnMgr.getFunctions(true);
        int bandCount = 0;
        while (fit.hasNext()) {
            Function g = fit.next();
            long ep = g.getEntryPoint().getOffset();
            if (ep < BAND_LO || ep > BAND_HI) continue;
            bandCount++;
            Set<Function> callers = g.getCallingFunctions(monitor);
            List<String> flagged = new ArrayList<>();
            for (Function c : callers) if (interesting.contains(c)) flagged.add(c.getName());
            if (!flagged.isEmpty()) {
                out.printf("  getter %s @%s  called by INTERESTING: %s%n",
                        g.getName(), g.getEntryPoint(), flagged);
            }
        }
        out.printf("%n  getters in band: %d%n%n", bandCount);

        // ---------------------------------------------------------------
        // Phase 4: decompile the survivors.
        // ---------------------------------------------------------------
        out.println("================================================================");
        out.println("PHASE 4: decompilation of candidate functions");
        out.println("================================================================");
        for (Function fn : interesting) {
            out.println();
            out.println("---------------------------------------------------------------");
            out.printf("%s @%s   size=%d%n", fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses());
            out.println("---------------------------------------------------------------");
            DecompileResults res = decomp.decompileFunction(fn, 90, monitor);
            if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("  [decompile failed: "
                        + (res != null ? res.getErrorMessage() : "null result") + "]");
            }
        }

        out.flush();
        out.close();
        println("DlcmBrakeLamp: wrote " + outPath);
    }
}
