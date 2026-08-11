// @category Analysis
// Recursively decompile from gradient-limiter entry points and scan each
// function in the call tree for memory accesses whose address is in the
// CAL data range (0x80020000-0x80022400, the candidate LUT region). Report
// hits as candidate LUT loads.
//
// Approach:
//   1. Seed the worklist with the known gradient-limiter / 0x212-TX entry
//      points.
//   2. For each function popped: decompile it, write decompile to output,
//      walk the function's instructions and check each memory operand's
//      computed reference (Ghidra's reference manager has already resolved
//      MOV.L pool-loads to their targets).
//   3. Also check raw operands for any 32-bit literal in CAL data range.
//   4. Add every called function (from instructions and references) to the
//      worklist. Cap depth at 6 and total functions at 200.
//
// Output -> dlcm_export\gradient_call_chain.txt

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.io.*;
import java.util.*;

public class DlcmGradientCallChain extends GhidraScript {

    static final String OUT = "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\gradient_call_chain.txt";

    static final long CAL_DATA_LO = 0x80020000L;
    static final long CAL_DATA_HI = 0x80022400L;

    static final long[] SEED_ENTRIES = {
        0x8006D900L,
        0x8006D9E2L,
        0x8006CE4CL,
        0x8006D1B8L,
        0x8006DBC0L,
    };

    static final int MAX_DEPTH = 6;
    static final int MAX_FUNCS = 200;

    @Override
    public void run() throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();

        PrintWriter out = new PrintWriter(new FileWriter(OUT));

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        // BFS worklist
        ArrayDeque<long[]> work = new ArrayDeque<>();
        Set<Long> visited = new HashSet<>();
        for (long seed : SEED_ENTRIES) {
            work.add(new long[]{seed, 0L});
        }

        // Aggregated CAL hits
        List<String> calHits = new ArrayList<>();

        int processed = 0;
        while (!work.isEmpty() && processed < MAX_FUNCS) {
            long[] item = work.poll();
            long addr = item[0];
            long depth = item[1];
            if (visited.contains(addr)) continue;
            visited.add(addr);

            Address a = sp.getAddress(addr);
            Function f = fm.getFunctionContaining(a);
            if (f == null) {
                CreateFunctionCmd cmd = new CreateFunctionCmd(a);
                cmd.applyTo(currentProgram, monitor);
                f = fm.getFunctionAt(a);
            }
            if (f == null) {
                out.println("\n// SKIP: cannot find/create function at 0x" + Long.toHexString(addr)
                    + " (depth=" + depth + ")");
                continue;
            }
            long entry = f.getEntryPoint().getOffset();
            if (entry != addr && visited.contains(entry)) continue;
            visited.add(entry);
            processed++;

            long sz = f.getBody().getMaxAddress().getOffset()
                    - f.getBody().getMinAddress().getOffset() + 1;
            out.println();
            out.println("============================================================");
            out.println("// " + f.getName() + " @ 0x" + Long.toHexString(entry)
                + "  body=" + sz + " bytes  depth=" + depth
                + "  (#" + processed + ")");
            out.println("============================================================");

            // Decompile
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("// DECOMP FAIL: " + (res != null ? res.getErrorMessage() : "null"));
            }

            // Walk instructions, look for CAL references
            StringBuilder hitBuf = new StringBuilder();
            AddressSetView body = f.getBody();
            AddressIterator it = body.getAddresses(true);
            while (it.hasNext()) {
                Address ip = it.next();
                Instruction insn = listing.getInstructionAt(ip);
                if (insn == null) continue;

                // 1) Operand references resolved by Ghidra
                for (int opIdx = 0; opIdx < insn.getNumOperands(); opIdx++) {
                    Reference[] refs = insn.getOperandReferences(opIdx);
                    for (Reference r : refs) {
                        long t = r.getToAddress().getOffset();
                        if (t >= CAL_DATA_LO && t < CAL_DATA_HI) {
                            String hit = String.format(
                                "  CAL ref @ 0x%08x  insn '%s'  -> 0x%08x  (%s)",
                                ip.getOffset(), insn.toString(), t, r.getReferenceType().toString());
                            hitBuf.append(hit).append("\n");
                        }
                    }
                }

                // 2) Raw scalar operands -- catches literal pool loads where Ghidra
                //    didn't auto-create the reference.
                for (int opIdx = 0; opIdx < insn.getNumOperands(); opIdx++) {
                    Object[] opObjs = insn.getOpObjects(opIdx);
                    for (Object obj : opObjs) {
                        if (obj instanceof Scalar) {
                            long v = ((Scalar) obj).getUnsignedValue();
                            if (v >= CAL_DATA_LO && v < CAL_DATA_HI) {
                                String hit = String.format(
                                    "  CAL scalar @ 0x%08x  insn '%s'  scalar=0x%08x",
                                    ip.getOffset(), insn.toString(), v);
                                hitBuf.append(hit).append("\n");
                            }
                        }
                        if (obj instanceof Address) {
                            long v = ((Address) obj).getOffset();
                            if (v >= CAL_DATA_LO && v < CAL_DATA_HI) {
                                String hit = String.format(
                                    "  CAL addr @ 0x%08x  insn '%s'  addr=0x%08x",
                                    ip.getOffset(), insn.toString(), v);
                                hitBuf.append(hit).append("\n");
                            }
                        }
                    }
                }
            }
            if (hitBuf.length() > 0) {
                out.println();
                out.println("// >>> CAL DATA REFS in " + f.getName() + ":");
                out.println(hitBuf.toString());
                calHits.add("In " + f.getName() + " @ 0x" + Long.toHexString(entry) + ":\n"
                    + hitBuf.toString());
            }

            // Enqueue called functions
            if (depth < MAX_DEPTH) {
                Set<Long> calledSet = new TreeSet<>();
                AddressIterator ai = body.getAddresses(true);
                while (ai.hasNext()) {
                    Address ip = ai.next();
                    Reference[] refs = rm.getReferencesFrom(ip);
                    for (Reference r : refs) {
                        if (r.getReferenceType().isCall()) {
                            calledSet.add(r.getToAddress().getOffset());
                        }
                    }
                }
                for (long callTarget : calledSet) {
                    if (!visited.contains(callTarget)) {
                        work.add(new long[]{callTarget, depth + 1});
                    }
                }
            }
        }

        // Final summary
        out.println();
        out.println("============================================================");
        out.println("CAL DATA-LOAD SUMMARY -- functions reaching 0x80020000-0x80022400");
        out.println("============================================================");
        if (calHits.isEmpty()) {
            out.println("\n  NO CAL data references found in any of "
                + processed + " visited functions.");
            out.println("  This means the gradient limiter does not load from the candidate");
            out.println("  LUT range via any path reachable in <=" + MAX_DEPTH
                + " call levels from the seed entries.");
        } else {
            for (String h : calHits) {
                out.println();
                out.println(h);
            }
        }

        out.println();
        out.println("Stats: " + processed + " functions processed, "
            + visited.size() + " unique addresses visited");

        decomp.dispose();
        out.flush();
        out.close();
        println("Wrote gradient call chain trace -> " + OUT);
    }
}
