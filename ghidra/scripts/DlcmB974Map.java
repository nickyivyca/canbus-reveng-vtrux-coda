// DlcmB974Map.java
// Map the second digital-output subsystem -- the one behind FUN_8007b974 -- end to end.
//
// The DLCM has TWO table-driven output layers, not one.  The documented one is
// FUN_8007cd6e with 0xC-byte entries at 0x800421BC (Key Interlock Solenoid, etc).
// This is the other: FUN_8007b974(id, level) where
//
//     entry = *(int *)(*(int *)(a0 - 0x3db4) + 4) + (id >> 1) * 0x14
//     pin   = *(byte *)(entry + ((id & 1) ? 5 : 4))
//     FUN_800635b8(pin, level)
//
// so one 0x14-byte entry carries TWO pin ids and `id` packs entry in bits[n:1] and
// which-pin in bit 0.  FUN_80089ed4(cfg) installs it: cfg[0] is the entry count and
// *(int*)(cfg+4) is the array base.  The reverse lamp lives here (id 3, DTC B2101),
// which is why it matters -- C_A3, the regen brake lamp relay coil driver, is wired
// the same way as C_L4 in the harness and would be expected in the same layer.
//
// Reports: the cfg site, the decoded entry table, every literal-argument caller of
// FUN_8007b974 and of the FUN_8007c662 selector wrapper, and which ids nothing drives.
//
// Args: <outpath> [comma-separated extra installer function names to probe for a cfg literal]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmB974Map extends GhidraScript {

    static final String SETTER = "FUN_8007b974";
    static final String SELECTOR = "FUN_8007c662";
    static final String INIT = "FUN_80089ed4";
    static final int STRIDE = 0x14;

    PrintWriter out;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args.length > 0 && !args[0].isEmpty() ? args[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/b974_map.txt";
        new File(outPath).getParentFile().mkdirs();
        out = new PrintWriter(new FileWriter(outPath));

        out.println("=== FUN_8007b974 output subsystem ===");
        out.println();

        // --- 1. find the config pointer handed to the initialiser -----------
        Long cfg = findInitArg();
        out.println();

        // --- 2. decode the entry table -------------------------------------
        if (cfg != null) dumpEntries(cfg);
        out.println();

        // --- 3. literal-argument callers -----------------------------------
        Map<Long, List<String>> byId = new TreeMap<>();
        collectLiteralCalls(SETTER, byId, "direct");
        Map<Long, List<String>> selIds = new TreeMap<>();
        collectLiteralCalls(SELECTOR, selIds, "via " + SELECTOR);

        out.println("--- callers of " + SETTER + " with a literal first argument ---");
        report(byId);
        out.println();
        out.println("--- callers of " + SELECTOR + " with a literal first argument ---");
        out.println("    (the wrapper maps 0->0, 2->2, 3->3 and rejects everything else)");
        report(selIds);

        // --- 4. optional: recover the literal cfg pointer handed to other installers
        if (args.length > 1 && !args[1].isEmpty()) {
            out.println();
            out.println("--- cfg pointers handed to other installers ---");
            for (String n : args[1].split(",")) {
                n = n.trim();
                if (n.isEmpty()) continue;
                Function f = getFn(n);
                out.println("  " + n + (f == null ? "  (not found)" : ""));
                if (f == null) continue;
                for (Reference r : getReferencesTo(f.getEntryPoint())) {
                    if (!r.getReferenceType().isCall()) continue;
                    Long v = backtrackAddressReg(r.getFromAddress(), "a4");
                    out.printf("      called from %s   cfg = %s%n", r.getFromAddress(),
                            v == null ? "(not a literal)" : String.format("0x%08x", v));
                }
            }
        }

        out.flush();
        out.close();
        println("DlcmB974Map -> " + outPath);
    }

    private void report(Map<Long, List<String>> m) {
        if (m.isEmpty()) { out.println("    (none)"); return; }
        for (Map.Entry<Long, List<String>> e : m.entrySet()) {
            out.printf("  id = %d  (0x%x)%n", e.getKey(), e.getKey());
            for (String s : e.getValue()) out.println("        " + s);
        }
    }

    private Long findInitArg() throws Exception {
        Function init = getFn(INIT);
        out.println("--- " + INIT + " (installs the table) ---");
        if (init == null) { out.println("  not found"); return null; }
        Long found = null;
        for (Reference r : getReferencesTo(init.getEntryPoint())) {
            if (!r.getReferenceType().isCall()) continue;
            Address site = r.getFromAddress();
            Function owner = currentProgram.getFunctionManager().getFunctionContaining(site);
            out.printf("  called from %s  in %s%n", site,
                    owner == null ? "(no function)" : owner.getName());
            Long v = backtrackAddressReg(site, "a4");
            if (v != null) {
                out.printf("      cfg pointer = 0x%08x%n", v);
                found = v;
            } else {
                out.println("      cfg pointer not recovered from the preceding instructions");
            }
        }
        return found;
    }

    /** Walk back for the movh.a/lea pair that loads an address register. */
    private Long backtrackAddressReg(Address site, String regName) {
        Instruction ins = getInstructionAt(site);
        if (ins == null) return null;
        Long hi = null, lo = null;
        for (int i = 0; i < 24 && ins != null; i++) {
            ins = ins.getPrevious();
            if (ins == null) break;
            String m = ins.getMnemonicString();
            String txt = ins.toString();
            if (!txt.contains(regName)) continue;
            if (m.equals("lea") && lo == null) {
                Scalar s = lastScalar(ins);
                if (s != null) lo = s.getUnsignedValue();
            } else if (m.equals("movh.a") && hi == null) {
                Scalar s = lastScalar(ins);
                if (s != null) hi = s.getUnsignedValue();
            }
            if (hi != null && lo != null) return (hi << 16) + lo;
        }
        return null;
    }

    private Scalar lastScalar(Instruction ins) {
        Scalar last = null;
        for (int i = 0; i < ins.getNumOperands(); i++) {
            for (Object o : ins.getOpObjects(i)) if (o instanceof Scalar) last = (Scalar) o;
        }
        return last;
    }

    private void dumpEntries(long cfg) throws Exception {
        out.println("--- entry table ---");
        Address cfgAddr = toAddr(cfg);
        int count = getByte(cfgAddr) & 0xFF;
        long base = getInt(cfgAddr.add(4)) & 0xFFFFFFFFL;
        out.printf("  cfg @0x%08x   count = %d   entries @0x%08x  stride 0x%x%n",
                cfg, count, base, STRIDE);
        out.println();
        out.println("   entry   id(A) pinA          id(B) pinB          +0xC        +0x10");
        for (int i = 0; i < count && i < 64; i++) {
            Address e = toAddr(base + (long) i * STRIDE);
            int pinA = getByte(e.add(4)) & 0xFF;
            int pinB = getByte(e.add(5)) & 0xFF;
            long c = getInt(e.add(0xC)) & 0xFFFFFFFFL;
            int chan = getByte(e.add(0x10)) & 0xFF;
            out.printf("   %-6d  %-5d %-14s %-5d %-14s 0x%08x  0x%02x%n",
                    i, i * 2, pinName(pinA), i * 2 + 1, pinName(pinB), c, chan);
        }
    }

    private String pinName(int id) {
        if (id == 0) return "0x00 (none)";
        return String.format("P%d.%d", (id >> 4) & 0xF, id & 0xF);
    }

    private void collectLiteralCalls(String fnName, Map<Long, List<String>> byId, String tag) {
        Function f = getFn(fnName);
        if (f == null) return;
        for (Reference r : getReferencesTo(f.getEntryPoint())) {
            if (!r.getReferenceType().isCall()) continue;
            Address site = r.getFromAddress();
            Function owner = currentProgram.getFunctionManager().getFunctionContaining(site);
            Long id = backtrackD4(site);
            String where = String.format("%s @%s  [%s]",
                    owner == null ? "(no function)" : owner.getName(), site, tag);
            if (id == null) byId.computeIfAbsent(-1L, k -> new ArrayList<>())
                    .add(where + "   (argument not a literal)");
            else byId.computeIfAbsent(id, k -> new ArrayList<>()).add(where);
        }
    }

    /** Recover a literal loaded into d4 (TriCore first integer argument) before a call. */
    private Long backtrackD4(Address site) {
        Instruction ins = getInstructionAt(site);
        if (ins == null) return null;
        for (int i = 0; i < 12 && ins != null; i++) {
            ins = ins.getPrevious();
            if (ins == null) break;
            String txt = ins.toString();
            if (!txt.startsWith("mov d4,#") && !txt.startsWith("mov.u d4,#")) {
                // anything else that writes d4 defeats the literal read
                if (txt.matches("^\\w[\\w.]*\\s+d4,.*")) return null;
                continue;
            }
            Scalar s = lastScalar(ins);
            if (s != null) return s.getUnsignedValue();
        }
        return null;
    }

    private Function getFn(String name) {
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            if (f.getName().equals(name)) return f;
        return null;
    }
}
