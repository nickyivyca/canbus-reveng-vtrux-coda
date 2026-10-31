// DlcmDisasmRange.java
// Clear a range, disassemble it from a chosen start, print the instruction stream and
// report whether it lands cleanly on a known-good boundary.
//
// TriCore instructions are 2 or 4 bytes, so a linear sweep started at the wrong parity or
// mid-instruction decodes plausible-looking garbage.  That is the standing risk with
// `artifacts/call_target_scan.py`, which sweeps raw bytes: it found a call to
// FUN_8006eb8c at 0x8007C2E2, but Ghidra has no instruction there at all, so the hit was
// never checked against a real decode.  This script is how that check is made -- if the
// stream started at `start` runs to exactly `expectEnd` with no bad instruction, the
// alignment is right and what it decodes can be trusted.
//
// Args: <outpath> <clearLo> <clearHi> <start> [expectEnd]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DlcmDisasmRange extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        Address lo = toAddr(a[1]), hi = toAddr(a[2]), start = toAddr(a[3]);
        Address expectEnd = (a.length > 4 && !a[4].isEmpty()) ? toAddr(a[4]) : null;

        out.println("clearing " + lo + " .. " + hi);
        clearListing(new AddressSet(lo, hi));
        out.println("disassembling from " + start);
        disassemble(start);

        Listing listing = currentProgram.getListing();
        Instruction ins = listing.getInstructionAt(start);
        if (ins == null) {
            out.println("  FAILED: nothing disassembled at " + start);
            out.flush(); out.close();
            println("DlcmDisasmRange: nothing decoded");
            return;
        }
        int n = 0;
        Address last = start;
        while (ins != null && ins.getAddress().compareTo(hi) <= 0 && n < 400) {
            out.printf("  %s  %-34s%n", ins.getAddress(), ins.toString());
            last = ins.getAddress().add(ins.getLength() - 1);
            ins = ins.getNext();
            n++;
            if (ins != null && ins.getAddress().compareTo(hi) > 0) break;
        }
        out.println();
        out.println("  instructions decoded: " + n + "   last byte: " + last);
        if (expectEnd != null) {
            Address next = last.add(1);
            out.println("  next address after stream: " + next
                    + (next.equals(expectEnd) ? "   MATCHES expected boundary -- alignment good"
                                              : "   does NOT match expected " + expectEnd));
        }
        out.flush();
        out.close();
        println("DlcmDisasmRange: " + n + " instructions -> " + a[0]);
    }
}
