# DecompileViaParsers.py
# Ghidra headless script -- decompile Via Motors signal parser methods
# from CANbusLogger2 iOS app binary.
#
# Targets:
#   - All functions whose names mention ViaCANbusParser, ViaOBDParser,
#     EPRIViaBus, EPRIViaOBDIIBus
#   - All functions that reference our known EPRI format strings
#     (e.g. "GENE_RotSpd = %d rpm")
#
# Output: artifacts/ghidra-via-decompiled.txt
#
# Run via analyzeHeadless with -postScript DecompileViaParsers.py
#@author Claude Code
#@category Analysis

import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.listing import Function

OUTPUT_PATH = os.path.join(
    "<repo> Libraries\\Projects\\reverse-it",
    "projects\\vtrux\\notes\\artifacts\\ghidra-via-decompiled.txt"
)

# ObjC class names whose methods we want to decompile
TARGET_CLASS_SUBSTRINGS = [
    "ViaCANbusParser",
    "ViaOBDParser",
    "EPRIViaBus",
    "EPRIViaOBDIIBus",
    "ViaVehicle",
    "ViaOperatingMode",
]

# Known format strings that appear right after signal decoding.
# Any function referencing one of these is a decoding function.
TARGET_FORMAT_STRINGS = [
    "GENE_RotSpd",
    "TRAC_RotSpd",
    "GENE_Mot_Trq",
    "TRAC_Mot_Trq",
    "GENE_HighPwr_Curr",
    "TRAC_HighPwr_Curr",
    "BCM_Status:",
    "BCM_Limits:",
    "BCM_Data1:",
    "BCM_Data2:",
    "DCDC high voltage",
    "GENE_DrvCoolFlowReq",
    "TRAC_DrvCoolFlowReq",
    "INVCH_Bdc_Ibat",
    "INVCH_Inv_Iout1",
    "Veh_BrakePdl_Pos",
]


def get_functions_by_name(prog):
    """Return functions whose name contains a target class substring."""
    hits = []
    fm = prog.getFunctionManager()
    for func in fm.getFunctions(True):
        name = func.getName()
        if any(cls in name for cls in TARGET_CLASS_SUBSTRINGS):
            hits.append(func)
    return hits


def get_functions_referencing_strings(prog):
    """Return functions that contain references to our target format strings."""
    memory = prog.getMemory()
    listing = prog.getListing()
    refMgr = prog.getReferenceManager()
    fm = prog.getFunctionManager()

    # Build set of addresses of target strings in memory
    target_addrs = set()
    for block in memory.getBlocks():
        if not block.isInitialized():
            continue
        block_name = block.getName()
        # String data lives in __cstring, __objc_methnames, etc.
        if "__cstring" not in block_name and "cstring" not in block_name.lower():
            continue
        try:
            data = bytearray(block.getSize())
            block.getBytes(block.getStart(), data, 0, block.getSize())
            offset = 0
            while offset < len(data):
                for target in TARGET_FORMAT_STRINGS:
                    tb = target.encode("ascii")
                    if data[offset:offset+len(tb)] == list(tb) or bytes(data[offset:offset+len(tb)]) == tb:
                        target_addrs.add(block.getStart().add(offset))
                        break
                offset += 1
        except Exception as e:
            print("Block scan error: " + str(e))

    print("Found {} target string addresses".format(len(target_addrs)))

    # Find functions that reference those addresses
    func_set = {}
    for addr in target_addrs:
        refs = refMgr.getReferencesTo(addr)
        for ref in refs:
            from_addr = ref.getFromAddress()
            func = fm.getFunctionContaining(from_addr)
            if func is not None:
                func_set[func.getEntryPoint()] = func

    return list(func_set.values())


def decompile_functions(prog, funcs, monitor):
    """Decompile a list of functions and return formatted strings."""
    decomp = DecompInterface()
    decomp.openProgram(prog)

    results = []
    seen = set()

    for func in funcs:
        ep = func.getEntryPoint()
        if ep in seen:
            continue
        seen.add(ep)

        name = func.getName()
        print("Decompiling: " + name + " @ " + str(ep))
        try:
            res = decomp.decompileFunction(func, 120, monitor)
            if res.decompileCompleted():
                c_code = res.getDecompiledFunction().getC()
                results.append("=" * 70)
                results.append("// " + name)
                results.append("// Address: " + str(ep))
                results.append("=" * 70)
                results.append(c_code)
                results.append("")
            else:
                results.append("// DECOMPILE FAILED: " + name + " -- " + str(res.getErrorMessage()))
                results.append("")
        except Exception as e:
            results.append("// EXCEPTION decompiling " + name + ": " + str(e))
            results.append("")

    decomp.dispose()
    return results


def run():
    prog = currentProgram
    monitor = ConsoleTaskMonitor()

    print("Program: " + prog.getName())
    print("Language: " + str(prog.getLanguage().getLanguageID()))

    print("Finding functions by class name...")
    name_funcs = get_functions_by_name(prog)
    print("  Found {} functions by class name".format(len(name_funcs)))

    print("Finding functions by format string references...")
    str_funcs = get_functions_referencing_strings(prog)
    print("  Found {} functions by string reference".format(len(str_funcs)))

    all_funcs = {f.getEntryPoint(): f for f in name_funcs + str_funcs}
    print("Total unique functions to decompile: {}".format(len(all_funcs)))

    lines = ["// Ghidra decompilation of Via Motors signal parsers from CANbusLogger2",
             "// Binary: CANbusLogger2 (EPRI Logger iOS app)",
             "// Target classes: " + ", ".join(TARGET_CLASS_SUBSTRINGS),
             "// Generated by DecompileViaParsers.py",
             ""]

    lines += decompile_functions(prog, list(all_funcs.values()), monitor)

    with open(OUTPUT_PATH, "w") as f:
        f.write("\n".join(lines))

    print("Written {} lines to {}".format(len(lines), OUTPUT_PATH))


run()
