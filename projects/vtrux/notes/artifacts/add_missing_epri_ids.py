"""
Add the 9 Ghidra-decoded IDs that were missing from epri-pt-bus.dbc because they were
not in Via_CANid_List.plist (the generator script only produced stubs for plist IDs).

All 9 IDs are in ViaCANbusParser::parseEPRIMessage and have full byte-level decodings
confirmed from Ghidra ARMv7 decompile.

Run from project root: py -3.12 projects/vtrux/notes/artifacts/add_missing_epri_ids.py
"""

from pathlib import Path

DBC_PATH = Path("projects/vtrux/epri-pt-bus.dbc")
DBC_EXT_FLAG = 0x80000000

# ---------------------------------------------------------------------------
# New BO_ + SG_ blocks
# ---------------------------------------------------------------------------

NEW_BO_BLOCKS = """\

BO_ 83 EPRI_OperatingMode_0053: 1 Vector__XXX
 SG_ OperationState : 0|4@1+ (1,0) [0|8] "" Vector__XXX
 SG_ OperationMode : 4|3@1+ (1,0) [0|3] "" Vector__XXX

BO_ 776 EPRI_ParkRequest_0308: 1 Vector__XXX
 SG_ ParkRequest : 5|2@1+ (1,0) [0|3] "" Vector__XXX

BO_ 1024 EPRI_HV_BCM_Control_0400: 1 Vector__XXX
 SG_ hsc_bcm_enable : 0|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ hsc_bcm_epo : 1|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ hsc_bcm_mainc_close : 2|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ hsc_bcm_leakage_ena : 3|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 1372 EPRI_ParkLock_055C: 3 Vector__XXX
 SG_ parkLockState : 16|3@1+ (1,0) [0|6] "" Vector__XXX
 SG_ parkSensor : 22|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ driveSensor : 23|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 1408 EPRI_TCM_CANError_0580: 3 Vector__XXX
 SG_ tcm_CAN_ERR : 17|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 1583 EPRI_HCU_SwVersion_062F: 6 Vector__XXX
 SG_ HCU_SwIDType_Enum : 1|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ HCU_SwIDPrj_Enum : 2|6@1+ (1,0) [0|63] "" Vector__XXX
 SG_ MajorVersion : 8|7@1+ (1,0) [0|127] "" Vector__XXX
 SG_ MinorVersion : 16|8@1+ (1,0) [0|255] "" Vector__XXX

BO_ 1594 EPRI_VehicleConfig_063A: 8 Vector__XXX
 SG_ iVehCfg_chgr_md : 56|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ iVehCfg_ess_md : 57|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 1627 EPRI_HCU_DTC_065B: 8 Vector__XXX
 SG_ DTC_Code : 55|16@0+ (1,0) [0|65535] "" Vector__XXX

BO_ 2566902976 EPRI_INVCH_Bdc_Status_18FFD4C0: 8 Vector__XXX
 SG_ INVCH_Bdc_Page M : 0|8@1+ (1,0) [0|3] "" Vector__XXX
 SG_ INV_Bdc_bEVSEConnected m0 : 11|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bCharging m0 : 16|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bExporting m0 : 19|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bGridTied m0 : 20|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INVCH_Bdc_Signal_State m0 : 40|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ INVCH_Bdc_bBoost_St m1 : 40|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ INVCH_Bdc_Inverter_St m2 : 40|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ INV_Bdc_bACOk m3 : 8|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bACOV m3 : 9|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bACUV m3 : 10|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bBatteryUV m3 : 11|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bHVBatteryOV m3 : 12|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bHVBatteryUV m3 : 13|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bOTP m3 : 14|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bExportOverload m3 : 15|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bInverterFault m3 : 16|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ INV_Bdc_bBBFault m3 : 17|1@1+ (1,0) [0|1] "" Vector__XXX
"""

# ---------------------------------------------------------------------------
# CM_ blocks
# ---------------------------------------------------------------------------

