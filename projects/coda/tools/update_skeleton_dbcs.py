"""One-off script to update B CAN and D CAN skeleton DBCs with
newly discovered IDs from VICD disassembly (BMS_Recvd, DLCM_Recvd, misc_Recvd).
"""

B_CAN_PATH = "projects/coda/CODA-B-CAN-skeleton.dbc"
D_CAN_PATH = "projects/coda/CODA-D-CAN-skeleton.dbc"

# ─────────────────────────────────────────────────────────────
# B CAN: new placeholder messages from disassembly
# ─────────────────────────────────────────────────────────────

NEW_B_CAN_MESSAGES = """\

BO_ 80 BMS_Recvd_0x050: 7 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_3 : 24|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_4 : 32|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_5 : 40|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_6 : 48|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 528 misc_0x210: 1 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 533 misc_0x215: 2 Vector__XXX
 SG_ Packet_0 : 0|16@1+ (1,0) [0|0] "" Vector__XXX

BO_ 624 BMS_Recvd_0x270: 1 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 625 misc_0x271: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 629 BMS_Recvd_0x275: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_3 : 24|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_4 : 32|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_5 : 40|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 634 CMSTempStatus: 8 Vector__XXX
 SG_ CaseTemp : 0|8@1+ (1,0) [0|0] "degC" Vector__XXX
 SG_ PFCTemp : 8|8@1+ (1,0) [0|0] "degC" Vector__XXX
 SG_ HV1Temp : 16|8@1+ (1,0) [0|0] "degC" Vector__XXX
 SG_ HV2Temp : 24|8@1+ (1,0) [0|0] "degC" Vector__XXX

BO_ 635 CMSInputValues: 8 Vector__XXX
 SG_ ACInVoltage : 0|8@1+ (1,0) [0|0] "V" Vector__XXX
 SG_ ACInCurrent : 8|8@1+ (1,0) [0|0] "A" Vector__XXX
 SG_ ACInPower : 16|8@1+ (1,0) [0|0] "W" Vector__XXX

BO_ 636 CMSOutputValues: 8 Vector__XXX
 SG_ HVOutVoltage : 0|8@1+ (1,0) [0|0] "V" Vector__XXX
 SG_ HVOutCurrent : 8|8@1+ (1,0) [0|0] "A" Vector__XXX
 SG_ LVOutVoltage : 16|8@1+ (1,0) [0|0] "V" Vector__XXX
 SG_ LVOutCurrent : 24|8@1+ (1,0) [0|0] "A" Vector__XXX

BO_ 705 BMS_Recvd_0x2C1: 1 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 816 misc_0x330: 1 Vector__XXX
 SG_ Packet_0 : 0|8@1- (1,0) [0|0] "" Vector__XXX

BO_ 880 misc_0x370: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_3 : 24|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_4 : 32|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_7 : 56|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 888 BMS_Recvd_0x378: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 912 BMS_Recvd_0x390: 2 Vector__XXX
 SG_ Packet_0 : 0|16@1+ (1,0) [0|0] "" Vector__XXX

BO_ 1372 misc_0x55C: 3 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 1536 misc_0x600: 2 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 1568 BMS_Recvd_0x620: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1+ (1,0) [0|0] "" Vector__XXX

BO_ 1834 BMS_Recvd_0x72A: 1 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
"""

NEW_B_CAN_COMMENTS = """\
CM_ BO_ 80 "source: BMS_Recvd disasm (0x050); cluster unknown; 7 bytes, 4x 0.1 scale; id: vicd_disasm";
CM_ BO_ 528 "source: misc_Recvd disasm (0x210); candidate: Vehicle_Mode (0.4 scale, 1 byte); id: vicd_disasm";
CM_ BO_ 533 "source: misc_Recvd disasm (0x215); candidate: TCM.ParkLock? (16-bit word, 1/128 scale); id: vicd_disasm";
CM_ BO_ 624 "source: BMS_Recvd disasm (0x270); simple byte copy, status/mode signal; id: vicd_disasm";
CM_ BO_ 625 "source: misc_Recvd disasm (0x271); candidate: Death Counter partial (integer bytes); id: vicd_disasm";
CM_ BO_ 629 "source: BMS_Recvd disasm (0x275); 4x scale 2.0 + 2x scale 0.1, 6+ float signals; id: vicd_disasm";
CM_ BO_ 634 "source: CMS_Recvd.vi (interpreted, no disasm); signals inferred from CMM mirror (same Lear hardware); id: labview_cluster_name";
CM_ BO_ 635 "source: CMS_Recvd.vi (interpreted, no disasm); signals inferred from CMM mirror; id: labview_cluster_name";
CM_ BO_ 636 "source: CMS_Recvd.vi (interpreted, no disasm); signals inferred from CMM mirror; id: labview_cluster_name";
CM_ BO_ 705 "source: BMS_Recvd disasm (0x2C1); single byte copy, state 0x51; id: vicd_disasm";
CM_ BO_ 816 "source: misc_Recvd disasm (0x330); candidate: Long_Accel (0.08 m/s2/count, signed byte); id: vicd_disasm";
CM_ BO_ 880 "source: misc_Recvd disasm (0x370); candidate: Death Counter batch (6 bytes, 0.1 scale); bytes 0,1,2,3,4,7 used; id: vicd_disasm";
CM_ BO_ 888 "source: BMS_Recvd disasm (0x378); 3 sentinel values, cluster unknown; id: vicd_disasm";
CM_ BO_ 912 "source: BMS_Recvd disasm (0x390); single 16-bit scaled value, cluster unknown; id: vicd_disasm";
CM_ BO_ 1372 "source: misc_Recvd disasm (0x55C); candidate: VehFaults or status flags (3 bytes); id: vicd_disasm";
CM_ BO_ 1536 "source: misc_Recvd disasm (0x600); candidate: TPMS pressure (1.37 kPa/count); id: vicd_disasm";
CM_ BO_ 1568 "source: BMS_Recvd disasm (0x620); sparse decode, cluster unknown; id: vicd_disasm";
CM_ BO_ 1834 "source: BMS_Recvd disasm (0x72A); simple byte copy, cluster unknown; id: vicd_disasm";
"""

