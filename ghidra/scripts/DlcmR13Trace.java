// @category Analysis
// Up-trace the module-context base register R13 (and R12) for the DLCM
// gradient-limiter path. R12 = [R13+0x34] (module data-block ptr); both are
// callee-saved and inherited into FUN_8006d192 / the 0x212 TX dispatcher.
// Goal: find where R13 is SET (task entry), and whether it is a fixed RAM
// address, a GBR-relative load, or a table field.
//
// Uses the project's persisted disassembly (does NOT clear). Iterates only
// DEFINED instructions, so pool-constant bytes are never misread as code.
//
// Run: analyzeHeadless <proj> dlcm_analysis -process coda_dlcm_prog.bin
//      -noanalysis -postScript DlcmR13Trace.java -scriptPath <scripts>

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.lang.Register;
import java.io.*;
import java.util.*;

public class DlcmR13Trace extends GhidraScript {

    static final String OUT =
        "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\r13_trace.txt";

    // Entry points of interest for the up-trace.
    static final long[] TRACE_SEEDS = {
        0x8006D192L,   // FUN_8006d192 : DBC0 caller (gradient compare)
        0x8006D9E2L,   // 0x212 CAN-TX load-site fn
        0x8006CDA4L,   // first [R13+0x34] use (mov.l @(0x34,r13),r6)
        0x8006D2B2L,   // mov.l @(0x34,r13),r12
    };

    Register r13, r12;
    Listing listing;
    FunctionManager fm;
    ReferenceManager rm;
    AddressSpace sp;
    PrintWriter out;

    @Override
    public void run() throws Exception {
        sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        fm = currentProgram.getFunctionManager();
        listing = currentProgram.getListing();
        rm = currentProgram.getReferenceManager();

        out = new PrintWriter(new FileWriter(OUT));
        out.println("=== DlcmR13Trace ===");

        r13 = getReg("r13");
        r12 = getReg("r12");
        out.println("r13 register: " + r13 + "   r12 register: " + r12);
        out.println();

        // Make sure the trace seeds are functions so xrefs resolve.
        for (long a : TRACE_SEEDS) {
            Address ad = sp.getAddress(a);
            if (fm.getFunctionContaining(ad) == null) {
                new DisassembleCommand(ad, null, true).applyTo(currentProgram, monitor);
                new CreateFunctionCmd(ad).applyTo(currentProgram, monitor);
            }
        }

        scanRegWriters();
        upTrace();
        decompileSetters();

        out.flush();
        out.close();
        println("DlcmR13Trace complete -> " + OUT);
    }

    Register getReg(String n) {
        Register r = currentProgram.getRegister(n);
        if (r == null) r = currentProgram.getRegister(n.toUpperCase());
        return r;
    }

    boolean writesReg(Instruction ins, Register reg) {
        if (reg == null) return false;
        for (Object o : ins.getResultObjects()) {
            if (o instanceof Register) {
                Register rr = (Register) o;
                if (rr.equals(reg) || reg.equals(rr) || rr.getName().equalsIgnoreCase(reg.getName()))
                    return true;
            }
        }
        return false;
    }

    String inputsOf(Instruction ins) {
        StringBuilder sb = new StringBuilder();
        for (Object o : ins.getInputObjects()) {
            sb.append(o.toString()).append(" ");
        }
        return sb.toString().trim();
    }

    String bytesOf(Instruction ins) {
        try {
            byte[] b = new byte[ins.getLength()];
            ins.getBytesInCodeUnit(b, 0);
            StringBuilder sb = new StringBuilder();
            for (byte x : b) sb.append(String.format("%02X ", x));
            return sb.toString().trim();
        } catch (Exception e) { return "??"; }
    }

    // ---- Step 1: program-wide scan of DEFINED instructions writing R13 or R12 ----
    void scanRegWriters() {
        out.println("============================================================");
        out.println("STEP 1: all DEFINED instructions that WRITE r13 or r12");
        out.println("  (code units only; pool bytes are excluded by construction)");
        out.println("============================================================");
        InstructionIterator it = listing.getInstructions(true);
        int n13 = 0, n12 = 0;
        List<String> w13 = new ArrayList<>();
        List<String> w12 = new ArrayList<>();
        while (it.hasNext()) {
            Instruction ins = it.next();
            boolean is13 = writesReg(ins, r13);
            boolean is12 = writesReg(ins, r12);
            if (!is13 && !is12) continue;
            Function f = fm.getFunctionContaining(ins.getAddress());
            String fn = (f != null) ? (f.getName() + "@" + f.getEntryPoint()) : "(no fn)";
            String line = String.format("  %08X  %-11s  %-28s  in[%s]  %s",
                ins.getAddress().getOffset(), bytesOf(ins), ins.toString(),
                inputsOf(ins), fn);
            if (is13) { w13.add(line); n13++; }
            if (is12) { w12.add(line); n12++; }
        }
        out.println("\n-- writers of r13 (" + n13 + ") --");
        for (String s : w13) out.println(s);
        out.println("\n-- writers of r12 (" + n12 + ") --");
        for (String s : w12) out.println(s);
        out.println();
    }

