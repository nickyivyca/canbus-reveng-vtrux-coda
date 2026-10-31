// Lists every reference to a set of addresses, with the containing function.
//
// Written 2026-09-20 to answer: which code reads the SECOND LUT descriptor
// block at 0x80040920, as opposed to the main block at 0x80043F88?  Both hold
// a full set of gradient-limiter tables and neither is reachable through a
// pointer table, so the addresses are built in code (movh.a + lea) and only
// the reference manager can find them.
//
// args: <outfile> <comma-separated hex addresses>
//@category DLCM
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.PrintWriter;

public class DlcmAddrXref extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(args[0]);
        for (String tok : args[1].split(",")) {
            tok = tok.trim();
            if (tok.isEmpty()) continue;
            long a = Long.parseLong(tok.replace("0x", ""), 16);
            Address addr = currentProgram.getAddressFactory()
                    .getDefaultAddressSpace().getAddress(a);
            out.printf("=== 0x%08X ===%n", a);
            ReferenceIterator it = currentProgram.getReferenceManager()
                    .getReferencesTo(addr);
            int n = 0;
            while (it.hasNext()) {
                Reference r = it.next();
                Address from = r.getFromAddress();
                Function f = getFunctionContaining(from);
                out.printf("  from 0x%s  %-14s  %s%n", from,
                        r.getReferenceType(),
                        f == null ? "(no function)" : f.getName() + " @ " + f.getEntryPoint());
                n++;
            }
            if (n == 0) out.println("  (no references found)");
            out.printf("  total %d%n", n);
        }
        out.close();
    }
}
