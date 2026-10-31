"""The DLCM torque task, one module per firmware function (plan R1).

Each block's `run()` is one call of the firmware function named in its class
docstring. Blocks read and write `ram` by symbol name; constants come from the
image by symbol name. `controller.py` calls them in DlcmTorqueTask10ms order.
"""
