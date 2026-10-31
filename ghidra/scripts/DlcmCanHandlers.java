// DlcmCanHandlers.java
// TriCore. Reads the DLCM's CAN COM configuration out of the image, then seeds and
// decompiles the per-message handlers so each configured CAN id can be tied to code.
//
//   master CAN config 0x80041DA4
//     +0x00 -> RX message table 0x8004162C  26 x 52B
//     +0x04 -> TX message table 0x80041B74  14 x 40B
//   record: +0x00 u32 id, +0x04 u16 buf, +0x06 u16 period(5ms ticks),
//           +0x08 u8 dlc (RX) / +0x0A u8 dlc (TX), +0x10 u32 stub, +0x20 u32 app handler (RX)
//           TX carries its second handler at +0x1C.
//
// Args: <outpath> [comma-separated hex ids to restrict to] [callee depth, default 2]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class DlcmCanHandlers extends GhidraScript {

    static final long RX_TABLE = 0x8004162CL, TX_TABLE = 0x80041B74L;
    static final int RX_N = 26, RX_STRIDE = 52, TX_N = 14, TX_STRIDE = 40;

    PrintWriter out;
    DecompInterface decompiler;
    FunctionManager fnMgr;
    Listing listing;
    AddressSpace as;
    Memory mem;

    @Override
    public void run() throws Exception {
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/can_handlers.txt";
        String[] args = getScriptArgs();
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];
        Set<Long> only = new HashSet<>();
        if (args.length > 1 && args[1].length() > 0) {
            for (String t : args[1].split(",")) {
                only.add(Long.parseLong(t.trim().replaceFirst("^0[xX]", ""), 16));
            }
        }
        int depth = 2;
        if (args.length > 2 && args[2].length() > 0) depth = Integer.parseInt(args[2].trim());

        out = new PrintWriter(new FileWriter(outPath));
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        fnMgr = currentProgram.getFunctionManager();
        listing = currentProgram.getListing();
        as = currentProgram.getAddressFactory().getDefaultAddressSpace();
        mem = currentProgram.getMemory();

        out.println("=== DLCM CAN COM message tables ===");
        out.println("program: " + currentProgram.getName()
                + "  lang=" + currentProgram.getLanguageID()
                + "  imagebase=" + currentProgram.getImageBase());

        LinkedHashMap<Long, long[]> targets = new LinkedHashMap<>(); // id -> {stub, app}
        out.println("\n--- RX table ---");
        out.println("  id     buf    per(ms) dlc  stub        app");
        for (int i = 0; i < RX_N; i++) {
            long rec = RX_TABLE + i * RX_STRIDE;
            long id = u32(rec), stub = u32(rec + 0x10), app = u32(rec + 0x20);
            out.printf("  0x%03X  0x%04X  %5d  %d   0x%08X  0x%08X%n",
                    id, u16(rec + 4), 5 * u16(rec + 6), u8(rec + 8), stub, app);
            if (only.isEmpty() || only.contains(id)) targets.put(id, new long[]{stub, app});
        }
        out.println("\n--- TX table ---");
        out.println("  id     buf    per(ms) dlc  stub        app");
        for (int i = 0; i < TX_N; i++) {
            long rec = TX_TABLE + i * TX_STRIDE;
            long id = u32(rec), stub = u32(rec + 0x10), app = u32(rec + 0x1C);
            out.printf("  0x%03X  0x%04X  %5d  %d   0x%08X  0x%08X%n",
                    id, u16(rec + 4), 5 * u16(rec + 6), u8(rec + 0x0A), stub, app);
            if (only.isEmpty() || only.contains(id)) targets.put(id, new long[]{stub, app});
        }

        LinkedHashSet<Address> wanted = new LinkedHashSet<>();
        out.println("\n=== SEEDING ===");
        for (Map.Entry<Long, long[]> e : targets.entrySet()) {
            for (long a : e.getValue()) {
                if (a < 0x80040000L || a > 0x80096000L) continue;
                out.printf("  0x%03X -> 0x%08X%n", e.getKey(), a);
                collectCallees(addr(a), depth, wanted);
            }
        }

        out.println("\n=== CALL GRAPH CLOSURE (" + wanted.size() + " functions) ===");
        for (Address a : wanted) {
            Function f = fnMgr.getFunctionAt(a);
            out.printf("  0x%08X  %s  size=%d%n", a.getOffset(),
                    f == null ? "<none>" : f.getName(),
                    f == null ? 0 : f.getBody().getNumAddresses());
        }
        for (Address a : wanted) dumpFunction(a);

        out.flush();
        out.close();
        decompiler.dispose();
        println("Done. Output: " + outPath);
    }

    Address addr(long v) throws Exception { return as.getAddress(Long.toHexString(v)); }
    int u8(long a) throws Exception { return mem.getByte(addr(a)) & 0xFF; }
    int u16(long a) throws Exception { return u8(a) | (u8(a + 1) << 8); }
    long u32(long a) throws Exception { return (u16(a) | ((long) u16(a + 2) << 16)) & 0xFFFFFFFFL; }

    void collectCallees(Address entry, int depth, LinkedHashSet<Address> acc) throws Exception {
        if (entry == null || acc.contains(entry)) return;
        Function f = fnMgr.getFunctionAt(entry);
        if (f == null) {
            if (listing.getInstructionAt(entry) == null) disassemble(entry);
            try { f = createFunction(entry, null); } catch (Exception e) { }
            if (f == null) return;
        }
        acc.add(entry);
        if (depth <= 0) return;
        for (Function callee : f.getCalledFunctions(monitor)) {
            collectCallees(callee.getEntryPoint(), depth - 1, acc);
        }
        InstructionIterator it = listing.getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            Address[] flows = ins.getFlows();
            if (flows == null) continue;
            for (Address fl : flows) {
                if (!f.getBody().contains(fl)) collectCallees(fl, depth - 1, acc);
            }
        }
    }

    void dumpFunction(Address entry) throws Exception {
        Function f = fnMgr.getFunctionAt(entry);
        if (f == null) return;
        out.printf("%n%n================ %s @0x%08X  size=%d ================%n",
                f.getName(), entry.getOffset(), f.getBody().getNumAddresses());
        DecompileResults res = decompiler.decompileFunction(f, 90, monitor);
        if (res != null && res.decompileCompleted() && res.getDecompiledFunction() != null) {
            out.println(res.getDecompiledFunction().getC());
        } else {
            out.println("  [decompile failed: "
                    + (res == null ? "null" : res.getErrorMessage()) + "]");
        }
        if (f.getBody().getNumAddresses() <= 96) {
            out.println("--- listing ---");
            InstructionIterator it = listing.getInstructions(f.getBody(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                StringBuilder bytes = new StringBuilder();
                try { for (byte b : ins.getBytes()) bytes.append(String.format("%02X", b)); }
                catch (MemoryAccessException e) { bytes.append("??"); }
                out.printf("  %08X  %-10s  %s%n",
                        ins.getAddress().getOffset(), bytes.toString(), ins.toString());
            }
        }
    }
}
