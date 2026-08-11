// @category Analysis
// Minimal test: count functions and try one decompile

import ghidra.app.decompiler.*;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import java.io.*;

public class DlcmTest extends GhidraScript {
    @Override
    public void run() throws Exception {
        PrintWriter out = new PrintWriter(new FileWriter(
            "C:\\Users\\<user>\\AppData\\Local\\ghidra-projects\\dlcm_export\\test_output.txt"));

        FunctionManager fm = currentProgram.getFunctionManager();
        int count = 0;
        FunctionIterator fi = fm.getFunctions(true);
        while (fi.hasNext()) { fi.next(); count++; }
        out.println("Function count: " + count);
        println("Function count: " + count);

        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address a = sp.getAddress(0x80040052L);
        Function f = fm.getFunctionAt(a);
        if (f == null) {
            out.println("reset_entry function NOT found at 0x80040052");
            println("reset_entry not found");
        } else {
            out.println("reset_entry found: " + f.getName());
            println("reset_entry found: " + f.getName());

            DecompInterface decomp = new DecompInterface();
            decomp.openProgram(currentProgram);
            DecompileResults res = decomp.decompileFunction(f, 30, monitor);
            if (res != null && res.decompileCompleted()) {
                String code = res.getDecompiledFunction().getC();
                out.println("DECOMPILE SUCCESS, length=" + code.length());
                out.println(code.substring(0, Math.min(500, code.length())));
                println("Decompile success");
            } else {
                String msg = (res != null) ? res.getErrorMessage() : "null";
                out.println("DECOMPILE FAILED: " + msg);
                println("Decompile failed: " + msg);
            }
            decomp.dispose();
        }

        out.flush();
        out.close();
        println("Test complete");
    }
}
