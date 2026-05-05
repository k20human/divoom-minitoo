#!/usr/bin/env python3
import socket
import sys
import time
import os
import struct
import json
import threading

# Minimal Divoom BT protocol sender for Linux.
# Replaces divoom-send.swift using AF_BLUETOOTH.

def log(s):
    print(s, file=sys.stderr)

def checksum(payload):
    cs = sum(payload) & 0xFFFF
    return bytes([cs & 0xFF, (cs >> 8) & 0xFF])

def escape_payload(payload):
    out = bytearray()
    for b in payload:
        if 1 <= b <= 3:
            out.append(0x03)
            out.append(b + 0x03)
        else:
            out.append(b)
    return bytes(out)

def frame(command, args):
    args = bytes(args)
    length = len(args) + 3
    payload = struct.pack("<H", length) + bytes([command]) + args
    cs = checksum(payload)
    body = payload + cs
    if os.environ.get("DIVOOM_ESCAPE") == "1":
        body = escape_payload(body)
    return bytes([0x01]) + body + bytes([0x02])

def frames_for_face(face_id):
    return [
        frame(0x45, [0x05]),
        frame(0xBD, [0x17, face_id]),
    ]

def frames_for_brightness(pct):
    op_hex = os.environ.get("DIVOOM_BRIGHT_OP", "32")
    op = int(op_hex, 16)
    return [frame(op, [pct])]

def frames_for_clock():
    return [frame(0x45, [0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00])]

def frames_for_raw(hex_string):
    bytes_list = [int(b, 16) for b in hex_string.split()]
    if not bytes_list: return []
    return [frame(bytes_list[0], bytes_list[1:])]

def frames_for_rawfile(path):
    if not os.path.exists(path):
        log(f"rawfile: cannot find {path}")
        return None
    frames = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            hex_part = line.split("#")[0].strip()
            built = frames_for_raw(hex_part)
            if not built:
                log(f"rawfile: bad hex line: {line}")
                return None
            frames.extend(built)
    return frames

def frames_for_json(json_str):
    return [frame(0x01, json_str.encode("utf-8"))]

def parse_command(tokens):
    if not tokens: return None
    verb = tokens[0]
    rest = tokens[1:]
    default_delay = int(os.environ.get("DIVOOM_FRAME_DELAY_MS", "150"))
    
    if verb == "face":
        if len(rest) != 1: return None
        return frames_for_face(int(rest[0])), default_delay
    elif verb == "brightness":
        if len(rest) != 1: return None
        return frames_for_brightness(int(rest[0])), default_delay
    elif verb == "clock":
        return frames_for_clock(), default_delay
    elif verb == "raw":
        if not rest: return None
        return frames_for_raw(" ".join(rest)), default_delay
    elif verb == "rawfile":
        if len(rest) < 1 or len(rest) > 2: return None
        frames = frames_for_rawfile(rest[0])
        if not frames: return None
        delay = int(rest[1]) if len(rest) == 2 else 40
        return frames, delay
    elif verb == "json":
        if not rest: return None
        return frames_for_json(" ".join(rest)), default_delay
    return None

class DivoomClient:
    def __init__(self, mac, port=1):
        self.mac = mac
        self.port = port
        self.sock = None

    def connect(self):
        log(f"Connecting to {self.mac} on port {self.port}...")
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        try:
            self.sock.connect((self.mac, self.port))
            log("Connected.")
        except Exception as e:
            log(f"Connection failed: {e}")
            self.sock = None
            raise

    def send_frames(self, frames, delay_ms=150):
        if not self.sock: return
        for i, f in enumerate(frames):
            log(f"tx[{i}]: {f.hex(' ')}")
            self.sock.send(f)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

def run_daemon(mac, port):
    fifo_path = os.environ.get("DIVOOM_FIFO", "/tmp/divoom.fifo")
    gap_ms = int(os.environ.get("DIVOOM_GAP_MS", "600"))
    
    if os.path.exists(fifo_path):
        os.unlink(fifo_path)
    os.mkfifo(fifo_path, 0o666)
    
    client = DivoomClient(mac, port)
    client.connect()
    
    log(f"daemon: listening on {fifo_path} (gap={gap_ms}ms)")
    
    last_sent = 0
    
    try:
        while True:
            with open(fifo_path, "r") as fifo:
                for line in fifo:
                    line = line.strip()
                    if not line: continue
                    if line in ["quit", "exit"]:
                        log("daemon: quit received")
                        return
                    
                    now = time.time()
                    elapsed = (now - last_sent) * 1000
                    if elapsed < gap_ms:
                        time.sleep((gap_ms - elapsed) / 1000.0)
                    
                    tokens = line.split()
                    parsed = parse_command(tokens)
                    if parsed:
                        frames, delay = parsed
                        client.send_frames(frames, delay)
                        last_sent = time.time()
                    else:
                        log(f"daemon: unknown command: {line}")
    finally:
        client.close()
        if os.path.exists(fifo_path):
            os.unlink(fifo_path)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: divoom-send-linux.py <MAC> <cmd> [args...]")
        sys.exit(1)
    
    mac = sys.argv[1]
    cmd = sys.argv[2]
    
    port = int(os.environ.get("DIVOOM_PORT", "1"))
    
    if cmd == "daemon":
        run_daemon(mac, port)
    elif cmd == "shell":
        client = DivoomClient(mac, port)
        client.connect()
        print("READY")
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line or line in ["quit", "exit"]: break
                parsed = parse_command(line.split())
                if parsed:
                    frames, delay = parsed
                    client.send_frames(frames, delay)
                else:
                    log(f"? unknown command: {line}")
        finally:
            client.close()
    else:
        client = DivoomClient(mac, port)
        client.connect()
        try:
            parsed = parse_command(sys.argv[2:])
            if parsed:
                frames, delay = parsed
                client.send_frames(frames, delay)
                hold_ms = int(os.environ.get("DIVOOM_HOLD_MS", "1500"))
                time.sleep(hold_ms / 1000.0)
            else:
                log("Unknown command")
        finally:
            client.close()