# (old_id, new_id, confidence note appended to existing CM_ BO_ comment)
B_CAN_REMAPS = [
    (8191, 897,  "BMS_Recvd 0x381, medium confidence: 5x init 1000.0 sentinel matches current limit cluster"),
    (8192, 899,  "BMS_Recvd 0x383, medium confidence: 8 boolean masks + 2x 0.1 scale matches BMSBattStatus"),
    (8195, 898,  "BMS_Recvd 0x382, tentative: 16-bit scaled values, ~5 bytes, could be BMSVminVmax"),
]

# ─────────────────────────────────────────────────────────────
# D CAN: new placeholder messages and ID remaps
# ─────────────────────────────────────────────────────────────

NEW_D_CAN_MESSAGES = """\

BO_ 577 DLCM_Recvd_0x241: 3 Vector__XXX
 SG_ Packet_0 : 0|8@1- (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1- (1,0) [0|0] "" Vector__XXX
 SG_ Packet_2 : 16|8@1- (1,0) [0|0] "" Vector__XXX

BO_ 632 DLCM_Recvd_0x278: 2 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1- (1,0) [0|0] "" Vector__XXX

BO_ 789 DLCM_Recvd_0x315: 8 Vector__XXX
 SG_ Packet_0 : 0|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_3 : 24|8@1+ (1,0) [0|0] "" Vector__XXX
 SG_ Packet_5 : 40|8@1+ (1,0) [0|0] "" Vector__XXX
"""

NEW_D_CAN_COMMENTS = """\
CM_ BO_ 577 "source: DLCM_Recvd disasm (0x241); candidate: TCM or EMS_3/FCM_1 (signed bytes); id: vicd_disasm";
CM_ BO_ 632 "source: DLCM_Recvd disasm (0x278); candidate: FCM_1 or EMS_3 (2 bytes, mask 0x40); id: vicd_disasm";
CM_ BO_ 789 "source: DLCM_Recvd disasm (0x315); candidate: AccurateFeedbacks or DLCM (0.1x3, mask 0x80); bytes 0,1,3,5; id: vicd_disasm";
"""

D_CAN_REMAPS = [
    (8191, 448,  "DLCM_Recvd 0x1C0, medium confidence: 8 bytes, 0.1x5 + 0.5x2 scale matches MCM motor signals"),
    (8195, 530,  "DLCM_Recvd 0x212, HIGH confidence: 0.25 deg/count scale, +-500 deg sentinel, 5-bit msg counter"),
    (8198, 1048, "DLCM_Recvd 0x418, medium confidence: single signed byte matches MCM temperature signal"),
]


def apply_updates(path, remaps, new_messages, new_comments):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    for old_id, new_id, note in remaps:
        # Update BO_ declaration
        text = text.replace(f'BO_ {old_id} ', f'BO_ {new_id} ')
        # Update CM_ SG_ lines
        text = text.replace(f'CM_ SG_ {old_id} ', f'CM_ SG_ {new_id} ')
        # Update CM_ BO_ line, appending confidence note
        old_prefix = f'CM_ BO_ {old_id} "'
        if old_prefix in text:
            idx = text.index(old_prefix)
            end = text.index('";\n', idx) + 3
            old_line = text[idx:end]
            inner = old_line[len(old_prefix):-3]  # content between quotes
            new_line = f'CM_ BO_ {new_id} "{inner}; vicd_disasm: {note}";\n'
            text = text[:idx] + new_line + text[end:]

    # Insert new messages just before the first CM_ line
    cm_start = text.find('\nCM_ ')
    if cm_start == -1:
        cm_start = len(text)
    text = text[:cm_start] + '\n' + new_messages + text[cm_start:]

    # Append new comments
    text = text.rstrip('\n') + '\n' + new_comments + '\n'

    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

    # Count messages
    msg_count = text.count('\nBO_ ')
    print(f"Updated {path}: {msg_count} messages total")


apply_updates(B_CAN_PATH, B_CAN_REMAPS, NEW_B_CAN_MESSAGES, NEW_B_CAN_COMMENTS)
apply_updates(D_CAN_PATH, D_CAN_REMAPS, NEW_D_CAN_MESSAGES, NEW_D_CAN_COMMENTS)
print("Done.")
