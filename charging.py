#!/usr/bin/env python3
"""
Tapo P110 Smart Switch Scheduler
----------------------------------
Turns the switch ON and OFF at defined times every day.

Requirements:
    pip install tapo
    
Set environment variables:
    export TAPO_USERNAME="your@email.com"
    export TAPO_PASSWORD="yourpassword"
    export IP_ADDRESS="192.168.x.x"
"""

import asyncio
from datetime import datetime
from tapo import ApiClient

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

TAPO_USERNAME = "xxxxxxxxxxxx"       # Your Tapo app email
TAPO_PASSWORD = "xxxxxxxxxxxx"         # Your Tapo app password
IP_ADDRESS    = "xxxxxxxxxxxx"          # Your P110's local IP address

ON_TIME  = (15, 0)   # Turn ON  at 08:00
OFF_TIME = (21, 0)  # Turn OFF at 23:00

# ─────────────────────────────────────────────


def seconds_until(hour: int, minute: int) -> float:
    """Return seconds until the next occurrence of a given time today or tomorrow."""
    now    = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    diff   = (target - now).total_seconds()
    if diff <= 0:
        diff += 86400  # already passed today → wait until tomorrow
    return diff


async def main():
    tapo_username = TAPO_USERNAME
    tapo_password = TAPO_PASSWORD
    ip_address    = IP_ADDRESS

    if not all([tapo_username, tapo_password, ip_address]):
        print("[ERROR] Missing environment variables.")
        print("  export TAPO_USERNAME='your@email.com'")
        print("  export TAPO_PASSWORD='yourpassword'")
        print("  export IP_ADDRESS='192.168.x.x'")
        return

    client = ApiClient(tapo_username, tapo_password)
    device = await client.p110(ip_address)

    on_h,  on_m  = ON_TIME
    off_h, off_m = OFF_TIME

    print(f"[INFO] P110 Scheduler started")
    print(f"  ON  time : {on_h:02d}:{on_m:02d}")
    print(f"  OFF time : {off_h:02d}:{off_m:02d}")
    print(f"  Press Ctrl+C to quit.\n")

    while True:
        now     = datetime.now()
        now_min = now.hour * 60 + now.minute

        on_min  = on_h  * 60 + on_m
        off_min = off_h * 60 + off_m

        # Determine if we're currently inside the ON window
        if on_min < off_min:
            # e.g. ON=08:00, OFF=23:00 — simple daytime window
            should_be_on = on_min <= now_min < off_min
        else:
            # e.g. ON=22:00, OFF=06:00 — overnight window
            should_be_on = now_min >= on_min or now_min < off_min

        # Apply current state
        device_info = await device.get_device_info()
        is_on       = device_info.device_on

        if should_be_on and not is_on:
            print(f"[{now.strftime('%H:%M:%S')}] Turning ON...")
            await device.on()
        elif not should_be_on and is_on:
            print(f"[{now.strftime('%H:%M:%S')}] Turning OFF...")
            await device.off()
        else:
            state = "ON" if is_on else "OFF"
            print(f"[{now.strftime('%H:%M:%S')}] Device already {state} — no change needed.")

        # Sleep until the next scheduled event
        wait_on  = seconds_until(on_h,  on_m)
        wait_off = seconds_until(off_h, off_m)
        wait     = min(wait_on, wait_off)
        next_event = "ON" if wait_on < wait_off else "OFF"

        h, m = divmod(int(wait) // 60, 60)
        s    = int(wait) % 60
        print(f"[INFO] Next event: {next_event} in {h}h {m}m {s}s\n")

        await asyncio.sleep(wait)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[EXIT] Scheduler stopped.")