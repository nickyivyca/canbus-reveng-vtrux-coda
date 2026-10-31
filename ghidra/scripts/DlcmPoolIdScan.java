// Every call site of the indexed signal-pool accessors, with the signal id
// that the call site loads into d4.
//
// Written 2026-10-04 while identifying DLCM P3115 reason-1 "signal B"
// (0xD0008316 = *(byte*)0xD0007590 * 0x80).  That byte is byte 4 of a 6-byte
// block loaded from pool record 0x2080, and the question is which code writes
// and reads the other records of the same pool bank -- i.e. what device is on
// the far end of the link.
//
// The pool accessors are:
//   FUN_80064574(dest, id, count)  read  count u16 elements  (desc+0x14 array)
//   FUN_80064520(src,  id, count)  write count u16 elements  (desc+0x10 array)
//   FUN_800645c8(id)               commit / trigger the record
//   FUN_8008ea3e(id, n)            per-element operation
// id decomposes as bank=(id>>13)&1, record=(id>>7)&0x3f, element=id&0x7f.
//
// The id is almost always a literal, loaded with "mov d4,#imm" (or into d15
// and then "mov d4,d15") a few instructions before the call, so this walks
// backwards from each call site looking for that load.  Call sites where no
// literal is found are printed as "?" rather than skipped, so a computed id
// cannot pass unnoticed as an absent one.
//
// args: <outfile> [comma-separated target function entry addresses]
//@category DLCM
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.PrintWriter;
import java.util.*;

public class DlcmPoolIdScan extends GhidraScript {

    static final int LOOKBACK = 16;

    // The last literal moved into d4 at or before `site`, following a
    // "mov d4,dN" back to the literal that set dN.
    String idAt(Address site) {
        Listing lst = currentProgram.getListing();
        List<Instruction> pre = new ArrayList<>();
        Instruction in = lst.getInstructionAt(site);
        for (int i = 0; i < LOOKBACK && in != null; i++) {
            in = lst.getInstructionBefore(in.getAddress());
            if (in != null) pre.add(in);
        }
        String want = "d4";
        for (Instruction i : pre) {
            if (!i.getMnemonicString().startsWith("mov")) continue;
            Object[] dst = i.getOpObjects(0);
            if (dst.length == 0 || !(dst[0] instanceof Register)) continue;
            if (!((Register) dst[0]).getName().equals(want)) continue;
            Object[] src = i.getNumOperands() > 1 ? i.getOpObjects(1) : new Object[0];
            if (src.length > 0 && src[0] instanceof Scalar)
                return String.format("0x%04X", ((Scalar) src[0]).getUnsignedValue());
            if (src.length > 0 && src[0] instanceof Register) {
                want = ((Register) src[0]).getName();   // chase the alias
                continue;
            }
            return "?";
        }
        return "?";
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(args[0]);
        String[] targets = (args.length > 1 ? args[1]
                : "0x80064574,0x80064520,0x800645c8,0x8008ea3e").split(",");

        out.println("=== indexed signal-pool call sites ===");
        for (String t : targets) {
            Address fa = toAddr(Long.parseLong(t.trim().replace("0x", ""), 16));
            Function f = getFunctionAt(fa);
            out.println("");
            out.printf("---- %s @%s ----%n", f == null ? "(no function)" : f.getName(), fa);
            out.printf("  %-10s %-8s %-6s %-7s %-8s %s%n",
                    "site", "id", "bank", "record", "element", "in");
            ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(fa);
            List<String> rows = new ArrayList<>();
            while (it.hasNext()) {
                Reference r = it.next();
                if (!r.getReferenceType().isCall() && !r.getReferenceType().isJump()) continue;
                Address site = r.getFromAddress();
                Function c = getFunctionContaining(site);
                String id = idAt(site);
                String bank = "?", rec = "?", el = "?";
                if (!id.equals("?")) {
                    int v = Integer.parseInt(id.substring(2), 16);
                    bank = String.valueOf((v >> 13) & 1);
                    rec = String.valueOf((v >> 7) & 0x3f);
                    el = String.valueOf(v & 0x7f);
                }
                rows.add(String.format("  %-10s %-8s %-6s %-7s %-8s %s",
                        site, id, bank, rec, el, c == null ? "-" : c.getName()));
            }
            Collections.sort(rows);
            for (String s : rows) out.println(s);
            if (rows.isEmpty()) out.println("  (no call references)");
        }
        out.close();
    }
}
