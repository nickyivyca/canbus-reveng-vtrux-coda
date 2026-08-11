// DlcmGapDecompile.java
// Seed function creation at discovered entry points in the large gap (0x8006A738-0x8006CCA0)
// and at the CAN TX helper 0x8006CE4C, then decompile.
// Also decompile the functions in 0x8006E1xx-0x8006E4xx (CAN TX serialize loop).
// Outputs to dlcm_export/gap_decompile.txt
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.decompiler.*;
import java.io.*;
import java.util.*;

public class DlcmGapDecompile extends GhidraScript {

    PrintWriter out;
    DecompInterface decompiler;
    FunctionManager fnMgr;

    @Override
    public void run() throws Exception {
        String outPath = "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\gap_decompile.txt";
        out = new PrintWriter(new FileWriter(outPath));
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        fnMgr = currentProgram.getFunctionManager();
        AddressFactory af = currentProgram.getAddressFactory();
        AddressSpace as = af.getDefaultAddressSpace();

        // 1. Key entry points found by Python scan:
        // - 0x8006CE4C: CAN TX helper called when dispatching 0x212 (BSR from 0x8006D9E8)
        // - Large gap entry points (called via BSR/BRA from outside gap)
        // - 0x8006E202-0x8006E3CC: the CAN TX serialize loop functions
        long[] seedAddrs = {
            // CAN TX helper - most important
            0x8006CE4CL,
            // Gap entry points with multiple callers or at gap start
            0x8006A7A2L, 0x8006A7A4L, 0x8006A7A6L, 0x8006A7BAL, 0x8006A7E6L,
            0x8006A818L, 0x8006A8D6L, 0x8006AAB4L, 0x8006AB16L, 0x8006AC32L,
            0x8006ACBCL, 0x8006ACF2L, 0x8006AD92L, 0x8006AEA2L, 0x8006AFC4L,
            0x8006B056L, 0x8006B070L, 0x8006B07AL, 0x8006B08AL, 0x8006B0A4L,
            0x8006B0BEL, 0x8006B0DAL, 0x8006B114L, 0x8006B52CL,
            0x8006BF1AL, 0x8006BF2AL,
            0x8006C19AL, 0x8006C256L, 0x8006C32CL,
            0x8006C406L, 0x8006C594L, 0x8006C5A8L,
            0x8006C630L, 0x8006C644L, 0x8006C688L, 0x8006C69CL,
            0x8006C6E0L, 0x8006C6F4L, 0x8006C738L, 0x8006C74CL,
            0x8006C900L, 0x8006C95AL, 0x8006C984L,
            0x8006CAA2L, 0x8006CAB6L, 0x8006CB2AL, 0x8006CB32L,
            0x8006CB3EL, 0x8006CB6EL, 0x8006CB82L, 0x8006CB94L,
            0x8006CB96L, 0x8006CBDAL, 0x8006CBEEL,
            0x8006CC32L, 0x8006CC46L,
            // CAN serialize functions in 0x8006E2xx
            0x8006E202L, 0x8006E262L, 0x8006E282L, 0x8006E2ACL,
            0x8006E2C4L, 0x8006E2DAL, 0x8006E304L, 0x8006E31CL,
            0x8006E332L, 0x8006E35CL, 0x8006E374L, 0x8006E38AL,
            0x8006E3B4L, 0x8006E3CCL,
            // Small helpers called from CAN TX region
            0x8006D17EL, 0x8006D192L, 0x8006D076L, 0x8006D0CEL,
            0x8006D0E2L, 0x8006D126L, 0x8006D13AL, 0x8006D06EL,
        };

        // 2. Create functions at seed addresses
        out.println("=== FUNCTION CREATION ===");
        println("Creating functions at " + seedAddrs.length + " seed addresses...");
        List<Function> createdFunctions = new ArrayList<>();
        for (long addrLong : seedAddrs) {
            Address addr = as.getAddress(Long.toHexString(addrLong));
            Function existing = fnMgr.getFunctionContaining(addr);
            if (existing != null) {
                out.printf("  EXISTING  0x%X  ->  %s%n", addrLong, existing.getName());
                if (!createdFunctions.contains(existing)) createdFunctions.add(existing);
            } else {
                Function created = createFunction(addr, null);
                if (created != null) {
                    out.printf("  CREATED   0x%X  ->  %s (size=%d)%n",
                        addrLong, created.getName(), created.getBody().getNumAddresses());
                    createdFunctions.add(created);
                } else {
                    out.printf("  FAILED    0x%X%n", addrLong);
                }
            }
        }

        // 3. Decompile each created/found function
        out.println("\n=== DECOMPILATIONS ===");
        println("Decompiling " + createdFunctions.size() + " functions...");
        Set<Address> done = new HashSet<>();
        for (Function fn : createdFunctions) {
            if (done.contains(fn.getEntryPoint())) continue;
            done.add(fn.getEntryPoint());
            out.printf("%n--- %s  at 0x%X  (size=%d) ---%n",
                fn.getName(), fn.getEntryPoint().getOffset(), fn.getBody().getNumAddresses());
            DecompileResults res = decompiler.decompileFunction(fn, 60, monitor);
            if (res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("  [decompile failed: " + res.getErrorMessage() + "]");
            }
            out.flush();
        }

        // 4. Also list all functions now in the gap region, including ones Ghidra discovered
        out.println("\n=== ALL FUNCTIONS IN GAP 0x8006A738-0x8006CCA0 (after seeding) ===");
        Address gapLo = as.getAddress("0x8006A738");
        Address gapHi = as.getAddress("0x8006CCA0");
        FunctionIterator fi = fnMgr.getFunctions(gapLo, true);
        int gapCount = 0;
        while (fi.hasNext()) {
            Function fn = fi.next();
            if (fn.getEntryPoint().compareTo(gapHi) > 0) break;
            out.printf("  %s  @0x%X  size=%d%n",
                fn.getName(), fn.getEntryPoint().getOffset(), fn.getBody().getNumAddresses());
            gapCount++;
        }
        out.printf("Total: %d functions in gap%n", gapCount);

        // 5. Also look for functions near 0x8006D7B0-0x8006DA70 (CAN TX serialize function)
        out.println("\n=== FUNCTIONS 0x8006D700-0x8006E500 ===");
        Address txLo = as.getAddress("0x8006D700");
        Address txHi = as.getAddress("0x8006E500");
        FunctionIterator fi2 = fnMgr.getFunctions(txLo, true);
        while (fi2.hasNext()) {
            Function fn = fi2.next();
            if (fn.getEntryPoint().compareTo(txHi) > 0) break;
            out.printf("  %s  @0x%X  size=%d%n",
                fn.getName(), fn.getEntryPoint().getOffset(), fn.getBody().getNumAddresses());
        }

        out.flush();
        out.close();
        decompiler.dispose();
        println("Done. Output: " + outPath);
    }
}
