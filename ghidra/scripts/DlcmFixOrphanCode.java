// DlcmFixOrphanCode.java
// Make Ghidra's caller graph correct on this TriCore image, permanently.
//
// THE PROBLEM -- and it is NOT what it first looks like
// -----------------------------------------------------
// Ask Ghidra "who calls FUN_8006eb8c?" and it answers "nobody".  That function is the
// DLCM's brake-lamp-feedback module; it raises DTC B2100 and it runs every task cycle.
// Believing the answer on 2026-09-25 produced the conclusion that it was dead code.
//
// The first diagnosis was that TriCore tail calls -- `j <function>` instead of `call` --
// were being recorded as jumps and so missed by `Function.getCallingFunctions`, which
// filters on `RefType.isCall()`.  **That diagnosis was wrong.**  Ghidra's TriCore
// language already classifies those instructions correctly.  Probing 0x8007C5FC:
//
//     insn: j 0x8007cd6e
//     flowType: CALL_TERMINATOR   isCall=true  isJump=false
//     reference: -> 8007cd6e  type=UNCONDITIONAL_CALL  isCall=true
//
// so the thin accessor band at 0x8007C54C-0x8007C662 is seen as calling, correctly, and
// no reference repair is needed.  A script written to "fix" that would have added nothing.
//
// The real gap is that **the caller is code with no function around it.**  Every way of
// listing callers -- `getCallingFunctions`, or walking `getReferencesTo` and mapping each
// source through `getFunctionContaining` -- turns a reference into a *function*.  When the
// call site lies in a region the rebuild never turned into a function, that mapping yields
// null and the caller silently disappears.  The reference is right there in the database;
// only its container is missing.
//
// FUN_8006eb8c is called from 0x8007C2E2, inside the main periodic task.  Most of that
// task is undefined code, so the call vanished.
//
// THE FIX
// -------
// Pass 1  Any call/jump destination that holds instructions but sits in no function gets
//         one.  (Recovers callees.)
// Pass 2  Any call *site* that sits in no function: walk back to the previous terminator
//         and create a function at the instruction after it.  (Recovers callers -- this
//         is the pass that fixes FUN_8006eb8c.)
// Both passes iterate to a fixed point, since creating one function exposes more.
//
// The change is written into the project database, so it is applied once and every later
// script benefits without knowing any of this.  Idempotent: a second run creates nothing.
//
// Args: <outpath> [comma-separated function entries to delete first, for repair]
//
// Run: analyzeHeadless ~/ghidra-projects dlcm_tricore \
//        -process coda_dlcm_prog.bin -noanalysis \
//        -postScript DlcmFixOrphanCode.java <out> \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmFixOrphanCode extends GhidraScript {

    static final int MAX_BACKWALK = 4000;   // instructions; a large TriCore function is ~1000
    static final int MAX_ROUNDS = 4;

    /**
     * A real function entry is preceded by a terminator (ret, or a tail-call jump), or by
     * nothing at all.  **This guard is load-bearing.**  `getFunctionContaining` is NOT a
     * reliable "is this address inside a function" test on this image: Ghidra's recorded
     * *body* can be a fraction of the code the function actually executes.  FUN_800803fa
     * has a body of 4 bytes while its decompilation runs through 0x80080414, so every
     * address after 0x800803FE reported no container and an earlier version of this script
     * happily created FUN_80080400 in the middle of it -- a fragment that decompiles to
     * nonsense (`*a0 = unaff_a13; FUN_800686d8();`) and looks like a real function.
     * Requiring a terminator before the entry rejects exactly that case.
     */
    private boolean plausibleEntry(Instruction at) {
        if (at == null) return false;
        Instruction prev = at.getPrevious();
        if (prev == null) return true;                       // start of the code region
        if (prev.getFlowType().isTerminal()) return true;     // ret, or tail-call jump
        if (prev.getFlowType().isJump() && !prev.getFlowType().isConditional()) return true;
        return false;
    }

    PrintWriter out;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = (args.length > 0 && !args[0].isEmpty())
                ? args[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/fix_orphan_code.txt";
        new File(outPath).getParentFile().mkdirs();
        out = new PrintWriter(new FileWriter(outPath));

        Listing listing = currentProgram.getListing();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        out.println("DlcmFixOrphanCode -- give every call site and callee a function");
        out.println("program: " + currentProgram.getName());
        out.println("functions before: " + fnMgr.getFunctionCount());
        out.println();

        if (args.length > 1 && !args[1].isEmpty()) {
            out.println("--- deleting functions requested for repair ---");
            for (String a : args[1].split(",")) {
                a = a.trim();
                if (a.isEmpty()) continue;
                Address addr = toAddr(a.startsWith("0x") ? a.substring(2) : a);
                Function f = fnMgr.getFunctionAt(addr);
                if (f == null) { out.println("  " + addr + "  none"); continue; }
                out.printf("  removing %s @%s (%d bytes)%n",
                        f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses());
                removeFunctionAt(addr);
            }
            out.println();
        }

        // --- pass 0: functions whose entry is NOT preceded by a terminator ----
        // These are mid-function fragments.  Report always; delete only when asked,
        // since auto-analysis occasionally produces a legitimate one.
        boolean prune = args.length > 2 && args[2].equals("prune");
        out.println("--- pass 0: suspect entries (not preceded by a terminator) ---");
        // A *fragment* is stricter than "implausible entry": the preceding instruction
        // must fall through into this entry AND belong to a different function.  The
        // looser test flags 831 entries, most of them legitimate pre-existing functions
        // (FUN_80048d94 among them), so it is safe for gating creation and far too blunt
        // for deletion.
        List<Address> suspect = new ArrayList<>();
        for (Function f : fnMgr.getFunctions(true)) {
            if (monitor.isCancelled()) break;
            Address ep = f.getEntryPoint();
            Instruction at = listing.getInstructionAt(ep);
            if (at == null || plausibleEntry(at)) continue;
            Instruction prev = at.getPrevious();
            if (prev == null || !prev.getFlowType().isFallthrough()) continue;
            Function owner = fnMgr.getFunctionContaining(prev.getAddress());
            if (owner == null || owner.getEntryPoint().equals(ep)) continue;
            suspect.add(ep);
        }
        out.printf("  suspect function entries: %d%s%n", suspect.size(),
                prune ? "  (pruning)" : "  (reporting only; pass \"prune\" as arg 3 to remove)");
        int pruned = 0;
        for (Address a : suspect) {
            Function f = fnMgr.getFunctionAt(a);
            if (f == null) continue;
            if (suspect.indexOf(a) < 30) {
                out.printf("      %s %s (%dB)%s%n", f.getName(), a,
                        f.getBody().getNumAddresses(), prune ? "  REMOVED" : "");
            }
            if (prune) { removeFunctionAt(a); pruned++; }
        }
        out.printf("  pruned: %d%n%n", pruned);

        int totalCallees = 0, totalSites = 0;
        for (int round = 1; round <= MAX_ROUNDS; round++) {
            int callees = passCallees(listing, fnMgr);
            int sites = passCallSites(listing, fnMgr);
            out.printf("round %d: +%d callee functions, +%d call-site functions%n",
                    round, callees, sites);
            totalCallees += callees;
            totalSites += sites;
            if (callees == 0 && sites == 0) break;
        }

        out.println();
        out.printf("total created: %d from callees, %d from call sites%n", totalCallees, totalSites);
        out.println("functions after: " + fnMgr.getFunctionCount());
        out.flush();
        out.close();
        println("DlcmFixOrphanCode: +" + (totalCallees + totalSites) + " functions -> " + outPath);
    }

    /** Destinations of a call/jump that hold code but live in no function. */
    private int passCallees(Listing listing, FunctionManager fnMgr) {
        Set<Address> orphans = new TreeSet<>();
        InstructionIterator it = listing.getInstructions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            if (!ins.getFlowType().isCall() && !ins.getFlowType().isJump()) continue;
            for (Address dest : ins.getFlows()) {
                if (fnMgr.getFunctionContaining(dest) != null) continue;
                Instruction target = listing.getInstructionAt(dest);
                if (target == null) continue;
                if (!plausibleEntry(target)) continue;   // mid-function: see plausibleEntry
                orphans.add(dest);
            }
        }
        int n = 0;
        for (Address a : orphans) if (createFunction(a, null) != null) n++;
        return n;
    }

    /**
     * Call sites that live in no function.  Walk back to the instruction after the
     * previous terminator and create a function there, so the site gets a container
     * and the callee's caller list stops being empty.
     */
    private int passCallSites(Listing listing, FunctionManager fnMgr) {
        Set<Address> starts = new TreeSet<>();
        InstructionIterator it = listing.getInstructions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            if (!ins.getFlowType().isCall()) continue;
            if (fnMgr.getFunctionContaining(ins.getAddress()) != null) continue;

            Instruction cur = ins, prev = ins.getPrevious();
            int steps = 0;
            while (prev != null && steps++ < MAX_BACKWALK) {
                // A terminator ends the previous function; `cur` begins this one.
                if (prev.getFlowType().isTerminal()) break;
                // Do not walk into an already-defined function.
                if (fnMgr.getFunctionContaining(prev.getAddress()) != null) break;
                cur = prev;
                prev = prev.getPrevious();
            }
            if (cur != null && fnMgr.getFunctionContaining(cur.getAddress()) == null
                    && plausibleEntry(cur)) {
                starts.add(cur.getAddress());
            }
        }
        int n = 0;
        List<String> shown = new ArrayList<>();
        for (Address a : starts) {
            Function f = createFunction(a, null);
            if (f != null) {
                n++;
                if (shown.size() < 20) shown.add("      created " + f.getName() + " @" + a);
            }
        }
        for (String s : shown) out.println(s);
        return n;
    }
}
