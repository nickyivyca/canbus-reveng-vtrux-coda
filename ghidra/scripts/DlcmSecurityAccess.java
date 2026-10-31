// DlcmSecurityAccess.java
// Decompile the UDS SecurityAccess handler (SID 0x27) at 0x80079490 and the
// proprietary SID 0xBC handler at 0x80078FCC in coda_dlcm_prog.bin, together
// with everything they call (2 levels deep).
//
// Context: the UDS service dispatch table at 0x80041250 (8-byte records,
// handler pointer little-endian FIRST, then SID | flags | 00 | 00).
// See projects/coda/notes/dlcm/dlcm-security-access.md section 1b.
//
// 2026-09-23: the field order below was CORRECTED. An earlier revision of this
// file read SID-first, which paired every SID with the FOLLOWING record's
// handler. The comments on DISPATCH_HANDLERS were stale in exactly that way and
// are fixed here. dlcm-security-access.md 1b verifies the corrected order
// independently of the table (NRC 0x35/0x36 occur only in SecurityAccess, and
// only 0x8007907C contains both).
//
// Output path is the first script argument; defaults to ~/ghidra-projects/
// dlcm_export/security_access.txt so it works on Linux without editing.
//
// Run: analyzeHeadless <projdir> dlcm_analysis -process coda_dlcm_prog.bin \
//        -noanalysis -postScript DlcmSecurityAccess.java [outpath] \
//        -scriptPath <repo>/ghidra/scripts
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import ghidra.app.decompiler.*;
import java.io.*;
import java.util.*;

public class DlcmSecurityAccess extends GhidraScript {

    PrintWriter out;
    DecompInterface decompiler;
    FunctionManager fnMgr;
    Listing listing;
    AddressSpace as;

    // Every handler in the dispatch table at 0x80041250, plus the two targets.
    // SID assignments per the CORRECTED (handler-first) record order.
    static final long[] DISPATCH_HANDLERS = {
        0x8007890AL, // SID 10 DiagnosticSessionControl
        0x80078A74L, // SID 11 ECUReset
        0x80078B10L, // SID 14 ClearDiagnosticInformation
        0x80078B8CL, // SID 19 ReadDTCInformation
        0x80078F10L, // SID 22 ReadDataByIdentifier
        0x8007907CL, // SID 27 SecurityAccess     <-- PRIMARY TARGET
        0x80079490L, // SID 28 CommunicationControl
        0x800795C0L, // SID 2E WriteDataByIdentifier
        0x800795F0L, // SID 31 RoutineControl
        0x80079940L, // SID 3E TesterPresent
        0x80079978L, // SID 85 ControlDTCSetting
        0x800799F0L, // SID BC proprietary          <-- SECOND TARGET
        0x80078FCCL, // SID 23 ReadMemoryByAddress
    };

    // Decompile these and their callees in full.
    static final long[] DEEP_TARGETS = {
        0x80079490L, 0x80078FCCL,
        0x8007890AL, 0x80078A74L, 0x80078B10L, 0x80078B8CL, 0x80078F10L,
        0x8007907CL, 0x800795C0L, 0x800795F0L, 0x80079940L, 0x80079978L,
        0x800799F0L,
    };
    static final int DEPTH = 2;

