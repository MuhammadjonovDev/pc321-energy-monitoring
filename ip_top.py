import json
import re
import subprocess
import sys

import tinytuya

d = json.load(open("devices.json"))[0]
ranges = sys.argv[1:] or ["192.168.109.0/24", "192.168.108.0/24",
                          "192.168.110.0/24", "192.168.104.0/22"]
for r in ranges:
    print("Skanerlanmoqda:", r, flush=True)
    out = subprocess.run(["nmap", "-Pn", "-p", "6668", "--open", "-oG", "-", r],
                         capture_output=True, text=True).stdout
    for ip in re.findall(r"Host: (\S+) .*6668/open", out):
        dev = tinytuya.Device(d["id"], ip, d["key"])
        dev.set_version(3.5)
        resp = dev.status()
        if isinstance(resp, dict) and "dps" in resp:
            print("TOPILDI:", ip)
            sys.exit(0)
        print(" ", ip, "boshqa qurilma yoki xato:", resp.get("Error") if isinstance(resp, dict) else resp)
print("Topilmadi")
sys.exit(1)
