"""UDS / ISO-14229 constants and small helpers shared by the flash simulators.

Only the services and NRCs that appear in (or are relevant to) the Coda DLCM
reflash are enumerated. Directionality note: in the real flash6.log capture the
tester (Omitec) speaks on 0x7E0 and the ECU (Gateway/DLCM) answers on 0x7E8;
request SIDs appear only on 0x7E0 and response SIDs only on 0x7E8 (proven by
ISO-TP flow-control reciprocity), so these two roles are unambiguous.
"""

DEFAULT_REQUEST_ID = 0x7E0   # tester -> ECU  (Omitec)
DEFAULT_RESPONSE_ID = 0x7E8  # ECU -> tester  (Gateway/DLCM)

POSITIVE_RESPONSE_OFFSET = 0x40
NEGATIVE_RESPONSE_SID = 0x7F

# --- request service IDs ---
SVC_DIAGNOSTIC_SESSION_CONTROL = 0x10
SVC_ECU_RESET = 0x11
SVC_READ_DATA_BY_ID = 0x22
SVC_SECURITY_ACCESS = 0x27
SVC_COMMUNICATION_CONTROL = 0x28
SVC_WRITE_DATA_BY_ID = 0x2E
SVC_ROUTINE_CONTROL = 0x31
SVC_REQUEST_DOWNLOAD = 0x34
SVC_TRANSFER_DATA = 0x36
SVC_REQUEST_TRANSFER_EXIT = 0x37
SVC_TESTER_PRESENT = 0x3E
SVC_CONTROL_DTC_SETTING = 0x85

SERVICE_NAMES = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x22: "ReadDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
}

# --- negative response codes ---
NRC_GENERAL_REJECT = 0x10
NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUBFUNCTION_NOT_SUPPORTED = 0x12
NRC_INCORRECT_LENGTH = 0x13
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
NRC_TRANSFER_DATA_SUSPENDED = 0x71
NRC_GENERAL_PROGRAMMING_FAILURE = 0x72
NRC_WRONG_BLOCK_SEQUENCE_COUNTER = 0x73
NRC_RESPONSE_PENDING = 0x78
NRC_VOLTAGE_TOO_HIGH = 0x92
NRC_VOLTAGE_TOO_LOW = 0x93

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceived-ResponsePending",
    0x92: "voltageTooHigh",
    0x93: "voltageTooLow",
}


def svc_name(sid):
    return SERVICE_NAMES.get(sid, "0x%02X" % sid)


def nrc_name(nrc):
    return NRC_NAMES.get(nrc, "0x%02X" % nrc)


def is_negative(payload):
    return len(payload) >= 1 and payload[0] == NEGATIVE_RESPONSE_SID


def is_response_pending(payload):
    """True for a 0x7F <sid> 0x78 responsePending negative response."""
    return (len(payload) >= 3
            and payload[0] == NEGATIVE_RESPONSE_SID
            and payload[2] == NRC_RESPONSE_PENDING)


def positive_response(request_sid):
    return (request_sid + POSITIVE_RESPONSE_OFFSET) & 0xFF


def negative_response(request_sid, nrc):
    return bytes([NEGATIVE_RESPONSE_SID, request_sid & 0xFF, nrc & 0xFF])


def describe(payload):
    """Human-readable one-liner for a UDS payload (request or response)."""
    if not payload:
        return "<empty>"
    sid = payload[0]
    if sid == NEGATIVE_RESPONSE_SID and len(payload) >= 3:
        return "NEG svc=%s nrc=%s" % (svc_name(payload[1]), nrc_name(payload[2]))
    if sid >= 0x40 and (sid - 0x40) in SERVICE_NAMES:
        return "+%s %s" % (svc_name(sid - 0x40), payload[1:].hex())
    return "%s %s" % (svc_name(sid), payload[1:].hex())
