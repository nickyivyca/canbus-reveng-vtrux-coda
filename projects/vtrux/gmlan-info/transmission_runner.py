#!/usr/bin/env python

"""
This example demonstrates how to use async IO with python-can.
"""

import asyncio
from typing import List

import can
from can.notifier import MessageRecipient

import time

# dongle 1: 'HW379841'
# dongle 1: 'HW630227'

locked = False
sixth = False


# gm_bus = can.Bus(interface='ixxat', channel=0, unique_hardware_id='HW379841', bitrate=500000, rx_fifo_size=512, tx_fifo_size=128)
# gm_bus = can.Bus(interface='nican', bitrate=500000, channel="CAN1")
# gm_bus = can.Bus(interface='usb2can', bitrate=500000, dll='C:\\Users\\<user>\\Downloads\\usb2can.dll', channel='6&29B22425&0&0000')
# hybrid_bus = can.Bus(interface='kvaser', channel=0, bitrate=500000)

gm_bus = can.Bus(interface='socketcan', bitrate=500000, channel='can0') # innomaker
hybrid_bus = can.Bus(interface='socketcan', bitrate=500000, channel='can1') # kvaser
# hybrid_bus = can.Bus(interface='kvaser', channel=0, bitrate=500000)

def receive_hybrid(message):
    global locked
    global sixth
    # pass
    # print("Received hybrid")
    if (message.arbitration_id == 0x1F5):
        if (message.data[0] == 0x06):
            sixth = True
            if (locked):
                message.data[0] = 0x66
            else:
                message.data[0] = 0x26
        else:
            sixth = False
        if (message.data[3] == 0x09):
            message.data[3] = 0x04
        if (message.data[5] == 0x02):
            message.data[5] = 0x00
        print(message)
    gm_bus.send(message)


def receive_gm(message):
    # pass
    # print("Received gm")
    # print(message)
    hybrid_bus.send(message)




def main():
    global locked
    global sixth

    lock_timer = 0

    # configs = can.detect_available_configs()
    # print(configs)
    # for config in configs:
    #     print(config)

    can.Notifier(hybrid_bus, [receive_hybrid])
    can.Notifier(gm_bus, [receive_gm])

    print("init success")

    # msg = can.Message(
    #     arbitration_id=0xC0FFEE,
    #     data=[0, 25, 0, 1, 3, 1, 4, 1],
    #     is_extended_id=True
    # )
    # trans_msg = can.Message(
    #     arbitration_id=0x1F5,
    #     data=[0, 25, 0, 1, 3, 1, 4, 1],
    #     is_extended_id=True
    # )
    # try:
    #     gm_bus.send(msg)
    #     print(f"Message sent on {gm_bus.channel_info}")
    # except can.CanError:
    #     print("Message NOT sent")
    # """The main function that runs in the loop."""

    # for i in range(0,50):
    #     gm_bus.send(msg)
    #     time.sleep(0.05)
        # msg = gm_bus.recv()
        # print(msg)

    while(True):        
        time.sleep(0.05)
        if (sixth):
            if not locked and lock_timer < 10:
                lock_timer += 1
            if lock_timer >= 10:
                if not locked:
                    print("locking")
                locked = True
        else:
            if (lock_timer or locked):
                print("unlocking")
            lock_timer = 0
            locked = 0

    gm_bus.shutdown()
    hybrid_bus.shutdown()

if __name__ == "__main__":
    main()