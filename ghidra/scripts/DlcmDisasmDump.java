// @category Analysis
// Dump raw SH-4 disassembly listings for Goals 1, 3, and VBR handlers,
// plus decompile every function with a body >= 20 bytes in key ranges.

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DlcmDisasmDump extends GhidraScript {

    static final String OUT = "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\disasm_dump.txt";

    // Goal 1: startup chain range
    static final long G1_START = 0x80040052L;
    static final long G1_END   = 0x80041000L;

    // Goal 3: state machine area
    static final long G3_START = 0x80041A00L;
    static final long G3_END   = 0x80042300L;

    // VBR candidate = 0x8005DED8 (score 3/3, dlcm_vbr_scan.py)
    // Handler entry points: VBR+0x100, VBR+0x400, VBR+0x600
    static final long VBR_BASE        = 0x8005DED8L;
    static final long VBR_GEN_EXC     = 0x8005DFD8L;  // general exception VBR+0x100
    static final long VBR_TLB_MISS    = 0x8005E2D8L;  // TLB miss          VBR+0x400
    static final long VBR_INTERRUPT   = 0x8005E4D8L;  // interrupt         VBR+0x600
    static final long VBR_HANDLER_END = 0x8005E8D8L;  // covers all three (+0x400 each)

    @Override
    public void run() throws Exception {
        AddressSpace sp   = currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing   = currentProgram.getListing();

        PrintWriter out = new PrintWriter(new FileWriter(OUT));

        // ----------------------------------------------------------------
        // First: fix function bodies for key addresses by finding body extents
        // We do this by scanning forward from each entry point until we hit
        // an instruction that is the entry of ANOTHER known function.
        // ----------------------------------------------------------------
        long[] keyAddrs = {
            // Startup
            0x80040052L, 0x80040AB0L,
            // State machine
            0x80041E44L, 0x80041E9CL, 0x80042030L, 0x80042036L,
            // VBR setup
            0x8005D22AL, 0x8005E2ACL,
            // VBR handlers (candidate VBR=0x8005DED8)
            0x8005DFD8L, 0x8005E2D8L, 0x8005E4D8L,
        };
        for (long addr : keyAddrs) {
            Address a = sp.getAddress(addr);
            if (fm.getFunctionAt(a) == null) {
                CreateFunctionCmd cmd = new CreateFunctionCmd(a);
                cmd.applyTo(currentProgram, monitor);
            }
        }

        // ----------------------------------------------------------------
        // Dump disassembly for Goal 1 startup range
        // ----------------------------------------------------------------
        dumpRange(listing, fm, sp, G1_START, G1_END, "GOAL 1 - STARTUP 0x80040052-0x80041000", out);

        // ----------------------------------------------------------------
        // Dump disassembly for VBR handler regions
        //   VBR candidate = 0x8005DED8
        //   General exception: VBR+0x100 = 0x8005DFD8
        //   TLB miss:          VBR+0x400 = 0x8005E2D8
        //   Interrupt:         VBR+0x600 = 0x8005E4D8
        // ----------------------------------------------------------------
        dumpRange(listing, fm, sp, VBR_GEN_EXC, VBR_TLB_MISS,
                  "VBR GENERAL EXCEPTION HANDLER 0x8005DFD8-0x8005E2D8", out);
        dumpRange(listing, fm, sp, VBR_TLB_MISS, VBR_INTERRUPT,
                  "VBR TLB MISS HANDLER 0x8005E2D8-0x8005E4D8", out);
        dumpRange(listing, fm, sp, VBR_INTERRUPT, VBR_HANDLER_END,
                  "VBR INTERRUPT HANDLER 0x8005E4D8-0x8005E8D8", out);

        // ----------------------------------------------------------------
        // Dump disassembly for Goal 3 state machine range
        // ----------------------------------------------------------------
        dumpRange(listing, fm, sp, G3_START, G3_END, "GOAL 3 - STATE MACHINE 0x80041A00-0x80042300", out);

        // ----------------------------------------------------------------
        // Decompile every function with body >= 20 bytes in key ranges:
        //   - G1 startup
        //   - G3 state machine
        //   - VBR handler band (0x8005DFD8-0x8005E8D8)
        // ----------------------------------------------------------------
        out.println();
        out.println("============================================================");
        out.println("DECOMPILE ATTEMPTS (functions with body >= 20 bytes in key ranges)");
        out.println("============================================================");

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);

        Set<Long> decompAddrs = new TreeSet<>();

        // Scan G1, G3, and VBR handler band for functions with substantial bodies
        long[][] scanRanges = {
            {G1_START, G1_END},
            {G3_START, G3_END},
            {VBR_GEN_EXC, VBR_HANDLER_END},
        };
        for (long[] range : scanRanges) {
            for (long s = range[0]; s <= range[1]; s += 2) {
                Address a = sp.getAddress(s);
                Function f = fm.getFunctionAt(a);
                if (f != null) {
                    long sz = f.getBody().getMaxAddress().getOffset()
                            - f.getBody().getMinAddress().getOffset() + 1;
                    if (sz >= 20) decompAddrs.add(f.getEntryPoint().getOffset());
                }
            }
        }

        // Also explicitly include the VBR handler entry points regardless of body size
        decompAddrs.add(VBR_GEN_EXC);
        decompAddrs.add(VBR_TLB_MISS);
        decompAddrs.add(VBR_INTERRUPT);

        println("Found " + decompAddrs.size() + " functions with body >= 20 bytes in key ranges");
        for (long addr : decompAddrs) {
            Address a = sp.getAddress(addr);
            Function f = fm.getFunctionAt(a);
            if (f == null) continue;
            long sz = f.getBody().getMaxAddress().getOffset()
                    - f.getBody().getMinAddress().getOffset() + 1;
            out.println();
            out.println("// --- " + f.getName() + " @ 0x" + Long.toHexString(addr)
                + "  body=" + sz + " bytes ---");
            DecompileResults res = decomp.decompileFunction(f, 30, monitor);
            if (res != null && res.decompileCompleted()) {
                out.println(res.getDecompiledFunction().getC());
            } else {
                out.println("// FAIL: " + (res != null ? res.getErrorMessage() : "null"));
            }
        }

        decomp.dispose();
        out.flush();
        out.close();
        println("Wrote disasm dump -> " + OUT);
    }

    void dumpRange(Listing listing, FunctionManager fm, AddressSpace sp,
                   long startVa, long endVa, String header, PrintWriter out) {
        out.println();
        out.println("============================================================");
        out.println(header);
        out.println("============================================================");

        Address curr = sp.getAddress(startVa);
        Address end  = sp.getAddress(endVa);
        String lastFn = "";

        while (curr.compareTo(end) <= 0) {
            // Show function boundary if entering a new function
            Function f = fm.getFunctionAt(curr);
            if (f != null && !f.getName().equals(lastFn)) {
                long sz = f.getBody().getMaxAddress().getOffset()
                        - f.getBody().getMinAddress().getOffset() + 1;
                out.println();
                out.println("  ;; --- " + f.getName()
                    + "  body=" + sz + " bytes ---");
                lastFn = f.getName();
            }

            Instruction instr = listing.getInstructionAt(curr);
            if (instr != null) {
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  0x%08X  ", curr.getOffset()));
                // Instruction bytes
                int len = instr.getLength();
                byte[] bytes = new byte[len];
                try { instr.getBytesInCodeUnit(bytes, 0); } catch (Exception ex) {}
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                sb.append("  ");
                sb.append(instr.toString());
                out.println(sb.toString());
                try { curr = curr.add(instr.getLength()); } catch (Exception e) { break; }
            } else {
                Data d = listing.getDataAt(curr);
                int sz = (d != null) ? d.getLength() : 2;
                byte[] bytes = new byte[sz];
                try {
                    for (int i = 0; i < sz; i++) {
                        bytes[i] = (byte) currentProgram.getMemory().getByte(curr.add(i));
                    }
                } catch (Exception ex) {}
                StringBuilder sb = new StringBuilder();
                sb.append(String.format("  0x%08X  [data] ", curr.getOffset()));
                for (byte b : bytes) sb.append(String.format("%02X ", b));
                out.println(sb.toString());
                try { curr = curr.add(Math.max(sz, 2)); } catch (Exception e) { break; }
            }
        }
    }
}
