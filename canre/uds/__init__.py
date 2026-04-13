"""canre.uds -- UDS/KWP2000 diagnostic scanner package.

Public API:
    ISOTPChannel   -- synchronous ISO 15765-2 transport layer wrapper
    UDSClient      -- UDS + KWP2000 service layer
    UDSScanner     -- address scanner + full interrogation pipeline
    ScanResult, ModuleInfo, DIDResult, DTCSubfunctionResult,
    KWPDTCResult, ServiceProbeResult  -- result data classes
    UDSNegativeResponse, UDSTimeout, ISOTPError  -- exceptions
"""

from canre.uds.isotp import ISOTPChannel
from canre.uds.client import (
    UDSClient,
    UDSNegativeResponse,
    UDSTimeout,
    ISOTPError,
)
from canre.uds.scanner import (
    UDSScanner,
    ScanResult,
    ModuleInfo,
    DIDResult,
    DTCSubfunctionResult,
    KWPDTCResult,
    ServiceProbeResult,
)

__all__ = [
    "ISOTPChannel",
    "UDSClient",
    "UDSNegativeResponse",
    "UDSTimeout",
    "ISOTPError",
    "UDSScanner",
    "ScanResult",
    "ModuleInfo",
    "DIDResult",
    "DTCSubfunctionResult",
    "KWPDTCResult",
    "ServiceProbeResult",
]