    // ---- Step 2: walk UP the caller chain from the trace seeds ----
    void upTrace() {
        out.println("============================================================");
        out.println("STEP 2: caller chain upward from the gradient path");
        out.println("  (marks whether each function itself writes r13 / r12)");
        out.println("============================================================");
        Set<String> seen = new HashSet<>();
        Deque<Object[]> work = new ArrayDeque<>();
        for (long a : TRACE_SEEDS) work.add(new Object[]{ sp.getAddress(a), 0 });
        int MAXD = 6;
        while (!work.isEmpty()) {
            Object[] cur = work.poll();
            Address a = (Address) cur[0];
            int depth = (Integer) cur[1];
            Function f = fm.getFunctionContaining(a);
            String key = (f != null) ? f.getEntryPoint().toString() : a.toString();
            if (seen.contains(key)) continue;
            seen.add(key);
            String pad = "  ".repeat(depth);
            if (f == null) {
                out.println(pad + "* " + a + " (no function)");
                continue;
            }
            boolean w13 = false, w12 = false;
            InstructionIterator fi = listing.getInstructions(f.getBody(), true);
            while (fi.hasNext()) {
                Instruction ins = fi.next();
                if (writesReg(ins, r13)) w13 = true;
                if (writesReg(ins, r12)) w12 = true;
            }
            long sz = f.getBody().getMaxAddress().getOffset() - f.getBody().getMinAddress().getOffset() + 1;
            out.println(pad + "* " + f.getName() + " @ " + f.getEntryPoint()
                + " (" + sz + "b)  writes_r13=" + w13 + " writes_r12=" + w12);
            int nc = 0;
            for (Reference ref : rm.getReferencesTo(f.getEntryPoint())) {
                if (!ref.getReferenceType().isCall() && !ref.getReferenceType().isJump()) continue;
                Function cf = fm.getFunctionContaining(ref.getFromAddress());
                out.println(pad + "    <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + " " + ref.getReferenceType()
                    + " in " + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "(no fn)"));
                if (depth < MAXD) work.add(new Object[]{ ref.getFromAddress(), depth + 1 });
                nc++;
            }
            if (nc == 0) out.println(pad + "    (no callers found -- top of chain / entered via table)");
        }
        out.println();
    }

    // ---- Step 3: decompile + prologue dump for functions that WRITE r13 ----
    void decompileSetters() {
        out.println("============================================================");
        out.println("STEP 3: decompile + prologue for functions that write r13");
        out.println("============================================================");
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        // Collect distinct functions that write r13.
        LinkedHashSet<Function> setters = new LinkedHashSet<>();
        InstructionIterator it = listing.getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            if (!writesReg(ins, r13)) continue;
            // skip the obvious pool-alias byte load (mov.b @r0,r13) -- keep pointer-ish writes
            String mn = ins.toString().toLowerCase();
            if (mn.startsWith("mov.b")) continue;
            Function f = fm.getFunctionContaining(ins.getAddress());
            if (f != null) setters.add(f);
        }
        out.println("Distinct functions with a non-byte r13 write: " + setters.size());
        for (Function f : setters) {
            out.println("\n---- " + f.getName() + " @ " + f.getEntryPoint()
                + "  body " + f.getBody().getMinAddress() + "-" + f.getBody().getMaxAddress() + " ----");
            out.println("Callers:");
            for (Reference ref : rm.getReferencesTo(f.getEntryPoint())) {
                Function cf = fm.getFunctionContaining(ref.getFromAddress());
                out.println("  <- 0x" + Long.toHexString(ref.getFromAddress().getOffset())
                    + " " + ref.getReferenceType()
                    + " in " + (cf != null ? cf.getName() + "@" + cf.getEntryPoint() : "(no fn)"));
            }
            out.println("Prologue (first 30 instructions):");
            InstructionIterator pi = listing.getInstructions(f.getBody(), true);
            int k = 0;
            while (pi.hasNext() && k < 30) {
                Instruction ins = pi.next();
                out.println(String.format("  %08X  %-11s %s",
                    ins.getAddress().getOffset(), bytesOf(ins), ins.toString()));
                k++;
            }
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println("--- C ---");
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("DECOMPILE FAILED: " + (res != null ? res.getErrorMessage() : "null"));
            }
        }
        decomp.dispose();
    }
}