NEW_CM_BLOCKS = """\
CM_ BO_ 83 "NOT in plist. CONFIRMED from Ghidra decompile of ViaCANbusParser::parseEPRIMessage. HCU operating mode and state machine. DLC=1: only B0 accessed. Added 2026-03-29.";

CM_ SG_ 83 OperationMode "CONFIRMED. B0[6:4] = (B0 >> 4) & 0x7. 3-bit index: 0=NTRL, others are error strings (app defect -- only 0 is a real mode).";
CM_ SG_ 83 OperationState "CONFIRMED. B0[3:0] = B0 & 0xF. 4-bit index, valid 0-8. 9-entry state machine.";

CM_ BO_ 776 "NOT in plist. CONFIRMED from Ghidra decompile. HCU park request command. DLC=1: only B0 accessed. Added 2026-03-29.";

CM_ SG_ 776 ParkRequest "CONFIRMED. B0[6:5] = (B0 >> 5) & 3. 2-bit index: 0=OFF, 1=Park, 2=UnPark. Index 3 is a fallback error string not expected in practice.";

CM_ BO_ 1024 "NOT in plist. CONFIRMED from Ghidra decompile. HV BCM control word (hsc_ prefix = HCU-to-BMS command signals). DLC=1: only B0[3:0] accessed. Added 2026-03-29.";

CM_ SG_ 1024 hsc_bcm_enable "CONFIRMED. B0 bit 0.";
CM_ SG_ 1024 hsc_bcm_epo "CONFIRMED. B0 bit 1. Emergency power off command.";
CM_ SG_ 1024 hsc_bcm_mainc_close "CONFIRMED. B0 bit 2. Main contactor close command.";
CM_ SG_ 1024 hsc_bcm_leakage_ena "CONFIRMED. B0 bit 3. Leakage detection enable.";

CM_ BO_ 1372 "NOT in plist. CONFIRMED from Ghidra decompile. Transmission park lock state and sensor feedback. DLC=3: only B2 accessed; B0-B1 not read. Added 2026-03-29.";

CM_ SG_ 1372 parkLockState "CONFIRMED. B2[2:0] = (int)(char)B2 & 7. 3-bit index, 7-entry state machine. Index 7 bleeds into format string cfstring and should never occur.";
CM_ SG_ 1372 parkSensor "CONFIRMED. B2 bit 6. OFF/ON.";
CM_ SG_ 1372 driveSensor "CONFIRMED. B2 bit 7 (sign bit of int8 cast). OFF/ON.";

CM_ BO_ 1408 "NOT in plist. CONFIRMED from Ghidra decompile. TCM CAN error flag. DLC=3: only B2 bit 1 accessed. Added 2026-03-29.";

CM_ SG_ 1408 tcm_CAN_ERR "CONFIRMED. B2 bit 1. YES/NO (1=error present).";

CM_ BO_ 1583 "NOT in plist. CONFIRMED from Ghidra decompile. HCU software version fields, tightly bit-packed across B0-B5. DLC=6. SG_ entries cover cleanly-extractable fields only. Three fields require cross-byte bit manipulation and are documented here only: HCU_SwIDMaturity_Enum = (B0[0]<<1)|(B1>>7) 2-bit; HCU_SwIDVehVariant_Enum = (B3<<2)|(B4>>6) 10-bit; HCU_SwIDCalVer_Cnt = (B4[5:0]<<2)|(B5>>6) 8-bit. Added 2026-03-29.";

CM_ SG_ 1583 HCU_SwIDPrj_Enum "CONFIRMED. B0[7:2] = B0 >> 2. 6-bit project enum.";
CM_ SG_ 1583 HCU_SwIDType_Enum "CONFIRMED. B0 bit 1. 1-bit type flag.";
CM_ SG_ 1583 MajorVersion "CONFIRMED. B1[6:0] = B1 & 0x7F. 7-bit.";
CM_ SG_ 1583 MinorVersion "CONFIRMED. B2 full byte. 8-bit.";

CM_ BO_ 1594 "NOT in plist. CONFIRMED from Ghidra decompile. Vehicle configuration flags -- charger type and ESS (battery pack) type. DLC=8: only B7 bits 0-1 accessed. Added 2026-03-29.";

CM_ SG_ 1594 iVehCfg_chgr_md "CONFIRMED. B7 bit 0. 0=POWERONE, 1=DRS.";
CM_ SG_ 1594 iVehCfg_ess_md "CONFIRMED. B7 bit 1. 0=A123, 1=VALENCE.";

CM_ BO_ 1627 "NOT in plist. CONFIRMED from Ghidra decompile. HCU DTC (diagnostic trouble code) dispatcher. Passive receive only -- EPRI app never requests DTCs; 0x065B never observed in any log in the corpus (62 drive/charge/fault logs). Almost certainly a scan-tool-requested stored DTC readout. DLC=8: B6:B7 = 16-bit DTC code (big-endian), B0-B5 not read. Added 2026-03-29.";

CM_ SG_ 1627 DTC_Code "CONFIRMED. (B6<<8)|B7 = 16-bit SAE J2012 DTC code (big-endian). 29-entry lookup table in Ghidra decompile maps to HCU/BMS/charger/CAN fault codes. See VAL_ for full table.";

CM_ BO_ 2566902976 "NOT in plist. CONFIRMED from Ghidra decompile. Bel Power Solutions INVCH_Bdc multi-page status message. J1939 extended 29-bit ID 0x18FFD4C0. B0 = page selector (mux); pages 0-3 dispatch to different signal sets in B1/B2/B5. Cross-validated against BelInverter.dbc (byte/bit positions match; EPRI app missing 3 fault flags on page 3 that Bel DBC has). Added 2026-03-29.";

CM_ SG_ 2566902976 INVCH_Bdc_Page "CONFIRMED. B0 = page selector (0-3). Mux signal.";
CM_ SG_ 2566902976 INVCH_Bdc_Signal_State "CONFIRMED. Page 0. B5 raw byte, 29-entry state dictionary. See VAL_.";
CM_ SG_ 2566902976 INVCH_Bdc_bBoost_St "CONFIRMED. Page 1. B5 raw byte, 21-entry buck-boost state dictionary. See VAL_.";
CM_ SG_ 2566902976 INVCH_Bdc_Inverter_St "CONFIRMED. Page 2. B5 raw byte, 35-entry inverter state dictionary. See VAL_.";
CM_ SG_ 2566902976 INV_Bdc_bEVSEConnected "CONFIRMED. Page 0. B1 bit 3 (B1 & 0x08).";
CM_ SG_ 2566902976 INV_Bdc_bCharging "CONFIRMED. Page 0. B2 bit 0 (B2 & 0x01).";
CM_ SG_ 2566902976 INV_Bdc_bExporting "CONFIRMED. Page 0. B2 bit 3 (B2 & 0x08).";
CM_ SG_ 2566902976 INV_Bdc_bGridTied "CONFIRMED. Page 0. B2 bit 4 (B2 & 0x10).";
CM_ SG_ 2566902976 INV_Bdc_bACOk "CONFIRMED. Page 3. B1 bit 0. Also in BelInverter.dbc as BELINV_acOk.";
CM_ SG_ 2566902976 INV_Bdc_bACOV "CONFIRMED. Page 3. B1 bit 1. AC over-voltage.";
CM_ SG_ 2566902976 INV_Bdc_bACUV "CONFIRMED. Page 3. B1 bit 2. AC under-voltage.";
CM_ SG_ 2566902976 INV_Bdc_bBatteryUV "CONFIRMED. Page 3. B1 bit 3. 12V battery under-voltage.";
CM_ SG_ 2566902976 INV_Bdc_bHVBatteryOV "CONFIRMED. Page 3. B1 bit 4. HV battery over-voltage.";
CM_ SG_ 2566902976 INV_Bdc_bHVBatteryUV "CONFIRMED. Page 3. B1 bit 5. HV battery under-voltage.";
CM_ SG_ 2566902976 INV_Bdc_bOTP "CONFIRMED. Page 3. B1 bit 6. Over-temperature protection.";
CM_ SG_ 2566902976 INV_Bdc_bExportOverload "CONFIRMED. Page 3. B1 bit 7. Export overload.";
CM_ SG_ 2566902976 INV_Bdc_bInverterFault "CONFIRMED. Page 3. B2 bit 0.";
CM_ SG_ 2566902976 INV_Bdc_bBBFault "CONFIRMED. Page 3. B2 bit 1. Buck-boost fault.";
"""

