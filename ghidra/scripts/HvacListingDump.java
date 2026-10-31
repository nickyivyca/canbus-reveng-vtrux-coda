// @category Analysis
// Dump every decoded instruction of the HVAC program as one TSV row, for analysis in
// Python (register and RAM access sweeps, step 2 onward of
// projects/coda/notes/plans/hvac_firmware_re.md). Read-only on the database.
// Columns: addr, function entry (or -), bytes, instruction text, references
// (space-separated "type:addr"), all addresses global hex.
// Args: <outpath>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class HvacListingDump extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        out.println("addr\tfunc\tbytes\ttext\trefs");
        InstructionIterator it = listing.getInstructions(true);
        int n = 0;
        while (it.hasNext()) {
            Instruction ins = it.next();
            Function f = fm.getFunctionContaining(ins.getAddress());
            StringBuilder b = new StringBuilder();
            for (byte x : ins.getBytes()) b.append(String.format("%02X", x & 0xFF));
            StringBuilder r = new StringBuilder();
            for (Reference ref : ins.getReferencesFrom()) {
                if (r.length() > 0) r.append(' ');
                r.append(ref.getReferenceType().getName()).append(':')
                 .append(String.format("%06X", ref.getToAddress().getOffset()));
            }
            out.printf("%06X\t%s\t%s\t%s\t%s%n", ins.getAddress().getOffset(),
                    f == null ? "-" : String.format("%06X", f.getEntryPoint().getOffset()),
                    b, ins.toString(), r);
            n++;
        }
        out.close();
        println("HvacListingDump: " + n + " instructions -> " + a[0]);
    }
}
