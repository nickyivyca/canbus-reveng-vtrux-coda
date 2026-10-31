// DlcmCallCensus.java
//
// TriCore. Find the DEM / fault-reporting core of the DLCM by call census.
//
// Rationale: in an AUTOSAR-style stack the event reporter -- Dem_ReportErrorStatus
// (eventId, status) or an equivalent SetFault(id, state) -- is called from every
// monitor in the application, so it is among the most-referenced functions in the
// image, and its first argument is a small constant event ID at nearly every call
// site. Both properties are cheap to measure and together they are a much stronger
// signature than any byte pattern.
//
// Written 2026-09-23 while tracing what sets DLCM P3115
// ("System safety critical disable DLCM fault level 2").
//
// Output:
//   1. Top functions by distinct caller count.
//   2. For each address given in arg[1] (or the auto-picked top candidates), every
//      call site with the constant loaded into d4 / d5 immediately before the call.
//
// TriCore calling convention: first data args in d4, d5, d6, d7; first address args
// in a4, a5, a6, a7. A monitor calling SetFault(id, state) therefore shows up as
// `mov d4,#<id>` / `mov d5,#<state>` in the few instructions before the call.
//
// args: <outfile> [comma-separated hex addrs to detail] [topN]
//@category DLCM
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.io.PrintWriter;
import java.util.*;

public class DlcmCallCensus extends GhidraScript {

    PrintWriter out;
    FunctionManager fnMgr;
    Listing listing;
    ReferenceManager refMgr;

    /** How far back from a call site to look for the argument setup. */
    static final int LOOKBACK = 14;

