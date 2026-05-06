#!/usr/bin/env python3
import socket
import sys
import time
import os
import struct
import json
import threading
import queue

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

def framed_packets(buffer):
    """Drain complete `01 ... 02` framed packets from a bytearray. Mutates buffer."""
    packets = []
    i = 0
    n = len(buffer)
    while i + 3 < n:
        if buffer[i] != 0x01:
            i += 1
            continue
        length = buffer[i + 1] | (buffer[i + 2] << 8)
        total = length + 4
        if length < 3:
            i += 1
            continue
        if i + total > n:
            break
        if buffer[i + total - 1] != 0x02:
            i += 1
            continue
        packets.append(bytes(buffer[i:i + total]))
        i += total
    if i > 0:
        del buffer[:i]
    return packets


class AutoCustomResponder:
    """Auto-reply to MiniToo custom upload handshake (mirrors divoom-send.swift)."""

    def __init__(self, files_by_id, default_file_id, device_id, file_delay_ms):
        self.files_by_id = files_by_id  # {file_id: (start_frame, chunk_frames)}
        self.default_file_id = default_file_id
        self.device_id = device_id
        self.file_delay_ms = file_delay_ms
        self.client = None
        self.lock = threading.Lock()
        self.sending_chunks = False
        self.active_file_id = None

    def handle_packet(self, packet):
        if len(packet) < 8 or packet[3] != 0x04:
            return
        if packet[4] == 0xbd and packet[5] == 0x55 and packet[6] == 0x30:
            self._handle_bd30(packet)
        elif packet[4] == 0xbe and packet[5] == 0x55:
            self._handle_be(packet)
        elif packet[4] == 0x01 and packet[5] == 0x55:
            self._handle_json(packet)

    def _handle_bd30(self, packet):
        requested_len = packet[7]
        if len(packet) < 8 + requested_len + 3:
            return
        try:
            requested_id = packet[8:8 + requested_len].decode("utf-8")
        except UnicodeDecodeError:
            return
        if requested_id not in self.files_by_id:
            log(f"autocustom: ignoring BD30 for unexpected fileId={requested_id}")
            return
        with self.lock:
            if self.sending_chunks:
                log("autocustom: ignoring start request while chunks in flight")
                return
            self.active_file_id = requested_id
            start_frame = self.files_by_id[requested_id][0]
        log(f"autocustom: sending start for {requested_id} reason=BD30")
        self.client.send_frames([start_frame], 0)

    def _handle_be(self, packet):
        status = packet[6]
        if status == 0:
            self._send_chunks("BE00")
        elif status == 1 and len(packet) >= 10:
            idx = packet[7] | (packet[8] << 8)
            self._resend_chunk(idx)
        else:
            log(f"autocustom: unhandled BE status={status}")

    def _send_chunks(self, reason):
        with self.lock:
            if self.sending_chunks:
                log("autocustom: chunks already in flight")
                return
            file_id = self.active_file_id
            if not file_id or file_id not in self.files_by_id:
                log("autocustom: BE00 without active file")
                return
            self.sending_chunks = True
            chunks = self.files_by_id[file_id][1]
        try:
            log(f"autocustom: sending {len(chunks)} chunks for {file_id} reason={reason}")
            self.client.send_frames(chunks, self.file_delay_ms)
        finally:
            with self.lock:
                self.sending_chunks = False

    def _resend_chunk(self, index):
        with self.lock:
            file_id = self.active_file_id
            if not file_id or file_id not in self.files_by_id:
                log("autocustom: resend without active file")
                return
            chunks = self.files_by_id[file_id][1]
        if index < 0 or index >= len(chunks):
            log(f"autocustom: chunk resend out of range index={index}")
            return
        log(f"autocustom: resending chunk {index} for {file_id}")
        self.client.send_frames([chunks[index]], 0)

    def _handle_json(self, packet):
        end = len(packet) - 3
        if end <= 6:
            return
        try:
            obj = json.loads(packet[6:end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        command = obj.get("Command")
        if command == "Channel/GetOneCustom":
            custom_id = int(obj.get("CustomId") or 0)
            page_index = int(obj.get("CustomPageIndex") or 0)
            log(f"autocustom: reply Channel/GetOneCustom page={page_index} custom={custom_id}")
            self._send_json_reply({
                "Command": "Channel/GetOneCustom",
                "ReturnCode": 0,
                "ReturnMessage": "",
                "DeviceId": self.device_id,
                "CustomPageIndex": page_index,
                "CustomId": custom_id,
                "FileId": self._json_file_id(obj),
            })
        elif command == "Device/GetFileVersion":
            file_type = int(obj.get("FileType") or 1)
            log(f"autocustom: reply Device/GetFileVersion type={file_type}")
            self._send_json_reply({
                "Command": "Device/GetFileVersion",
                "ReturnCode": 0,
                "ReturnMessage": "",
                "DeviceId": self.device_id,
                "FileType": file_type,
                "FileId": self._json_file_id(obj),
                "Version": 1,
            })

    def _json_file_id(self, obj):
        file_id = obj.get("FileId")
        if isinstance(file_id, str) and file_id in self.files_by_id:
            return file_id
        return self.default_file_id

    def _send_json_reply(self, obj):
        s = json.dumps(obj, separators=(",", ":"))
        self.client.send_frames(frames_for_json(s), 0)


def load_custom_files(entries):
    """entries: list of (file_id, raw_path).
    Returns ({file_id: (start_frame, chunk_frames)}, default_file_id) or None."""
    files = {}
    default_id = None
    for file_id, raw_path in entries:
        if not file_id:
            log("autocustom: empty fileId")
            return None
        if file_id in files:
            log(f"autocustom: duplicate fileId {file_id}")
            return None
        frames = frames_for_rawfile(raw_path)
        if not frames:
            log(f"autocustom: cannot load rawfile {raw_path}")
            return None
        files[file_id] = (frames[0], frames[1:])
        if default_id is None:
            default_id = file_id
        log(f"autocustom: loaded fileId={file_id} start=1 chunks={len(frames) - 1}")
    if not files:
        log("autocustom: no files configured")
        return None
    return files, default_id


class DivoomClient:
    def __init__(self, mac, port=1):
        self.mac = mac
        self.port = port
        self.sock = None
        self.send_lock = threading.Lock()
        self.rx_buffer = bytearray()
        self.rx_queue = queue.Queue()
        self.rx_thread = None
        self.dispatch_thread = None
        self.rx_running = False
        self.on_packet = None  # callback(packet: bytes)

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

    def start_rx(self):
        if self.rx_thread is not None:
            return
        self.rx_running = True
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.rx_thread.start()
        self.dispatch_thread.start()

    def _rx_loop(self):
        # Drain socket continuously. Never block on user callbacks here -
        # packets go on rx_queue so the dispatch thread can take its time.
        while self.rx_running and self.sock is not None:
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            log(f"rx[{len(data)}]: {data.hex(' ')}")
            self.rx_buffer.extend(data)
            for packet in framed_packets(self.rx_buffer):
                self.rx_queue.put(packet)

    def _dispatch_loop(self):
        while self.rx_running:
            try:
                packet = self.rx_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            cb = self.on_packet
            if cb is None:
                continue
            try:
                cb(packet)
            except Exception as e:
                log(f"rx handler error: {e}")

    def send_frames(self, frames, delay_ms=150):
        if not self.sock: return
        with self.send_lock:
            for i, f in enumerate(frames):
                log(f"tx[{i}]: {f.hex(' ')}")
                self.sock.sendall(f)
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)

    def close(self):
        self.rx_running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

def run_daemon(mac, port, responder=None):
    fifo_path = os.environ.get("DIVOOM_FIFO", "/tmp/divoom.fifo")
    gap_ms = int(os.environ.get("DIVOOM_GAP_MS", "600"))

    if os.path.exists(fifo_path):
        os.unlink(fifo_path)
    os.mkfifo(fifo_path, 0o666)

    client = DivoomClient(mac, port)
    client.connect()
    if responder is not None:
        responder.client = client
        client.on_packet = responder.handle_packet
    client.start_rx()

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
    elif cmd == "daemon-custom":
        if len(sys.argv) < 6 or len(sys.argv) > 7:
            log("usage: divoom-send-linux.py <MAC> daemon-custom <fileId> <rawfile> <deviceId> [delay_ms]")
            sys.exit(64)
        file_id = sys.argv[3]
        rawfile = sys.argv[4]
        try:
            device_id = int(sys.argv[5])
        except ValueError:
            log("daemon-custom: deviceId must be int")
            sys.exit(64)
        delay_ms = int(sys.argv[6]) if len(sys.argv) == 7 else 40
        loaded = load_custom_files([(file_id, rawfile)])
        if loaded is None:
            sys.exit(65)
        files_by_id, default_id = loaded
        log(f"autocustom: enabled files=1 default={default_id} delay={delay_ms}ms deviceId={device_id}")
        responder = AutoCustomResponder(files_by_id, default_id, device_id, max(0, delay_ms))
        run_daemon(mac, port, responder)
    elif cmd == "daemon-custom-multi":
        if len(sys.argv) < 6:
            log("usage: divoom-send-linux.py <MAC> daemon-custom-multi <deviceId> <delay_ms> <fileId=rawfile>...")
            sys.exit(64)
        try:
            device_id = int(sys.argv[3])
            delay_ms = int(sys.argv[4])
        except ValueError:
            log("daemon-custom-multi: deviceId/delay_ms must be int")
            sys.exit(64)
        entries = []
        for spec in sys.argv[5:]:
            if "=" not in spec or spec.startswith("="):
                log(f"daemon-custom-multi: bad spec {spec}")
                sys.exit(64)
            fid, _, rp = spec.partition("=")
            if not rp:
                log(f"daemon-custom-multi: bad spec {spec}")
                sys.exit(64)
            entries.append((fid, rp))
        loaded = load_custom_files(entries)
        if loaded is None:
            sys.exit(65)
        files_by_id, default_id = loaded
        log(f"autocustom: enabled files={len(files_by_id)} default={default_id} delay={delay_ms}ms deviceId={device_id}")
        responder = AutoCustomResponder(files_by_id, default_id, device_id, max(0, delay_ms))
        run_daemon(mac, port, responder)
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