    @Override
    public void run() throws Exception {
        String outPath = System.getProperty("user.home")
                + "/ghidra-projects/dlcm_export/security_access.txt";
        String[] args = getScriptArgs();
        if (args.length > 0 && args[0].length() > 0) outPath = args[0];
        // Second argument: comma-separated hex addresses to deep-dive instead
        // of DEEP_TARGETS, so new leads can be chased without editing this file.
        long[] deep = DEEP_TARGETS;
        if (args.length > 1 && args[1].length() > 0) {
            String[] parts = args[1].split(",");
            deep = new long[parts.length];
            for (int i = 0; i < parts.length; i++) {
                deep[i] = Long.parseLong(parts[i].trim().replaceFirst("^0[xX]", ""), 16);
            }
        }

        out = new PrintWriter(new FileWriter(outPath));
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        fnMgr = currentProgram.getFunctionManager();
        listing = currentProgram.getListing();
        as = currentProgram.getAddressFactory().getDefaultAddressSpace();

        out.println("=== coda_dlcm_prog.bin SecurityAccess / SID 0xBC decompile ===");
        out.println("program: " + currentProgram.getName()
                + "  lang=" + currentProgram.getLanguageID()
                + "  imagebase=" + currentProgram.getImageBase());

        dumpDispatchTable();
        seedFunctions();

        // Walk the call graph from the two deep targets.
        LinkedHashSet<Address> wanted = new LinkedHashSet<>();
        // Third argument: callee depth (default DEPTH). 0 = the named functions only.
        int depth = DEPTH;
        if (args.length > 2 && args[2].length() > 0) depth = Integer.parseInt(args[2].trim());
        for (long t : deep) collectCallees(addr(t), depth, wanted);

        out.println("\n=== CALL GRAPH CLOSURE (" + wanted.size() + " functions) ===");
        for (Address a : wanted) {
            Function f = fnMgr.getFunctionAt(a);
            out.printf("  0x%08X  %s  size=%d%n", a.getOffset(),
                    f == null ? "<none>" : f.getName(),
                    f == null ? 0 : f.getBody().getNumAddresses());
        }

        for (Address a : wanted) dumpFunction(a);

        // Raw bytes of the primary target, so the instruction stream can be
        // re-decoded by hand if SLEIGH mis-decodes anything.
        out.println("\n=== RAW BYTES 0x80079490 .. 0x800795C0 (SecurityAccess) ===");
        hexDump(addr(0x80079490L), 0x130);
        out.println("\n=== RAW BYTES 0x80078FCC .. 0x8007907C (SID 0xBC) ===");
        hexDump(addr(0x80078FCCL), 0xB0);

        out.flush();
        out.close();
        decompiler.dispose();
        println("Done. Output: " + outPath);
    }

    Address addr(long v) throws Exception {
        return as.getAddress(Long.toHexString(v));
    }

    /** Re-read the dispatch table from memory so the notes' transcription is verified. */
    void dumpDispatchTable() throws Exception {
        // Record layout: handler pointer (LE) at rec+0, then SID|flags|00|00.
        // Record N therefore has its pointer at 0x8004124C + N*8 and its SID
        // byte at 0x80041250 + N*8. Reading SID-first pairs each SID with the
        // NEXT record's handler -- the error corrected 2026-09-19.
        out.println("\n=== DISPATCH TABLE @0x80041250 (re-read from image) ===");
        out.println("  SID@        SID flags  handler(LE ptr)   raw(ptr|sid)");
        Memory mem = currentProgram.getMemory();
        for (int i = 0; i < 13; i++) {
            long sidAddr = 0x80041250L + i * 8L;
            Address rec = addr(sidAddr - 4L);
            byte[] b = new byte[8];
            try {
                mem.getBytes(rec, b);
            } catch (MemoryAccessException e) {
                out.println("  [unreadable at " + rec + "]");
                break;
            }
            long ptrLE = ((long) (b[0] & 0xFF))
                    | ((long) (b[1] & 0xFF) << 8)
                    | ((long) (b[2] & 0xFF) << 16)
                    | ((long) (b[3] & 0xFF) << 24);
            StringBuilder raw = new StringBuilder();
            for (byte x : b) raw.append(String.format("%02X ", x));
            out.printf("  0x%08X  %02X   %02X     LE=0x%08X   %s%n",
                    sidAddr, b[4] & 0xFF, b[5] & 0xFF, ptrLE, raw.toString().trim());
        }
    }