    Address addr(long v) {
        return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v);
    }

    /** Call sites (not distinct callers) targeting this entry point. */
    List<Address> callSites(Address entry) {
        List<Address> sites = new ArrayList<>();
        ReferenceIterator it = refMgr.getReferencesTo(entry);
        while (it.hasNext()) {
            Reference r = it.next();
            if (r.getReferenceType().isCall()) sites.add(r.getFromAddress());
        }
        return sites;
    }

    /**
     * Walk backwards from a call site collecting the last constant written to each
     * of d4..d7 before the call. Stops at a label/branch target boundary so we do
     * not read constants from a different path.
     */
    Map<String, Long> argConstants(Address callSite) {
        Map<String, Long> found = new LinkedHashMap<>();
        Instruction ins = listing.getInstructionAt(callSite);
        if (ins == null) return found;
        for (int i = 0; i < LOOKBACK; i++) {
            ins = ins.getPrevious();
            if (ins == null) break;
            // Do not walk past an incoming branch target -- different path.
            if (i > 0 && refMgr.hasReferencesTo(ins.getAddress())) {
                boolean jumpTarget = false;
                ReferenceIterator it = refMgr.getReferencesTo(ins.getAddress());
                while (it.hasNext()) {
                    if (it.next().getReferenceType().isJump()) { jumpTarget = true; break; }
                }
                if (jumpTarget) break;
            }
            Object[] res = ins.getResultObjects();
            Object[] inp = ins.getInputObjects();
            if (res.length != 1 || !(res[0] instanceof Register)) continue;
            String rn = ((Register) res[0]).getName();
            if (!rn.matches("d[4-7]")) continue;
            if (found.containsKey(rn)) continue;          // keep the nearest write
            Long konst = null;
            for (Object o : inp) {
                if (o instanceof Scalar) { konst = ((Scalar) o).getUnsignedValue(); break; }
            }
            // Record non-constant writes as null so a later (earlier) constant write
            // to the same register is not mistaken for the value actually passed.
            found.put(rn, konst);
        }
        return found;
    }

    void detail(long target) {
        Address entry = addr(target);
        Function f = fnMgr.getFunctionAt(entry);
        String nm = (f == null) ? "(no function)" : f.getName();
        List<Address> sites = callSites(entry);
        out.printf("%n================ CALL SITES OF 0x%08X  %s  (%d sites) ================%n",
                target, nm, sites.size());
        // Tally the distinct d4 values -- the candidate event-ID set.
        TreeMap<Long, Integer> d4hist = new TreeMap<>();
        int unknown = 0;
        Collections.sort(sites);
        for (Address s : sites) {
            Function c = getFunctionContaining(s);
            Map<String, Long> args = argConstants(s);
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, Long> e : args.entrySet()) {
                if (!e.getKey().equals("d4") && !e.getKey().equals("d5")) continue;
                sb.append(String.format("%s=%s ", e.getKey(),
                        e.getValue() == null ? "<var>"
                                : String.format("0x%X(%d)", e.getValue(), e.getValue())));
            }
            Long d4 = args.get("d4");
            if (args.containsKey("d4") && d4 != null) {
                d4hist.merge(d4, 1, Integer::sum);
            } else {
                unknown++;
            }
            out.printf("  0x%s  in %-22s %s%n", s,
                    c == null ? "(none)" : c.getName(), sb.toString().trim());
        }
        out.printf("%n  -- distinct constant d4 values: %d (%d call sites had a "
                + "non-constant or absent d4)%n", d4hist.size(), unknown);
        StringBuilder line = new StringBuilder("  ");
        int n = 0;
        for (Map.Entry<Long, Integer> e : d4hist.entrySet()) {
            line.append(String.format("%d(x%d) ", e.getKey(), e.getValue()));
            if (++n % 10 == 0) { out.println(line); line = new StringBuilder("  "); }
        }
        if (line.length() > 2) out.println(line);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/call_census.txt";
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];
        int topN = 50;
        if (args.length > 2 && args[2].length() > 0) topN = Integer.parseInt(args[2].trim());

        out = new PrintWriter(outPath);
        fnMgr = currentProgram.getFunctionManager();
        listing = currentProgram.getListing();
        refMgr = currentProgram.getReferenceManager();

        out.println("=== DLCM call census (TriCore) ===");
        out.println("program: " + currentProgram.getName()
                + "  lang=" + currentProgram.getLanguageID());

        // ---- census ----
        List<Function> fns = new ArrayList<>();
        FunctionIterator it = fnMgr.getFunctions(true);
        while (it.hasNext()) fns.add(it.next());
        out.println("functions defined: " + fns.size());

        Map<Function, Integer> siteCount = new HashMap<>();
        Map<Function, Integer> callerCount = new HashMap<>();
        for (Function f : fns) {
            List<Address> sites = callSites(f.getEntryPoint());
            Set<Address> callers = new HashSet<>();
            for (Address s : sites) {
                Function c = getFunctionContaining(s);
                if (c != null) callers.add(c.getEntryPoint());
            }
            siteCount.put(f, sites.size());
            callerCount.put(f, callers.size());
        }

        fns.sort((a, b) -> callerCount.get(b) - callerCount.get(a));
        out.printf("%n=== TOP %d FUNCTIONS BY DISTINCT CALLER COUNT ===%n", topN);
        out.printf("  %-12s %-22s %8s %8s %8s%n",
                "entry", "name", "callers", "sites", "size");
        for (int i = 0; i < Math.min(topN, fns.size()); i++) {
            Function f = fns.get(i);
            out.printf("  0x%s %-22s %8d %8d %8d%n",
                    f.getEntryPoint(), f.getName(),
                    callerCount.get(f), siteCount.get(f), f.getBody().getNumAddresses());
        }

        // ---- detail ----
        List<Long> targets = new ArrayList<>();
        if (args.length > 1 && args[1].length() > 0) {
            for (String p : args[1].split(",")) {
                targets.add(Long.parseLong(p.trim().replaceFirst("^0[xX]", ""), 16));
            }
        } else {
            for (int i = 0; i < Math.min(6, fns.size()); i++) {
                targets.add(fns.get(i).getEntryPoint().getOffset());
            }
        }
        for (long t : targets) detail(t);

        out.close();
        println("Done. Output: " + outPath);
    }
}
