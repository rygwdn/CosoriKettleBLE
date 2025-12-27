#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "bleak",
# ]
# ///

import asyncio
from bleak import BleakScanner
from bleak.args.corebluetooth import CBScannerArgs

async def main():
    devices = await BleakScanner.discover(cb=CBScannerArgs(use_bdaddr=True))
    for d in devices:
        if d.name and ("cosori" in d.name.lower() or "kettle" in d.name.lower()):
            print(f"Found: {d.name} - {d.address}")

asyncio.run(main())
