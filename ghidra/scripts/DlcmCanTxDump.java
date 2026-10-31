// DlcmCanTxDump.java
// Find all references to the CAN descriptor table region and the CAN pointer array.
// Also find all stores to peripheral addresses (0xAFxxxxxx range) to locate CAN TX driver.
// Outputs to dlcm_export/can_tx_dump.txt
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.pcode.*;
import ghidra.app.decompiler.*;
import java.io.*;
import java.util.*;

public class DlcmCanTxDump extends GhidraScript {

    PrintWriter out;
    DecompInterface decompiler;

    @Override
    public void run() throws Exception {
        // Honour args[0] when given.  Until 2026-10-06 this path was hardcoded to a
        // Windows absolute path and args were ignored: on Linux the run "succeeded"
        // and created a file literally named C:\Users\... in the CWD, while the
        // requested output path did not exist.  A silently misdirected output.
        String outPath = "can_tx_dump.txt";
        String[] a = getScriptArgs();
        if (a.length > 0 && a[0].length() > 0) outPath = a[0];
        out = new PrintWriter(new FileWriter(outPath));

        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);

        AddressFactory addrFac = currentProgram.getAddressFactory();
        AddressSpace as = addrFac.getDefaultAddressSpace();

        // CAN descriptor table range and pointer array
        Address canDescLo = as.getAddress("0x80042200");
        Address canDescHi = as.getAddress("0x80042800");

        // Peripheral range
        Address periphLo = as.getAddress("0xAF000000");
        Address periphHi = as.getAddress("0xAFFFFFFF");

        Listing listing = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();
        ReferenceManager refMgr = currentProgram.getReferenceManager();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        // 1. Find all instructions that reference the CAN descriptor range
        out.println("=== XREFS TO CAN DESCRIPTOR REGION [0x80042200, 0x80042800] ===");
        println("Scanning xrefs to CAN descriptor region...");

        Set<Function> canRefFunctions = new HashSet<>();
        AddressSet canDescRange = new AddressSet(canDescLo, canDescHi);

        ReferenceIterator refs = refMgr.getReferencesTo(canDescLo);
        // Iterate all addresses in range
        AddressIterator addrIter = canDescRange.getAddresses(true);
        int refCount = 0;
        while (addrIter.hasNext()) {
            Address addr = addrIter.next();
            ReferenceIterator ri = refMgr.getReferencesTo(addr);
            while (ri.hasNext()) {
                Reference ref = ri.next();
                Address fromAddr = ref.getFromAddress();
                Function fn = fnMgr.getFunctionContaining(fromAddr);
                String fnName = (fn != null) ? fn.getName() + " @" + fn.getEntryPoint() : "(no function)";
                out.printf("  %s -> %s  [%s]  in %s%n",
                    fromAddr, addr, ref.getReferenceType(), fnName);
                if (fn != null) canRefFunctions.add(fn);
                refCount++;
                if (refCount > 500) break;
            }
            if (refCount > 500) break;
        }
        out.printf("Total refs found: %d%n%n", refCount);

        // 2. Decompile the functions that reference the CAN descriptor range
        out.println("=== DECOMPILE OF FUNCTIONS ACCESSING CAN DESCRIPTOR REGION ===");
        println("Decompiling " + canRefFunctions.size() + " CAN-descriptor-referencing functions...");
        for (Function fn : canRefFunctions) {
            out.printf("%n--- Function: %s at %s (size=%d) ---%n",
                fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses());
            DecompileResults res = decompiler.decompileFunction(fn, 30, monitor);
            if (res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("  [decompile failed: " + res.getErrorMessage() + "]");
            }
        }

        // 3. Find all stores to peripheral addresses (0xAFxxxxxx) - these are the CAN TX writes
        out.println("\n=== INSTRUCTIONS WRITING TO PERIPHERAL ADDRESSES (0xAFxxxxxx) ===");
        println("Scanning for peripheral writes...");
        int periph_count = 0;
        InstructionIterator instrIter = listing.getInstructions(true);
        while (instrIter.hasNext()) {
            Instruction instr = instrIter.next();
            Reference[] instrRefs = instr.getReferencesFrom();
            for (Reference r : instrRefs) {
                if (r.getReferenceType().isWrite()) {
                    Address toAddr = r.getToAddress();
                    if (toAddr.getOffset() >= 0xAF000000L && toAddr.getOffset() <= 0xAFFF0000L) {
                        Function fn = fnMgr.getFunctionContaining(instr.getAddress());
                        String fnStr = (fn != null) ? fn.getName() + "@" + fn.getEntryPoint() : "(no fn)";
                        out.printf("  WRITE %s -> %s  [%s]  in %s%n",
                            instr.getAddress(), toAddr, instr.getMnemonicString(), fnStr);
                        periph_count++;
                    }
                }
            }
        }
        out.printf("Total peripheral writes: %d%n%n", periph_count);

        // 4. Also decompile the function at the only real code loader we found
        out.println("\n=== DECOMPILE: Function containing 0x80082774 ===");
        Address addr82774 = as.getAddress("0x80082774");
        Function fn82774 = fnMgr.getFunctionContaining(addr82774);
        if (fn82774 != null) {
            out.printf("Function: %s at %s%n", fn82774.getName(), fn82774.getEntryPoint());
            DecompileResults res = decompiler.decompileFunction(fn82774, 30, monitor);
            if (res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("[failed: " + res.getErrorMessage() + "]");
            }
        } else {
            out.println("No function contains 0x80082774 (in a gap)");

            // Try creating a function there and decompiling
            out.println("Attempting to create function at 0x80082774...");
            Function newFn = createFunction(addr82774, null);
            if (newFn != null) {
                DecompileResults res = decompiler.decompileFunction(newFn, 30, monitor);
                if (res.decompileCompleted()) {
                    out.println(res.getDecompiledFunction().getC());
                } else {
                    out.println("[failed after create: " + res.getErrorMessage() + "]");
                }
            }
        }

        // 5. Look at what calls the main state machine functions (around 0x80060000-0x80080000)
        // that are involved in periodic CAN TX
        out.println("\n=== LARGE FUNCTIONS in 0x80060000-0x80080000 that might be CAN TX ===");
        Address rangeStart = as.getAddress("0x80060000");
        Address rangeEnd   = as.getAddress("0x80080000");
        FunctionIterator fnIter = fnMgr.getFunctions(rangeStart, true);
        int bigFnCount = 0;
        while (fnIter.hasNext() && bigFnCount < 20) {
            Function fn = fnIter.next();
            if (fn.getEntryPoint().compareTo(rangeEnd) > 0) break;
            if (fn.getBody().getNumAddresses() > 100) {
                out.printf("  %s at %s  size=%d%n",
                    fn.getName(), fn.getEntryPoint(), fn.getBody().getNumAddresses());
                bigFnCount++;
            }
        }

        out.flush();
        out.close();
        decompiler.dispose();
        println("Done. Output: " + outPath);
    }
}