# ---------------------------------------------------------------------------
# VAL_ blocks
# ---------------------------------------------------------------------------

NEW_VAL_BLOCKS = """\
VAL_ 83 OperationMode 0 "NTRL" 1 "Invalid_1" 2 "Invalid_2" ;
VAL_ 83 OperationState 0 "INIT" 1 "STBY" 2 "ACTIVATION" 3 "DEACTIVATION" 4 "OPERATIONAL" 5 "FAILURE" 6 "SHTDWN" 7 "WAIT4COOLING" 8 "PWR_OFF_RDY" ;

VAL_ 776 ParkRequest 0 "OFF" 1 "Park" 2 "UnPark" ;

VAL_ 1372 parkLockState 0 "OFF" 1 "Park" 2 "Parked" 3 "ParkStalled" 4 "Unparking" 5 "Unparked" 6 "UnparkStalled" ;

VAL_ 1594 iVehCfg_chgr_md 0 "POWERONE" 1 "DRS" ;
VAL_ 1594 iVehCfg_ess_md 0 "A123" 1 "VALENCE" ;

VAL_ 1627 DTC_Code 3431 "aChgr_p0d67ChgrPfrm_dtc" 6688 "sEss_p1a20BecmAFlt" 2683 "sEss_p0a7bBecmMilOnReq" 6689 "sEss_p1a21BecmACritFlt" 6785 "sEss_p1a81HvilPrfmGene" 6786 "sEss_p1a82HvilPrfmTrac" 6784 "sEss_p1a80HvilPrfmDcdc" 2726 "sEss_p0aa6HvIso" 6816 "sChgr_p1aa0ChgrShtdwn" 2571 "cEss_p0a0bHvilPrfm" 2591 "cEss_p0a1fEss" 54016 "diagHcu_u1300AppIntrptTsk" 54017 "diagHcu_u1301LowMemTsk2" 54018 "diagHcu_u1302LowMemTsk1" 54019 "diagHcu_u1303LowMemIdleTsk" 54020 "diagHcu_u1304LowMemIntrpt" 54021 "diagHcu_u1305LowMemKernel" 54022 "diagHcu_u1306ShtdwnTsk" 54023 "diagHcu_u1307LowMemHeap" 54033 "diagHcu_u1311HighCpuTsk2" 54032 "diagHcu_u1310HighCpuAppIntrptTsk" 54034 "diagHcu_u1312HighCpuTsk1" 54035 "diagHcu_u1313HighCpuShtdwnTsk" 54036 "diagHcu_u1314CpuIdleApp" 49449 "inAbstrCanEbcm_u0129LostRx" 49408 "inAbstrCanEcm_u0100LostRx" 49515 "inAbstrCanAccm_u016BLostRx" 49425 "inAbstrCanBecm_u0111LostRx" 49814 "inAbstrCanBdc_u0296LostRx" ;

VAL_ 2566902976 INVCH_Bdc_Signal_State 0 "INIT" 1 "WAKE_UP" 2 "VEH_CHARGE" 3 "OTP" 4 "SLEEP" 5 "DELAYED_SLEEP" 6 "TEST" 7 "EXPORT" 8 "STANDBY" 9 "DEBUG" 10 "NOT_CONN_A" 11 "CONN_B" 12 "ACCEPT_ENERGY_CD" 13 "ENERGY_DISC_E" 14 "ERR" 15 "SHUTDOWN_CHARGER" 20 "CHRGR_SHTDOWN_1" 21 "CHRGR_SHTDOWN_2" 22 "CHRGR_SHTDOWN_3" 23 "CHRGR_SHTDOWN_4" 30 "EXP_INIT" 31 "EXP_DISABLED" 32 "EXP_ENERGY" 33 "EXP_SHTDOWN" 34 "EXP_ALCI" 40 "EXP_SHTDWN_1" 41 "EXP_SHTDWN_2" 42 "EXP_SHTDWN_3" 43 "EXP_SHTDWN_4" ;

VAL_ 2566902976 INVCH_Bdc_bBoost_St 0 "FIRST_START" 1 "IDDLE" 2 "UV_OV" 3 "STARTUP" 4 "RUNNING" 5 "LATCHED_FAULT1" 6 "BUS_ERROR" 7 "OTP" 8 "DEBUG" 9 "INIT" 10 "OVERLOAD" 11 "DRIVER_FAULT" 12 "SHORTCIRCUIT" 13 "DCDC_SOFTSTART" 14 "BB_SOFTSTART" 15 "SOFTSTART" 16 "JUMP_BOOTLOADER" 17 "GOTO_SLEEP" 18 "BB_DEBUG" 19 "DC_DEBUG" 20 "WATCHDOG" ;

VAL_ 2566902976 INVCH_Bdc_Inverter_St 0 "FIRST_START" 1 "IDDLE" 2 "INV_UV_OV" 3 "INV_STARTUP" 4 "INV_RUNNING" 5 "LATCHED_FAULT" 6 "BUS_ERROR" 7 "OTP" 8 "INV_DEBUG" 9 "INIT" 10 "DRIVER_FAULT" 11 "OVERLOAD" 12 "SHORTCIRCUIT" 13 "INV_SOFTSTART" 14 "BB_SOFTSTART" 15 "SOFTSTART" 16 "JUMP_BOOTLOADER" 17 "GOTO_SLEEP" 18 "PFC_DC_UV_OV" 19 "INV_DRIVER_SOFTSTART" 20 "ALCI_ACTIVE" 21 "INV_RELAY_START" 22 "PFC_DEBUG" 23 "PFC_DRIVER_SOFTSTART" 24 "PFC_SOFTSTART" 25 "PFC_RELAY_START" 26 "PFC_RUNNING" 27 "DC_DEBUG" 28 "INV_DC_DEBUG" 29 "PFC_AC_UV_OV" 30 "WATCHDOG" 31 "INV_DC_DEBUG_NO_PROT" 32 "INV_ENABLE_N" 33 "PFC_ENABLE_N" 34 "INV_HICCUP" ;
"""


