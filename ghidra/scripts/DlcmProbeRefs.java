// DlcmProbeRefs.java
// Print the flow type, flows and outgoing references of specific instructions, and
// the function containing each address.  Diagnostic aid for the tail-call work:
// TriCore `j <function>` is a tail call, and the question is exactly how Ghidra
// classifies it, since that determines which API sees it as a caller.
//
// Args: <outpath> <comma-separated hex addresses>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class DlcmProbeRefs extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(args[0]));
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        for (String a : args[1].split(",")) {
            a = a.trim();
            Address addr = toAddr(a.startsWith("0x") ? a.substring(2) : a);
            out.println("================ " + addr + " ================");
            Function c = fnMgr.getFunctionContaining(addr);
            out.println("  containing function: "
                    + (c == null ? "(none)" : c.getName() + " @" + c.getEntryPoint()
                       + (c.isThunk() ? "  [THUNK -> " + c.getThunkedFunction(true).getName() + "]" : "")
                       + "  body=" + c.getBody().getNumAddresses() + "B"));
            Function at = fnMgr.getFunctionAt(addr);
            out.println("  function AT this address: " + (at == null ? "(none)" : at.getName()));
            Instruction ins = getInstructionAt(addr);
            if (ins == null) { out.println("  no instruction"); out.println(); continue; }
            out.println("  insn: " + ins.toString());
            out.println("  flowType: " + ins.getFlowType()
                    + "   isJump=" + ins.getFlowType().isJump()
                    + " isCall=" + ins.getFlowType().isCall()
                    + " isTerminal=" + ins.getFlowType().isTerminal()
                    + " isConditional=" + ins.getFlowType().isConditional()
                    + " isComputed=" + ins.getFlowType().isComputed());
            Address[] flows = ins.getFlows();
            out.println("  getFlows(): " + flows.length);
            for (Address f : flows) out.println("      -> " + f);
            out.println("  referencesFrom:");
            for (Reference r : ins.getReferencesFrom()) {
                out.println("      -> " + r.getToAddress() + "  type=" + r.getReferenceType()
                        + "  isCall=" + r.getReferenceType().isCall()
                        + "  isJump=" + r.getReferenceType().isJump());
            }
            out.println();
        }
        out.flush();
        out.close();
        println("DlcmProbeRefs: wrote " + args[0]);
    }
}