    /** Disassemble + create a function at every dispatch handler. */
    void seedFunctions() throws Exception {
        out.println("\n=== FUNCTION SEEDING ===");
        for (long a : DISPATCH_HANDLERS) {
            Address ad = addr(a);
            Function existing = fnMgr.getFunctionAt(ad);
            if (existing != null) {
                out.printf("  EXISTING 0x%08X -> %s (size=%d)%n", a,
                        existing.getName(), existing.getBody().getNumAddresses());
                continue;
            }
            if (listing.getInstructionAt(ad) == null) {
                disassemble(ad);
            }
            Function created = null;
            try {
                created = createFunction(ad, null);
            } catch (Exception e) {
                out.printf("  EXC      0x%08X -> %s%n", a, e.getMessage());
            }
            if (created != null) {
                out.printf("  CREATED  0x%08X -> %s (size=%d)%n", a,
                        created.getName(), created.getBody().getNumAddresses());
            } else {
                Function containing = fnMgr.getFunctionContaining(ad);
                out.printf("  FAILED   0x%08X%s%n", a, containing == null ? ""
                        : "  (inside " + containing.getName() + " @"
                          + containing.getEntryPoint() + ")");
            }
        }
    }

    /** Depth-limited callee collection; seeds functions at call targets as it goes. */
    void collectCallees(Address entry, int depth, LinkedHashSet<Address> acc) throws Exception {
        if (entry == null || acc.contains(entry)) return;
        Function f = fnMgr.getFunctionAt(entry);
        if (f == null) {
            if (listing.getInstructionAt(entry) == null) disassemble(entry);
            try {
                f = createFunction(entry, null);
            } catch (Exception e) {
                // fall through
            }
            if (f == null) return;
        }
        acc.add(entry);
        if (depth <= 0) return;
        for (Function callee : f.getCalledFunctions(monitor)) {
            collectCallees(callee.getEntryPoint(), depth - 1, acc);
        }
        // getCalledFunctions only sees resolved references; also walk the
        // instruction stream for BSR/JSR flow targets Ghidra has not turned
        // into functions yet.
        InstructionIterator it = listing.getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            Address[] flows = ins.getFlows();
            if (flows == null) continue;
            for (Address fl : flows) {
                if (ins.getFlowType().isCall() && !f.getBody().contains(fl)) {
                    collectCallees(fl, depth - 1, acc);
                }
            }
        }
    }

    void dumpFunction(Address entry) throws Exception {
        Function f = fnMgr.getFunctionAt(entry);
        if (f == null) return;
        out.printf("%n%n================ %s @0x%08X  size=%d ================%n",
                f.getName(), entry.getOffset(), f.getBody().getNumAddresses());

        out.println("--- listing ---");
        InstructionIterator it = listing.getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            StringBuilder bytes = new StringBuilder();
            try {
                for (byte b : ins.getBytes()) bytes.append(String.format("%02X", b));
            } catch (MemoryAccessException e) {
                bytes.append("??");
            }
            out.printf("  %08X  %-8s  %s%n",
                    ins.getAddress().getOffset(), bytes.toString(), ins.toString());
        }
        // Data-in-code (SH-4 literal pools) inside the body.
        DataIterator di = listing.getData(f.getBody(), true);
        boolean firstData = true;
        while (di.hasNext()) {
            Data d = di.next();
            if (firstData) {
                out.println("--- data inside body (literal pool) ---");
                firstData = false;
            }
            out.printf("  %08X  %s  %s%n", d.getAddress().getOffset(),
                    d.getDataType().getName(), d.getDefaultValueRepresentation());
        }

        out.println("--- decompiled ---");
        DecompileResults res = decompiler.decompileFunction(f, 120, monitor);
        if (res.decompileCompleted()) {
            out.println(res.getDecompiledFunction().getC());
        } else {
            out.println("  [decompile failed: " + res.getErrorMessage() + "]");
        }
        out.flush();
    }

    void hexDump(Address start, int len) throws Exception {
        Memory mem = currentProgram.getMemory();
        byte[] b = new byte[len];
        try {
            mem.getBytes(start, b);
        } catch (MemoryAccessException e) {
            out.println("  [unreadable]");
            return;
        }
        for (int i = 0; i < len; i += 16) {
            StringBuilder hex = new StringBuilder();
            for (int j = i; j < i + 16 && j < len; j++) {
                hex.append(String.format("%02X", b[j]));
                if ((j % 2) == 1) hex.append(' ');
            }
            out.printf("  %08X  %s%n", start.getOffset() + i, hex.toString());
        }
    }
}