def main():
    content = DBC_PATH.read_text(encoding="ascii", errors="replace")

    # Find the insertion point for BO_ blocks: right before the first CM_ line
    cm_pos = content.find("\nCM_ BO_")
    if cm_pos == -1:
        raise ValueError("Could not find CM_ BO_ insertion point")

    # Find the insertion point for CM_ blocks: right before the first VAL_ line
    val_pos = content.find("\nVAL_")
    if val_pos == -1:
        raise ValueError("Could not find VAL_ insertion point")

    # Build new content: insert BO_ before first CM_, insert CM_ before first VAL_
    # We do this from back-to-front to avoid offset shifts
    new_content = (
        content[:cm_pos]
        + NEW_BO_BLOCKS
        + content[cm_pos:val_pos]
        + NEW_CM_BLOCKS
        + content[val_pos:]
        + NEW_VAL_BLOCKS
    )

    DBC_PATH.write_text(new_content, encoding="ascii", errors="replace")
    print(f"Updated {DBC_PATH}")

    # Verify with cantools
    try:
        import cantools
        db = cantools.db.load_file(str(DBC_PATH), strict=False)
        print(f"cantools: loaded {len(db.messages)} messages OK")
        new_ids = [0x53, 0x308, 0x400, 0x55C, 0x580, 0x62F, 0x63A, 0x65B, 0x18FFD4C0]
        for arb_id in new_ids:
            try:
                msg = db.get_message_by_frame_id(arb_id)
                print(f"  0x{arb_id:04X}  {msg.name}  ({len(msg.signals)} signals)")
            except Exception as e:
                print(f"  0x{arb_id:04X}  ERROR: {e}")
    except ImportError:
        print("cantools not available for validation")


if __name__ == "__main__":
    main()
