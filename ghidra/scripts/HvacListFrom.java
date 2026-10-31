// @category Analysis
// Disassemble (follow flow) from each given global address in the HVAC image, after
// setting PPAGE over every flashed page, and print the decoded stream in address order.
// Read-only on the database when run with -readOnly. Used for step 1a of
// projects/coda/notes/plans/hvac_firmware_re.md.
// Args: <outpath> <comma-separated hex addresses> [maxInstructions]
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import java.io.*;
import java.math.BigInteger;

public class HvacListFrom extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        int max = a.length > 2 ? Integer.parseInt(a[2]) : 400;
        Register ppage = currentProgram.getRegister("PPAGE");
        for (int pg = 0xE0; pg <= 0xFF; pg++) {
            long lo = 0x400000L | ((long) pg << 14);
            currentProgram.getProgramContext().setValue(ppage, toAddr(lo), toAddr(lo + 0x3FFF), BigInteger.valueOf(pg));
        }
        Listing listing = currentProgram.getListing();
        for (String s : a[1].split(",")) {
            Address at = toAddr(Long.parseLong(s, 16));
            AddressSetView got = new DisassembleCommand(at, null, true).applyTo(currentProgram, monitor)
                    ? listing.getInstructions(at, true).hasNext() ? null : null : null;
            out.println("=== from " + at + " ===");
            InstructionIterator it = listing.getInstructions(at, true);
            int n = 0;
            Address prevEnd = null;
            while (it.hasNext() && n < max) {
                Instruction ins = it.next();
                if (prevEnd != null && !ins.getAddress().equals(prevEnd))
                    out.printf("  ---- gap to %s ----%n", ins.getAddress());
                StringBuilder fl = new StringBuilder();
                for (Address f : ins.getFlows()) fl.append(" ->").append(f);
                out.printf("  %s  %-12s %-34s%s%s%n", ins.getAddress(), bytesHex(ins), ins.toString(),
                        ins.getFlowType().isTerminal() ? " [TERM]" : "", fl);
                prevEnd = ins.getAddress().add(ins.getLength());
                n++;
            }
        }
        out.close();
    }
    String bytesHex(Instruction ins) throws Exception {
        StringBuilder sb = new StringBuilder();
        for (byte b : ins.getBytes()) sb.append(String.format("%02X", b & 0xFF));
        return sb.toString();
    }
}
