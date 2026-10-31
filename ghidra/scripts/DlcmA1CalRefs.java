// DlcmA1CalRefs.java
// Enumerate every calibration scalar the application code references directly.
//
// TriCore A1 is the second global address register.  The startup pair at
// 0x800400B8/0x800400BC is
//
//     movh.a a1,#0xa003
//     lea    a1,[a1]-0x8000        ->  A1 = 0xA0028000
//
// and the CAL region is 0xA0020000-0xA0028000, so **every A1-relative load with a
// negative offset is a direct reference to a calibration constant**, resolvable as
//
//     cal_addr = 0xA0028000 + offset        (offset negative)
//
// This matters because coda-dlcm-decompile-notes.md records that the torque path
// reaches its calibration only through descriptors and that "no literal addresses"
// appear in application code.  That is true of the LUT descriptors; it is not true
// of scalars, which come through A1 and were therefore invisible to every
// code-address scan run so far.
//
// For each hit the script prints the CAL offset and the value stored there,
// decoded as u8/u16/i16, so a threshold can be recognised on sight.
//
// Args: <outpath> [calbinpath]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class DlcmA1CalRefs extends GhidraScript {

    static final long A1_BASE = 0xA0028000L;
    static final long CAL_BASE = 0xA0020000L;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = (args.length > 0 && !args[0].isEmpty())
                ? args[0]
                : System.getProperty("user.home") + "/ghidra-projects/dlcm_export/a1_cal_refs.txt";
        String calPath = (args.length > 1 && !args[1].isEmpty())
                ? args[1]
                : null;
        new File(outPath).getParentFile().mkdirs();
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        byte[] cal = null;
        if (calPath != null && Files.exists(Paths.get(calPath))) {
            cal = Files.readAllBytes(Paths.get(calPath));
            out.println("CAL image: " + calPath + " (" + cal.length + " bytes)");
        } else {
            out.println("CAL image: not supplied -- values omitted");
        }
        out.println("A1 = 0x%08X   CAL base = 0x%08X".formatted(A1_BASE, CAL_BASE));
        out.println();

        Listing listing = currentProgram.getListing();
        FunctionManager fnMgr = currentProgram.getFunctionManager();

        // offset -> list of "addr  insn  fn"
        Map<Long, List<String>> byOff = new TreeMap<>();
        InstructionIterator it = listing.getInstructions(true);
        long scanned = 0;
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            scanned++;
            String t = ins.toString();
            int i = t.indexOf("[a1]");
            if (i < 0) continue;
            // parse the displacement that follows "[a1]"
            String rest = t.substring(i + 4).trim();
            boolean neg = rest.startsWith("-");
            if (neg) rest = rest.substring(1);
            if (rest.startsWith("#")) rest = rest.substring(1);
            int end = 0;
            while (end < rest.length()
                   && (Character.isLetterOrDigit(rest.charAt(end)) || rest.charAt(end) == 'x')) end++;
            String numTxt = rest.substring(0, end);
            long disp;
            try {
                disp = numTxt.startsWith("0x") || numTxt.startsWith("0X")
                        ? Long.parseLong(numTxt.substring(2), 16)
                        : Long.parseLong(numTxt);
            } catch (Exception e) { continue; }
            if (neg) disp = -disp;

            long calAddr = A1_BASE + disp;
            if (calAddr < CAL_BASE || calAddr >= A1_BASE) continue;

            Function fn = fnMgr.getFunctionContaining(ins.getAddress());
            byOff.computeIfAbsent(calAddr, k -> new ArrayList<>())
                 .add(ins.getAddress() + "  " + t + "   in "
                      + (fn != null ? fn.getName() + " @" + fn.getEntryPoint() : "(none)"));
        }

        out.println("instructions scanned: " + scanned);
        out.println("distinct CAL addresses referenced through A1: " + byOff.size());
        out.println();
        out.println("  cal addr     off      u8    u16      i16   refs");
        out.println("  " + "-".repeat(76));
        for (Map.Entry<Long, List<String>> e : byOff.entrySet()) {
            long a = e.getKey();
            int off = (int) (a - CAL_BASE);
            String vals = "   --      --       --";
            if (cal != null && off >= 0 && off + 1 < cal.length) {
                int u8 = cal[off] & 0xFF;
                int u16 = (cal[off] & 0xFF) | ((cal[off + 1] & 0xFF) << 8);
                short i16 = (short) u16;
                vals = String.format("%5d  %6d  %7d", u8, u16, i16);
            }
            out.printf("  0x%08X  0x%04X  %s   %d%n", a, off, vals, e.getValue().size());
            for (String s : e.getValue()) out.println("        " + s);
        }

        out.flush();
        out.close();
        println("DlcmA1CalRefs: wrote " + outPath + " (" + byOff.size() + " CAL addresses)");
    }
}
