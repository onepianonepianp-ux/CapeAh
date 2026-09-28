#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WEIRDMARKET - Combined Checker (100% VALID)
Fitur:
  1. CEK VALID  - Single & Bulk (sampai game server + role info)
  2. CEK BAN    - Single & Bulk
  3. SPLIT / DEVICE MANAGER
  4. 4 VERIFIKASI LANGKAH - 3X SCAN  ← PATCHED (Retry + Voting Mayoritas)
  5. TELEGRAM BOT
  6. EXIT

Logic valid: login server -> game server -> request role info
Client version: 2.2.16.1232.1 (sama dengan bot BF)
"""

import socket
import zlib
import zstandard as zstd
import datetime
import struct
import os
import json
import time
import asyncio
import io
import zipfile
import logging
import concurrent.futures
import threading
import re
from pathlib import Path
from enum import Enum
from typing import Any, Tuple, Optional, List, Dict

from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.table import Table
from Crypto.Cipher import AES
from colorama import init, Fore, Style, Back

init(autoreset=True)

console = Console()

# ── VERIF DEBUG LOGGER ──────────────────────────────────────────────
verif_logger = logging.getLogger("verif")
if not verif_logger.handlers:
    _vh = logging.FileHandler("verif_debug.log", mode="a", encoding="utf-8")
    _vh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _vh.setLevel(logging.WARNING)
    verif_logger.addHandler(_vh)
    verif_logger.setLevel(logging.WARNING)
    verif_logger.propagate = False

# ── DEVICE/SPLIT CONFIG ─────────────────────────────────────────────
DEVICE_RE = re.compile(r"(?i)(?:and_|ios_)[A-Za-z0-9_-]+")
RESULTS = Path(__file__).resolve().parent / "results"

# ── FITUR 4 CONFIG ──────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB
VERIF_THREADS = 10                 # diturunkan biar server ga rate-limit
VERIF_RETRY   = 3                  # retry kalau UNKNOWN
SOCKET_TIMEOUT = 15                # naik dari 5 detik

# ── GLOBAL MODE FLAGS ────────────────────────────────────────────────
DEBUG_MODE = False
RESULTS_FILE = "results_weiRd.txt"


# ── DEBUG HELPERS ────────────────────────────────────────────────────
def dbg(label, data=None, color=Fore.MAGENTA):
    if not DEBUG_MODE:
        return
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if data is None:
        print(f"{color}[DBG {ts}] {label}{Style.RESET_ALL}")
    else:
        print(f"{color}[DBG {ts}] {label}{Style.RESET_ALL}")
        if isinstance(data, (bytes, bytearray)):
            hex_str = data.hex()
            for i in range(0, len(hex_str), 64):
                print(f"  {Fore.CYAN}{hex_str[i:i+64]}{Style.RESET_ALL}")
        elif isinstance(data, dict):
            for k, v in data.items():
                print(f"  {Fore.CYAN}[{k}] => {repr(v)[:120]}{Style.RESET_ALL}")
        else:
            print(f"  {Fore.CYAN}{repr(data)[:200]}{Style.RESET_ALL}")


AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV = b'\x00' * 16


class SdpDataType(Enum):
    INTEGER_POSITIVE = 0
    INTEGER_NEGATIVE = 1
    FLOAT = 2
    DOUBLE = 3
    STRING = 4
    LIST = 5
    DICT = 6
    STRUCT_BEGIN = 7
    STRUCT_END = 8


class SdpException(Exception):
    pass


class SdpStruct(dict):
    def __init__(self, data=None):
        super().__init__()
        self.data = b''
        self.offset = 0
        if isinstance(data, bytes):
            self.data = data
            self.offset = 0
            self._unpack_from_binary()
        elif data is not None:
            super().update(data)
            self._pack_to_binary()

    def _pack_to_binary(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for tag, value in sorted(self.items()):
            self._pack(tag, value)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])

    def _unpack_from_binary(self):
        if not self.data:
            return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value:
            self.offset = 1
        while self.offset < len(self.data):
            tag, value = self._unpack()
            if isinstance(value, SdpDataType) and value == SdpDataType.STRUCT_END:
                break
            self[tag] = value

    def _write_number(self, value: int) -> bytes:
        result = bytearray()
        while value >= 0x80:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    def _read_number(self) -> int:
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag: int, data_type: SdpDataType) -> None:
        if tag < 15:
            self.data += bytes([(data_type.value << 4) | tag])
        else:
            self.data += bytes([(data_type.value << 4) | 15])
            self.data += self._write_number(tag)

    def _pack(self, tag: int, value: Any) -> None:
        if isinstance(value, bool):
            self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
            self.data += self._write_number(1 if value else 0)
        elif isinstance(value, int):
            if value < 0:
                self._pack_header(tag, SdpDataType.INTEGER_NEGATIVE)
                self.data += self._write_number(-value)
            else:
                self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
                self.data += self._write_number(value)
        elif isinstance(value, float):
            self._pack_header(tag, SdpDataType.DOUBLE)
            packed = struct.pack("<d", value)
            self.data += self._write_number(len(packed))
            self.data += packed
        elif isinstance(value, str) or isinstance(value, bytes):
            self._pack_header(tag, SdpDataType.STRING)
            encoded = value.encode('utf-8') if isinstance(value, str) else value
            self.data += self._write_number(len(encoded))
            self.data += encoded
        elif isinstance(value, list):
            self._pack_header(tag, SdpDataType.LIST)
            self.data += self._write_number(len(value))
            for item in value:
                self._pack(0, item)
        elif isinstance(value, dict):
            if isinstance(value, SdpStruct):
                self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(value.items()):
                    self._pack(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._pack_header(tag, SdpDataType.DICT)
                self.data += self._write_number(len(value))
                for k, v in sorted(value.items()):
                    self._pack(0, k)
                    self._pack(0, v)
        else:
            raise SdpException(f"Unsupported type: {type(value)}")

    def _unpack(self) -> Tuple[int, Any]:
        try:
            if self.offset >= len(self.data):
                return 0, None
            header = self.data[self.offset]
            tag = header & 0xF
            data_type = SdpDataType(header >> 4)
            self.offset += 1
            if tag == 15:
                tag = self._read_number()
            if data_type == SdpDataType.INTEGER_POSITIVE:
                value = self._read_number()
                return tag, value
            elif data_type == SdpDataType.INTEGER_NEGATIVE:
                value = -self._read_number()
                return tag, value
            elif data_type == SdpDataType.FLOAT:
                value = self._read_number().to_bytes(4, 'little')
                value = struct.unpack("<f", value)[0]
                return tag, value
            elif data_type == SdpDataType.DOUBLE:
                value = self._read_number().to_bytes(8, 'little')
                value = struct.unpack("<d", value)[0]
                return tag, value
            elif data_type == SdpDataType.STRING:
                length = self._read_number()
                try:
                    value = self.data[self.offset:self.offset+length].decode('utf-8')
                except UnicodeDecodeError:
                    value = self.data[self.offset:self.offset+length]
                self.offset += length
                return tag, value
            elif data_type == SdpDataType.LIST:
                length = self._read_number()
                value = []
                for _ in range(length):
                    _, item = self._unpack()
                    value.append(item)
                return tag, value
            elif data_type == SdpDataType.DICT:
                length = self._read_number()
                value = {}
                for _ in range(length):
                    _, k = self._unpack()
                    _, v = self._unpack()
                    value[k] = v
                return tag, value
            elif data_type == SdpDataType.STRUCT_BEGIN:
                struct_data = {}
                while True:
                    sub_tag, sub_value = self._unpack()
                    if isinstance(sub_value, SdpDataType) and sub_value == SdpDataType.STRUCT_END:
                        break
                    struct_data[sub_tag] = sub_value
                return tag, SdpStruct(struct_data)
            elif data_type == SdpDataType.STRUCT_END:
                return tag, SdpDataType.STRUCT_END
            else:
                raise SdpException("Unknown data type")
        except Exception:
            raise SdpException("Error unpacking data")

    def __repr__(self):
        return f"SdpStruct({dict(self)})"


class BaseConnection:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sequence = 1
        self.socket = None
        self.queue_data = b''

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(SOCKET_TIMEOUT)
        self.socket.connect((self.host, self.port))

    def cleanup(self):
        if self.socket:
            self.socket.close()
            self.sequence = 1
            self.socket = None

    def send_data(self, id, sdp):
        packet = SdpStruct({
            0: id,
            1: self.sequence,
            5: sdp.data
        }).data
        buf = zstd.compress(packet)
        flags = (len(buf) + 4) | (16 << 24)
        buf = flags.to_bytes(4, 'big') + buf
        dbg(f"SEND  packet_id={id}  seq={self.sequence}  payload_bytes={len(sdp.data)}  compressed={len(buf)}")
        dbg("      SDP fields", dict(sdp))
        self.socket.send(buf)
        self.sequence += 1

    def recv_data(self):
        try:
            while len(self.queue_data) < 4:
                data = self.socket.recv(4096)
                if not data:
                    return None, None
                self.queue_data += data

            flags = int.from_bytes(self.queue_data[:4], 'big')
            size = flags & 0xFFFFFF
            compression_type = flags >> 24

            while len(self.queue_data) < size:
                data = self.socket.recv(4096)
                if not data:
                    return None, None
                self.queue_data += data

            data = self.queue_data[4:size]
            self.queue_data = self.queue_data[size:]

            if compression_type == 1:
                data = zlib.decompress(data)
            elif compression_type == 16:
                data = zstd.decompress(data)
            elif compression_type in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                decrypted = cipher.decrypt(data[:-1] if len(data) % 16 != 0 else data)
                data = decrypted.rstrip(b'\x00')
                if compression_type == 3:
                    data = zlib.decompress(data)
                elif compression_type == 18:
                    data = zstd.decompress(data)

            result = SdpStruct(data)
            id = result.get(0)
            if id is None:
                return None, None

            res = result.get(6) or result.get(5)
            if not res or not isinstance(res, bytes):
                return id, None

            parsed_res = SdpStruct(res)
            dbg(f"RECV  id={id}  body_bytes={len(res)}  compression_type={compression_type}", color=Fore.CYAN)
            dbg("      SDP fields", dict(parsed_res), color=Fore.CYAN)
            return id, parsed_res

        except socket.timeout:
            return -1, None
        except Exception:
            return None, None


# ══════════════════════════════════════════════════════════════════════
# RANK MAPPER
# ══════════════════════════════════════════════════════════════════════
def map_rank(p):
    if p is None:
        return "Unknown"
    R = [
        (0,4,"Warrior III"),(5,9,"Warrior II"),(10,14,"Warrior I"),
        (15,19,"Elite IV"),(20,24,"Elite III"),(25,29,"Elite II"),(30,34,"Elite I"),
        (35,39,"Master IV"),(40,44,"Master III"),(45,49,"Master II"),(50,54,"Master I"),
        (55,59,"Grandmaster IV"),(60,64,"Grandmaster III"),(65,69,"Grandmaster II"),(70,74,"Grandmaster I"),
        (75,81,"Epic IV"),(82,88,"Epic III"),(89,95,"Epic II"),(96,107,"Epic I"),
        (108,114,"Legend IV"),(115,121,"Legend III"),(122,128,"Legend II"),(129,135,"Legend I"),
    ]
    for mn, mx, r in R:
        if mn <= p <= mx:
            return r
    if 136 <= p <= 160: return f"Mythic {p-135}"
    if 161 <= p <= 195: return f"Mythical Honor {p-135}"
    if 196 <= p <= 235: return f"Mythical Glory {p-157}"
    if p >= 236: return f"Mythical Immortal {p-157}"
    return "Unknown"


# ══════════════════════════════════════════════════════════════════════
# GAME LOGIN — 100% VALID (sampai game server + role info)
# ══════════════════════════════════════════════════════════════════════
class GameLogin(BaseConnection):
    def __init__(self, device_id):
        super().__init__('login.ml.youngjoygame.com', 30021)
        self.device_id = device_id

        parts = self.device_id.split('_')
        if len(parts) >= 2:
            device_info = parts[1]
            if len(parts) >= 3 and len(device_info) < 32:
                device_info = device_info + "_" + parts[2]
            if len(device_info) >= 32:
                self.imei_md5 = device_info[:32]
                self.android_id = device_info[32:48] if len(device_info) >= 48 else ""
                self.advertising_id = device_info[48:] if len(device_info) > 48 else ""
            else:
                self.imei_md5 = device_info
                self.android_id = ""
                self.advertising_id = ""
        else:
            self.imei_md5 = device_id
            self.android_id = ""
            self.advertising_id = ""

        self.channel = 'and_usa'
        self.client_version = '2.2.16.1232.1'
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_server_host = ''
        self.game_server_port = 0
        self.creation_ts = 0
        self.kick_detected = False

    def _login_packet(self):
        return SdpStruct({
            0: self.device_id,
            1: f'gps_adid={self.advertising_id}&android_id={self.android_id}&device_unique_id={self.imei_md5}',
            2: self.client_version,
            3: self.channel,
            4: 'en'
        })

    def login_to_login_server(self):
        self.send_data(1, self._login_packet())
        id, res = self.recv_data()
        if id == 2 and res:
            self.account_id = res.get(0)
            self.session_key = res.get(1)
            zone_data = res.get(2)
            if isinstance(zone_data, list) and zone_data:
                self.zone_id = zone_data[0] if not isinstance(zone_data[0], dict) else zone_data[0].get(0, 0)
            elif isinstance(zone_data, dict):
                self.zone_id = zone_data.get(0, 0)
            else:
                self.zone_id = zone_data or 0
            self.creation_ts = res.get(19, 0)
            return True
        return False

    def get_game_server(self):
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key,
            2: self.client_version, 5: self.zone_id, 6: self.channel
        }))
        id, res = self.recv_data()
        if id == 6 and res:
            gs = res[1]
            self.game_server_host, self.game_server_port = gs.split(':')
            self.game_server_port = int(self.game_server_port)
            return True
        return False

    def connect_to_game_server(self):
        self.cleanup()
        self.host = self.game_server_host
        self.port = self.game_server_port
        self.connect()

        self.send_data(10001, SdpStruct({
            0: self.account_id,
            1: self.session_key,
            2: self.zone_id,
            4: self.client_version,
            13: self.channel,
            15: self.device_id
        }))
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))

        while True:
            pid, res = self.recv_data()
            if pid is None:
                return False
            elif pid == 10002:
                return True
            elif pid == -1:
                return False
            elif pid == 20001:
                try:
                    if self._is_kick_notification(res):
                        self.kick_detected = True
                except Exception:
                    pass
                return True

    def _is_kick_notification(self, res):
        if not res:
            return False
        keywords = [
            'login di perangkat lain', 'perangkat lain',
            'logged in on another device', 'another device',
            'other device', 'kick', 'kicked',
            'login elsewhere', 'device lain',
        ]

        def check_value(v):
            if isinstance(v, str):
                lv = v.lower()
                return any(kw in lv for kw in keywords)
            elif isinstance(v, bytes):
                try:
                    lv = v.decode('utf-8', errors='ignore').lower()
                    return any(kw in lv for kw in keywords)
                except Exception:
                    pass
            return False

        def walk(d):
            if isinstance(d, dict):
                for k, v in d.items():
                    if check_value(v):
                        return True
                    if isinstance(v, (dict, list)) and walk(v):
                        return True
            elif isinstance(d, list):
                for item in d:
                    if check_value(item):
                        return True
                    if isinstance(item, (dict, list)) and walk(item):
                        return True
            return False

        try:
            return walk(res)
        except Exception:
            return False

    def lookup_player(self, search_value, search_type="id"):
        if search_type == "id":
            try:
                ld = SdpStruct({1: int(search_value)})
            except ValueError:
                ld = SdpStruct({1: search_value})
        else:
            ld = SdpStruct({0: str(search_value).strip()})
        self.send_data(11153, ld)
        cnt = 0
        while True:
            pid, res = self.recv_data()
            if pid is None:
                return None
            elif pid == -1:
                return None
            elif pid == 11154:
                return res
            elif pid == 20001:
                cnt += 1
                if cnt >= 2:
                    return None

    def get_skin_role_info(self, role_id, zone_id, max_retries=3):
        for _ in range(max_retries):
            try:
                self.send_data(10143, SdpStruct({0: int(role_id), 1: int(zone_id)}))
                to = 0
                while to < 3:
                    pid, res = self.recv_data()
                    if pid is None:
                        break
                    elif pid == -1:
                        to += 1
                    elif pid == 10144:
                        return res
                    elif pid == 20001:
                        continue
            except Exception:
                pass
        return None

    def run(self):
        """Login server -> game server -> role info.
        Returns dict with data, or None if fail.
        """
        try:
            self.connect()
            dbg(f"LOGIN SERVER → sending packet 1  device_id={self.device_id[:30]}...")

            if not self.login_to_login_server():
                dbg(f"LOGIN FAILED", color=Fore.RED)
                return None

            dbg(f"LOGIN OK  account_id={self.account_id}  zone_id={self.zone_id}", color=Fore.GREEN)

            if not self.get_game_server():
                dbg(f"GAME SERVER FAILED", color=Fore.RED)
                return None

            dbg(f"GAME SERVER OK  {self.game_server_host}:{self.game_server_port}", color=Fore.GREEN)

            if not self.connect_to_game_server():
                dbg(f"CONNECT GAME SERVER FAILED", color=Fore.RED)
                return None

            dbg(f"CONNECTED TO GAME SERVER", color=Fore.GREEN)

            role_info = None
            try:
                role_info = self.get_skin_role_info(self.account_id, self.zone_id)
            except Exception as e:
                dbg(f"ROLE INFO FAILED: {e}", color=Fore.YELLOW)

            pdata = None
            try:
                result = self.lookup_player(self.account_id, "id")
                if result and result.get(0) and len(result[0]) > 0:
                    pd = result[0][0]
                    pdata = {
                        "nickname": pd.get(2, "-"),
                        "player_id": pd.get(0, "-"),
                        "server": pd.get(1, "-"),
                        "level": pd.get(3, 0),
                        "skin_count": pd.get(83, 0),
                        "hero_count": pd.get(4, 0),
                        "matches": pd.get(17, 0),
                        "high_rank": map_rank(pd.get(95)),
                        "current_rank": map_rank(pd.get(8)),
                    }
                    if role_info:
                        pdata["hero_count"] = role_info.get(9, pdata["hero_count"])
                        pdata["matches"] = role_info.get(22, pdata["matches"])
            except Exception as e:
                dbg(f"LOOKUP FAILED: {e}", color=Fore.YELLOW)

            return {
                "account_id": self.account_id,
                "zone_id": self.zone_id,
                "session_key": self.session_key,
                "creation_ts": self.creation_ts,
                "game_server": f"{self.game_server_host}:{self.game_server_port}",
                "player_data": pdata,
                "kick": self.kick_detected,
            }

        except Exception as e:
            dbg(f"ERROR: {str(e)}", color=Fore.RED)
            return None
        finally:
            self.cleanup()


# ── BAN CHECKER NETWORK CONNECTION ───────────────────────────────────
class BanCheckerConnection:
    def __init__(self, device_id: str):
        self.host = 'login.ml.youngjoygame.com'
        self.port = 30021
        self.sequence = 1
        self.socket = None
        self.queue_data = b''
        self.device_id = device_id

        parts = device_id.split('_')
        device_info = parts[1] if len(parts) >= 2 else device_id
        if len(parts) >= 3 and len(device_info) < 32:
            device_info = device_info + "_" + parts[2]

        if len(device_info) >= 32:
            self.imei_md5 = device_info[:32]
            self.android_id = device_info[32:48] if len(device_info) >= 48 else ""
            self.advertising_id = device_info[48:] if len(device_info) > 48 else ""
        else:
            self.imei_md5 = device_id
            self.android_id = ""
            self.advertising_id = ""

        self.channel = 'and_usa'
        self.client_version = '2.2.16.1232.1'
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_server_host = ''
        self.game_server_port = 0

    def connect(self, host=None, port=None):
        if host:
            self.host = host
        if port:
            self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(SOCKET_TIMEOUT)
        self.socket.connect((self.host, self.port))

    def cleanup(self):
        if self.socket:
            self.socket.close()
            self.sequence = 1
            self.socket = None

    def send_data(self, pkt_id, sdp):
        packet = SdpStruct({
            0: pkt_id,
            1: self.sequence,
            5: sdp.data
        }).data
        buf = zstd.compress(packet)
        flags = (len(buf) + 4) | (16 << 24)
        buf = flags.to_bytes(4, 'big') + buf
        self.socket.send(buf)
        self.sequence += 1

    def recv_data(self):
        try:
            while len(self.queue_data) < 4:
                data = self.socket.recv(4096)
                if not data:
                    return None, None
                self.queue_data += data

            flags = int.from_bytes(self.queue_data[:4], 'big')
            size = flags & 0xFFFFFF
            compression_type = flags >> 24

            while len(self.queue_data) < size:
                data = self.socket.recv(4096)
                if not data:
                    return None, None
                self.queue_data += data

            data = self.queue_data[4:size]
            self.queue_data = self.queue_data[size:]

            if compression_type == 1:
                data = zlib.decompress(data)
            elif compression_type == 16:
                data = zstd.decompress(data)
            elif compression_type in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data = cipher.decrypt(data[:-1] if len(data) % 16 != 0 else data)
                data = data.rstrip(b'\x00')
                if compression_type == 3:
                    data = zlib.decompress(data)
                elif compression_type == 18:
                    data = zstd.decompress(data)

            result = SdpStruct(data)
            pkt_id = result.get(0)
            if pkt_id is None:
                return None, None

            res = result.get(6) or result.get(5)
            if not res or not isinstance(res, bytes):
                return pkt_id, None

            return pkt_id, SdpStruct(res)

        except socket.timeout:
            return -1, None
        except Exception:
            return None, None


# ── BAN REASON MAPPING ───────────────────────────────────────────────
BAN_REASONS = {
    "21": "Using Plug-in Apps to Compromise Competitive Fairness",
}


def inspect_for_ban(pkt_id, sdp_data):
    is_banned = False
    details = {}

    if sdp_data:
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == 'ban_reason':
                        code_str = str(v)
                        details['ban_code'] = code_str
                        details['reason_name'] = BAN_REASONS.get(code_str, "Using Plug-in Apps to Compromise Competitive Fairness")
                    elif k in ('ban_status', 'ban_time') or (isinstance(k, str) and 'ban' in k.lower()):
                        details[str(k)] = v
                    if k == 'endtime_day': details['endtime_day'] = v
                    if k == 'endtime_hour': details['endtime_hour'] = v
                    if k == 'endtime_min': details['endtime_min'] = v
                    if k == 'endtime_sec': details['endtime_sec'] = v
                    if isinstance(v, (dict, list)): scan(v)
            elif isinstance(obj, list):
                for item in obj: scan(item)

        scan(dict(sdp_data))

    if 'endtime_day' in details and details['endtime_day'] is not None:
        is_banned = True

    return is_banned, details


# ── UI DASAR ──────────────────────────────────────────────────────────
APP_NAME = "WEIRD TOOLS"
APP_CREDIT = "WEIRDMARKET"
APP_VERSION = "v2.3"
UI_WIDTH = 76

ACCENT = Fore.CYAN
ACCENT_2 = Fore.MAGENTA
TITLE = Fore.WHITE + Style.BRIGHT
MUTED = Fore.LIGHTBLACK_EX
SUCCESS = Fore.GREEN + Style.BRIGHT
WARNING = Fore.YELLOW + Style.BRIGHT
DANGER = Fore.RED + Style.BRIGHT


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def line(char="─", width=UI_WIDTH, color=MUTED):
    print(f"{color}{char * width}{Style.RESET_ALL}")


def center(text, color=Fore.WHITE, bold=False, width=UI_WIDTH):
    style = Style.BRIGHT if bold else ""
    print(f"{color}{style}{text[:width].center(width)}{Style.RESET_ALL}")


def _big_weird_tools():
    art = [
        "██╗    ██╗███████╗██╗██████╗ ██████╗",
        "██║    ██║██╔════╝██║██╔══██╗██╔══██╗",
        "██║ █╗ ██║█████╗  ██║██████╔╝██║  ██║",
        "██║███╗██║██╔══╝  ██║██╔══██╗██║  ██║",
        "╚███╔███╔╝███████╗██║██║  ██║██████╔╝",
        " ╚══╝╚══╝ ╚══════╝╚═╝╚═╝  ╚═╝╚═════╝ ",
        "        ████████╗ ██████╗  ██████╗ ██╗     ███████╗",
        "        ╚══██╔══╝██╔═══██╗██╔═══██╗██║     ██╔════╝",
        "           ██║   ██║   ██║██║   ██║██║     ███████╗",
        "           ██║   ██║   ██║██║   ██║██║     ╚════██║",
        "           ██║   ╚██████╔╝╚██████╔╝███████╗███████║",
        "           ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝╚══════╝",
    ]
    for row in art:
        center(row, Fore.CYAN, True)


def section(title):
    print()
    print(f"{ACCENT}╭{'─' * (UI_WIDTH - 2)}╮{Style.RESET_ALL}")
    print(f"{ACCENT}│{Style.RESET_ALL} {TITLE}{title:<{UI_WIDTH - 4}}{Style.RESET_ALL} {ACCENT}│{Style.RESET_ALL}")
    print(f"{ACCENT}╰{'─' * (UI_WIDTH - 2)}╯{Style.RESET_ALL}")


def footer():
    print()
    line("─", UI_WIDTH, Fore.LIGHTBLACK_EX)
    center(f"{APP_CREDIT}  •  {APP_NAME} {APP_VERSION}", Fore.LIGHTBLACK_EX)
    line("─", UI_WIDTH, Fore.LIGHTBLACK_EX)


def pause():
    print()
    input(f"{MUTED}Press {Fore.WHITE}[ENTER]{MUTED} to continue...{Style.RESET_ALL}")


def banner():
    clear_screen()
    print()
    print(f"{ACCENT_2}╭{'═' * (UI_WIDTH - 2)}╮{Style.RESET_ALL}")
    _big_weird_tools()
    print(f"{ACCENT_2}├{'═' * (UI_WIDTH - 2)}┤{Style.RESET_ALL}")
    center("WEIRDMARKET  •  OFFICIAL TOOLS", Fore.MAGENTA, True)
    center("VALID / BAN CHECKER", Fore.CYAN, True)
    center(APP_VERSION, Fore.LIGHTBLACK_EX)
    print(f"{ACCENT_2}╰{'═' * (UI_WIDTH - 2)}╯{Style.RESET_ALL}")


# ══════════════════════════════════════════════════════════════════════
# VALID MODE — 100% VALID
# ══════════════════════════════════════════════════════════════════════
def save_valid_result(device_id, data):
    """Simpan hasil valid ke file."""
    result_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VALID_RESULTS.txt")
    pd = data.get("player_data") or {}
    with open(result_file, "a", encoding="utf-8") as f:
        f.write(
            f"DEVICE ID  : {device_id}\n"
            f"ACCOUNT ID : {data.get('account_id')}\n"
            f"ZONE ID    : {data.get('zone_id')}\n"
            f"NICKNAME   : {pd.get('nickname', '-')}\n"
            f"LEVEL      : {pd.get('level', 0)}\n"
            f"SKIN       : {pd.get('skin_count', 0)}\n"
            f"HERO       : {pd.get('hero_count', 0)}\n"
            f"RANK       : {pd.get('current_rank', '-')}\n"
            f"HIGH RANK  : {pd.get('high_rank', '-')}\n"
            f"{'-' * 58}\n"
        )


def print_valid_card(device_id, data):
    """Tampilkan card valid yang rapi."""
    pd = data.get("player_data") or {}
    width = UI_WIDTH
    inner = width - 2
    device_display = device_id if len(device_id) <= inner - 14 else device_id[:inner - 17] + "..."

    print()
    print(f"{Fore.GREEN}╭{'━' * inner}╮{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│{Style.RESET_ALL}{Fore.GREEN}{Style.BRIGHT}{'✓  VALID HIT'.center(inner)}{Style.RESET_ALL}{Fore.GREEN}│{Style.RESET_ALL}")
    print(f"{Fore.GREEN}├{'─' * inner}┤{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}DEVICE ID{Style.RESET_ALL}  {Fore.WHITE}{device_display}{Style.RESET_ALL}" + ' ' * max(0, inner - 12 - len(device_display)) + f"{Fore.GREEN}│{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}ACCOUNT ID{Style.RESET_ALL} {Fore.CYAN}{Style.BRIGHT}{data.get('account_id')}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(data.get('account_id')))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}ZONE ID{Style.RESET_ALL}    {Fore.CYAN}{Style.BRIGHT}{data.get('zone_id')}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(data.get('zone_id')))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
    if pd:
        print(f"{Fore.GREEN}├{'─' * inner}┤{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}NICKNAME{Style.RESET_ALL}   {Fore.WHITE}{pd.get('nickname', '-')}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(pd.get('nickname', '-')))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}LEVEL{Style.RESET_ALL}      {Fore.WHITE}{pd.get('level', 0)}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(pd.get('level', 0)))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}SKIN{Style.RESET_ALL}       {Fore.WHITE}{pd.get('skin_count', 0)}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(pd.get('skin_count', 0)))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}HERO{Style.RESET_ALL}       {Fore.WHITE}{pd.get('hero_count', 0)}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(pd.get('hero_count', 0)))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}RANK{Style.RESET_ALL}       {Fore.WHITE}{pd.get('current_rank', '-')}{Style.RESET_ALL}" + ' ' * max(0, inner - 13 - len(str(pd.get('current_rank', '-')))) + f"{Fore.GREEN}│{Style.RESET_ALL}")
    print(f"{Fore.GREEN}├{'─' * inner}┤{Style.RESET_ALL}")
    saved = "✓  SAVED  •  VALID_RESULTS.txt"
    print(f"{Fore.GREEN}│{Style.RESET_ALL}{Fore.YELLOW}{saved.center(inner)}{Style.RESET_ALL}{Fore.GREEN}│{Style.RESET_ALL}")
    print(f"{Fore.GREEN}╰{'━' * inner}╯{Style.RESET_ALL}")


def valid_single():
    banner()
    section("◈  CEK VALID • SINGLE")
    device_id = input(
        f"\n  {Fore.MAGENTA}WEIRD{Style.RESET_ALL} "
        f"{Fore.CYAN}❯{Style.RESET_ALL} DEVICE ID\n"
        f"  {Fore.YELLOW}➤ {Style.RESET_ALL}"
    ).strip()

    if not device_id:
        print(f"\n  {Fore.RED}✖ ERROR: No Device ID entered.{Style.RESET_ALL}")
        pause()
        return

    print(f"\n  {Fore.MAGENTA}◌{Style.RESET_ALL} Checking valid status...")
    bot = GameLogin(device_id)
    data = bot.run()

    if data and data.get("account_id") and data.get("zone_id"):
        save_valid_result(device_id, data)
        print_valid_card(device_id, data)
    else:
        print(f"\n  {Fore.RED}✖ LOGIN / VALIDATION FAILED{Style.RESET_ALL}")

    footer()
    pause()


def valid_bulk():
    banner()
    section("◈  CEK VALID • BULK")
    filepath = input(
        f"\n  {Fore.CYAN}FILE PATH{Style.RESET_ALL}\n  "
        f"{Fore.YELLOW}➤ {Style.RESET_ALL}"
    ).strip().replace('"', '')

    if not os.path.exists(filepath):
        print(f"\n  {Fore.RED}✖ File not found.{Style.RESET_ALL}")
        pause()
        return

    device_ids = read_device_ids_from_file(filepath)

    if not device_ids:
        print(f"\n  {Fore.RED}✖ File is empty.{Style.RESET_ALL}")
        pause()
        return

    valid_count = 0
    fail_count = 0
    total = len(device_ids)

    print()
    for i, dev_id in enumerate(device_ids, 1):
        print(f"  {Fore.CYAN}[{i:>4}/{total:<4}]{Style.RESET_ALL} {dev_id[:52]}")
        try:
            bot = GameLogin(dev_id)
            data = bot.run()
            if data and data.get("account_id") and data.get("zone_id"):
                valid_count += 1
                save_valid_result(dev_id, data)
                pd = data.get("player_data") or {}
                print(f"     {Fore.GREEN}✓ VALID{Style.RESET_ALL}  "
                      f"Acc: {data.get('account_id')} | Zone: {data.get('zone_id')} | "
                      f"Skin: {pd.get('skin_count', 0)} | Rank: {pd.get('current_rank', '-')}")
            else:
                fail_count += 1
                print(f"     {Fore.RED}✖ FAILED{Style.RESET_ALL}")
        except Exception as e:
            fail_count += 1
            print(f"     {Fore.RED}✖ ERROR: {e}{Style.RESET_ALL}")

    section("◈  VALID BULK COMPLETE")
    print(f"\n  {Fore.GREEN}✓ VALID  : {valid_count}{Style.RESET_ALL}")
    print(f"  {Fore.RED}✖ FAILED : {fail_count}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}◉ TOTAL  : {total}{Style.RESET_ALL}")
    footer()
    pause()


# ══════════════════════════════════════════════════════════════════════
# BAN MODE
# ══════════════════════════════════════════════════════════════════════
def format_ban_string(device_id: str, ban_info: dict) -> str:
    reason = ban_info.get('reason_name', 'Using Plug-in Apps to Compromise Competitive Fairness')
    day = ban_info.get('endtime_day')
    hour = ban_info.get('endtime_hour', '00')
    minute = ban_info.get('endtime_min', '00')
    sec = ban_info.get('endtime_sec', '00')
    return f"{device_id} |  Reason Name: {reason} |  Duration: Day {day}, {hour}:{minute}:{sec}"


def check_device_ban_silent(device_id: str) -> Tuple[str, str]:
    conn = BanCheckerConnection(device_id)
    try:
        conn.connect('login.ml.youngjoygame.com', 30021)
        conn.send_data(1, SdpStruct({
            0: conn.device_id,
            1: f'gps_adid={conn.advertising_id}&android_id={conn.android_id}&device_unique_id={conn.imei_md5}',
            2: conn.client_version,
            3: conn.channel,
            4: 'en'
        }))

        pkt_id, res = conn.recv_data()
        banned, ban_info = inspect_for_ban(pkt_id, res)
        if banned: return "BANNED", format_ban_string(device_id, ban_info)

        if pkt_id == 2 and res:
            conn.account_id = res.get(0)
            conn.session_key = res.get(1)
            zone_data = res.get(2)
            if isinstance(zone_data, dict): conn.zone_id = zone_data.get(0, 0)
            elif isinstance(zone_data, list) and len(zone_data) > 0:
                conn.zone_id = zone_data[0] if not isinstance(zone_data[0], dict) else zone_data[0].get(0, 0)
            else: conn.zone_id = zone_data or 0
        else:
            return "UNKNOWN", device_id

        conn.send_data(5, SdpStruct({
            0: conn.account_id, 1: conn.session_key, 2: conn.client_version,
            5: conn.zone_id, 6: conn.channel
        }))

        pkt_id, res = conn.recv_data()
        banned, ban_info = inspect_for_ban(pkt_id, res)
        if banned: return "BANNED", format_ban_string(device_id, ban_info)

        if pkt_id == 6 and res:
            game_server = res[1]
            conn.game_server_host, conn.game_server_port = game_server.split(':')
            conn.game_server_port = int(conn.game_server_port)
        else:
            return "UNKNOWN", device_id

        conn.cleanup()
        conn.connect(conn.game_server_host, conn.game_server_port)

        conn.send_data(10001, SdpStruct({
            0: conn.account_id, 1: conn.session_key, 2: conn.zone_id,
            4: conn.client_version, 13: conn.channel, 15: conn.device_id
        }))
        conn.send_data(10101, SdpStruct({0: 0, 2: 2}))

        role_requested = False
        while True:
            pkt_id, res = conn.recv_data()
            banned, ban_info = inspect_for_ban(pkt_id, res)

            if banned:
                return "BANNED", format_ban_string(device_id, ban_info)

            if pkt_id is None or pkt_id == -1:
                return "UNKNOWN", device_id
            elif pkt_id == 10002 and not role_requested:
                conn.send_data(10003, SdpStruct({
                    0: conn.account_id, 1: conn.session_key, 2: conn.zone_id,
                    3: conn.client_version, 4: conn.channel, 5: conn.device_id
                }))
                role_requested = True
            elif pkt_id in (10004, 10008):
                return "CLEAN", device_id
    except Exception:
        return "UNKNOWN", device_id
    finally:
        conn.cleanup()


# ── THREADING & BULK LOGIC ──────────────────────────────────────────
progress_lock = threading.Lock()
file_lock = threading.Lock()
processed_count = 0
banned_count = 0
clean_count = 0
total_count = 0


def update_progress():
    global processed_count, banned_count, clean_count, total_count
    with progress_lock:
        total = max(total_count, 1)
        done = min(processed_count, total_count)
        pct = (done / total) * 100
        bar_width = 18
        filled = int(bar_width * done / total)
        bar = "━" * filled + "─" * (bar_width - filled)

        border = Fore.LIGHTBLACK_EX
        title = Fore.CYAN + Style.BRIGHT
        accent = Fore.CYAN + Style.BRIGHT
        neutral = Fore.WHITE + Style.BRIGHT
        muted = Fore.LIGHTBLACK_EX
        warning = Fore.YELLOW + Style.BRIGHT
        danger = Fore.RED + Style.BRIGHT

        dashboard = (
            f"{border}│{Style.RESET_ALL} "
            f"{title}WEIRD TOOLS{Style.RESET_ALL} "
            f"{muted}• BULK CHECK{Style.RESET_ALL} "
            f"{neutral}{done}/{total_count}{Style.RESET_ALL} "
            f"{accent}{bar}{Style.RESET_ALL} "
            f"{warning}{pct:5.1f}%{Style.RESET_ALL} "
            f"{muted}│{Style.RESET_ALL} "
            f"{neutral}CHECKED {done}{Style.RESET_ALL} "
            f"{muted}│{Style.RESET_ALL} "
            f"{accent}NOT BAN {clean_count}{Style.RESET_ALL} "
            f"{muted}│{Style.RESET_ALL} "
            f"{danger}BAN {banned_count}{Style.RESET_ALL}"
        )
        print("\r\033[2K" + dashboard, end="", flush=True)


def process_device_worker(device_id: str, ban_filepath: str, clean_filepath: str):
    global processed_count, banned_count, clean_count

    status, result_str = check_device_ban_silent(device_id)

    with file_lock:
        if status == "BANNED":
            banned_count += 1
            with open(ban_filepath, "a", encoding="utf-8") as f:
                f.write(result_str + "\n")
        elif status == "CLEAN":
            clean_count += 1
            with open(clean_filepath, "a", encoding="utf-8") as f:
                f.write(result_str + "\n")
        elif status == "UNKNOWN":
            with open(os.path.join(os.path.dirname(ban_filepath), "UNKNOWN.txt"), "a", encoding="utf-8") as f:
                f.write(result_str + "\n")

        processed_count += 1

    update_progress()


def run_bulk_mode():
    global processed_count, banned_count, clean_count, total_count
    processed_count = 0
    banned_count = 0
    clean_count = 0

    print(f"\n{Fore.YELLOW}--- BULK CHECK MODE ---{Style.RESET_ALL}")

    filepath = input(f"{Fore.CYAN}Enter filepath containing Device IDs: {Style.RESET_ALL}").strip()
    if not os.path.exists(filepath):
        print(f"{Fore.RED}File not found!{Style.RESET_ALL}")
        return

    try:
        threads_input = int(input(f"{Fore.CYAN}Enter number of threads (1-20 max): {Style.RESET_ALL}").strip())
        threads = max(1, min(20, threads_input))
    except ValueError:
        threads = 1
        print(f"{Fore.YELLOW}Invalid input, defaulting to 1 thread.{Style.RESET_ALL}")

    with open(filepath, "r", encoding="utf-8") as f:
        device_ids = [line.strip() for line in f if line.strip()]

    total_count = len(device_ids)
    if total_count == 0:
        print(f"{Fore.RED}No valid Device IDs found in file.{Style.RESET_ALL}")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    save_dir = os.path.join(base_dir, "ban_results")
    os.makedirs(save_dir, exist_ok=True)
    ban_file = os.path.join(save_dir, "BAN 100%.txt")
    clean_file = os.path.join(save_dir, "NOT BAN 100%.txt")

    print(f"{Fore.CYAN}╭────────────────────────────────────────────────────────────────────╮{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│{Style.RESET_ALL} {Fore.YELLOW}⚡ BULK CHECK INITIALIZED{Style.RESET_ALL}   "
          f"{Fore.LIGHTBLACK_EX}Threads:{Style.RESET_ALL} {Fore.WHITE}{threads}{Style.RESET_ALL}"
          f" {Fore.CYAN}│{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╰────────────────────────────────────────────────────────────────────╯{Style.RESET_ALL}\n")
    update_progress()

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [
            executor.submit(process_device_worker, d_id, ban_file, clean_file)
            for d_id in device_ids
        ]
        for future in futures:
            try:
                future.result()
            except Exception as e:
                print(f"\\n{Fore.RED}Worker error: {type(e).__name__}: {e}{Style.RESET_ALL}")

    print(f"\n{Fore.LIGHTBLACK_EX}╭────────────────────────────────────────────────────────────────────╮{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}BULK CHECK COMPLETE{Style.RESET_ALL}"
          f" {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLACK_EX}╰────────────────────────────────────────────────────────────────────╯{Style.RESET_ALL}")
    unknown_file = os.path.join(save_dir, "UNKNOWN.txt")
    print(
        f"Results saved to:\n"
        f"- {ban_file}\n"
        f"- {clean_file}\n"
        f"- {unknown_file}\n"
    )
    print(
        f"{Fore.WHITE}Summary: {Fore.GREEN}{clean_count} NOT BAN"
        f"{Fore.WHITE} | {Fore.RED}{banned_count} BAN"
        f"{Fore.WHITE} | {Fore.YELLOW}{total_count - clean_count - banned_count} UNKNOWN/ERROR"
        f"{Style.RESET_ALL}"
    )


def check_device_ban(device_id: str):
    print(f"\n  {Fore.MAGENTA}◌{Style.RESET_ALL} Checking ban status...")
    status, result = check_device_ban_silent(device_id)

    if status == "BANNED":
        print(f"\n  {Fore.RED}{Style.BRIGHT}✖ BANNED{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{result}{Style.RESET_ALL}")
    elif status == "CLEAN":
        print(f"\n  {Fore.GREEN}{Style.BRIGHT}✓ NOT BANNED{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{result}{Style.RESET_ALL}")
    else:
        print(f"\n  {Fore.YELLOW}{Style.BRIGHT}⚠ UNKNOWN / CHECK FAILED{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{result}{Style.RESET_ALL}")

    return status, result


def ban_single():
    banner()
    section("◈  CEK BAN • SINGLE")
    device_id = input(
        f"\n  {Fore.CYAN}DEVICE ID{Style.RESET_ALL}\n  "
        f"{Fore.YELLOW}➤ {Style.RESET_ALL}"
    ).strip()

    if not device_id:
        print(f"\n  {Fore.RED}✖ No Device ID entered.{Style.RESET_ALL}")
        pause()
        return

    check_device_ban(device_id)
    pause()


# ══════════════════════════════════════════════════════════════════════
# SPLIT / DEVICE MANAGER
# ══════════════════════════════════════════════════════════════════════
def normalize(line: str) -> str:
    raw = (line or "").strip()
    if not raw:
        return ""
    match = re.search(r"(?i)(?:and_|ios_)[A-Za-z0-9_-]+", raw)
    if not match:
        return ""
    candidate = match.group(0)
    return candidate if DEVICE_RE.fullmatch(candidate) else ""


def extract_records(text: str):
    text = text or ""
    blocks = re.split(r"(?m)^\s*---\s*$", text)
    records = []
    id_pattern = re.compile(r"(?i)(?:and_|ios_)[A-Za-z0-9_-]+")

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.splitlines()
        id_lines = []
        for idx, line in enumerate(lines):
            m = id_pattern.search(line)
            if m and DEVICE_RE.fullmatch(m.group(0)):
                id_lines.append((idx, m.group(0)))

        if not id_lines:
            continue

        if len(id_lines) > 1:
            for n, (start_idx, device_id) in enumerate(id_lines):
                end_idx = id_lines[n + 1][0] if n + 1 < len(id_lines) else len(lines)
                chunk = lines[start_idx:end_idx]
                cleaned = []
                for line in chunk:
                    line = line.rstrip()
                    if not line.strip():
                        cleaned.append("")
                        continue
                    m = id_pattern.search(line)
                    if m and m.group(0).lower() == device_id.lower():
                        prefix = line[:m.start()]
                        if re.fullmatch(r"\s*(?:\d+[.)]\s*|[-*]\s*)?", prefix):
                            line = line[m.start():]
                    cleaned.append(line)
                record_text = "\n".join(cleaned).strip()
                if record_text:
                    records.append({"id": device_id, "text": record_text})
            continue

        start_idx, device_id = id_lines[0]
        cleaned = []
        for line in lines[start_idx:]:
            line = line.rstrip()
            if not line.strip():
                cleaned.append("")
                continue
            m = id_pattern.search(line)
            if m and m.group(0).lower() == device_id.lower():
                prefix = line[:m.start()]
                if re.fullmatch(r"\s*(?:\d+[.)]\s*|[-*]\s*)?", prefix):
                    line = line[m.start():]
            cleaned.append(line)

        record_text = "\n".join(cleaned).strip()
        if record_text:
            records.append({"id": device_id, "text": record_text})

    return records


def load_records(path: str):
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    with p.open("r", encoding="utf-8-sig", errors="ignore") as f:
        return extract_records(f.read())


def load_file(path: str):
    return [r["id"] for r in load_records(path)]


def unique_records_keep_order(records):
    seen = set()
    out = []
    duplicates = 0
    for record in records:
        key = record["id"].lower()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        out.append(record)
    return out, duplicates


def unique_keep_order(items):
    seen = set()
    out = []
    duplicates = 0
    for item in items:
        key = item.lower()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        out.append(item)
    return out, duplicates


def save_numbered_records(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for i, record in enumerate(records, 1):
            lines = record["text"].splitlines()
            if lines:
                f.write(f"{i}. {lines[0]}\n")
                for line in lines[1:]:
                    f.write(line + "\n")
            f.write("---\n")


def save_plain_records(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record["text"].rstrip() + "\n")
            f.write("---\n")


def read_device_ids_from_file(filepath):
    records = load_records(filepath)
    clean, _ = unique_records_keep_order(records)
    return [r["id"] for r in clean]


def export_all_records(records):
    RESULTS.mkdir(exist_ok=True)
    android = [r for r in records if r["id"].lower().startswith("and_")]
    ios = [r for r in records if r["id"].lower().startswith("ios_")]
    save_numbered_records(RESULTS / "all_devices.txt", records)
    save_numbered_records(RESULTS / "android_and.txt", android)
    save_numbered_records(RESULTS / "ios.txt", ios)
    console.print("[green]✓[/green] results/all_devices.txt")
    console.print("[green]✓[/green] results/android_and.txt")
    console.print("[green]✓[/green] results/ios.txt")


def split_record_files(records, size=50):
    RESULTS.mkdir(exist_ok=True)
    split_dir = RESULTS / "parts"
    split_dir.mkdir(exist_ok=True)
    for old in split_dir.glob("part_*.txt"):
        old.unlink()
    total_parts = 0
    for start in range(0, len(records), size):
        total_parts += 1
        chunk = records[start:start + size]
        save_numbered_records(split_dir / f"part_{total_parts:03d}.txt", chunk)
    console.print(
        f"[green]✓[/green] {len(records)} record dibagi menjadi "
        f"{total_parts} file di {split_dir}/"
    )


def split_manager_menu():
    while True:
        banner()
        section("◈  SPLIT / DEVICE MANAGER")
        print(
            f"\n  {Fore.CYAN}[1]{Style.RESET_ALL}  SPLIT FULL INFO"
            f"\n  {Fore.CYAN}[2]{Style.RESET_ALL}  SPLIT DEVICE ID"
            f"\n  {Fore.CYAN}[3]{Style.RESET_ALL}  SPLIT DEVICE ID • ANDROID / iOS"
            f"\n  {Fore.CYAN}[4]{Style.RESET_ALL}  DEDUP + EXPORT FULL INFO"
            f"\n  {Fore.LIGHTBLACK_EX}[0]{Style.RESET_ALL}  BACK"
        )
        choice = input(f"\n{Fore.CYAN}Pilih menu [0-4]: {Style.RESET_ALL}").strip()

        if choice == "0":
            return

        if choice not in {"1", "2", "3", "4"}:
            print(f"{Fore.RED}Pilihan tidak valid.{Style.RESET_ALL}")
            pause()
            continue

        filepath = input(
            f"\n{Fore.CYAN}FILE TXT{Style.RESET_ALL}\n"
            f"{Fore.YELLOW}➤ {Style.RESET_ALL}"
        ).strip().strip('"').strip("'")

        try:
            records = load_records(filepath)
        except Exception as e:
            print(f"\n{Fore.RED}Gagal membaca file: {e}{Style.RESET_ALL}")
            pause()
            continue

        clean, duplicates = unique_records_keep_order(records)

        if not clean:
            print(f"\n{Fore.RED}Tidak ada Device ID valid (and_/ios_).{Style.RESET_ALL}")
            pause()
            continue

        try:
            size = int(input(
                f"{Fore.CYAN}Jumlah ID per file [default 50]: {Style.RESET_ALL}"
            ).strip() or "50")
        except ValueError:
            size = 50
        size = max(1, size)

        out_dir = RESULTS / "split"
        out_dir.mkdir(parents=True, exist_ok=True)

        for old in out_dir.glob("*.txt"):
            old.unlink()

        def write_chunks(items, prefix, full_info=False):
            total_parts = 0
            for start_i in range(0, len(items), size):
                total_parts += 1
                chunk = items[start_i:start_i + size]
                path = out_dir / f"{prefix}_{total_parts:03d}.txt"
                with path.open("w", encoding="utf-8") as f:
                    for idx, item in enumerate(chunk, start=1):
                        if full_info:
                            lines = item["text"].splitlines()
                            if lines:
                                f.write(f"{idx}. {lines[0]}\n")
                                for line in lines[1:]:
                                    f.write(line + "\n")
                            f.write("---\n")
                        else:
                            f.write(item + "\n")
            return total_parts

        if choice == "1":
            parts = write_chunks(clean, "full_info", full_info=True)
            print(f"\n{Fore.GREEN}✓ Split FULL INFO selesai: {parts} file{Style.RESET_ALL}")

        elif choice == "2":
            ids = [r["id"] for r in clean]
            parts = write_chunks(ids, "device_id")
            print(f"\n{Fore.GREEN}✓ Split DEVICE ID selesai: {parts} file{Style.RESET_ALL}")

        elif choice == "3":
            ids_and = [r["id"] for r in clean if r["id"].lower().startswith("and_")]
            ids_ios = [r["id"] for r in clean if r["id"].lower().startswith("ios_")]
            parts_and = write_chunks(ids_and, "android_and")
            parts_ios = write_chunks(ids_ios, "ios")
            print(
                f"\n{Fore.GREEN}✓ Android: {len(ids_and)} ID / {parts_and} file"
                f"\n✓ iOS: {len(ids_ios)} ID / {parts_ios} file"
                f"\n✓ Output: {out_dir}{Style.RESET_ALL}"
            )

        elif choice == "4":
            export_all_records(clean)
            print(
                f"\n{Fore.GREEN}✓ Export full info selesai"
                f"\n✓ Total unik: {len(clean)}"
                f"\n✓ Duplikat dihapus: {duplicates}{Style.RESET_ALL}"
            )

        pause()


# ══════════════════════════════════════════════════════════════════════
# FITUR NOMOR 4 — 4 VERIFIKASI LANGKAH (3X SCAN) [PATCHED]
# ══════════════════════════════════════════════════════════════════════
def read_device_ids_from_text_verif(text: str) -> List[str]:
    """
    Baca device ID dari text (TXT atau JSON), dedup, urutkan sesuai kemunculan.
    """
    text = text or ""
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            found: List[str] = []

            def walk_json(o):
                if isinstance(o, str):
                    if DEVICE_RE.fullmatch(o.strip()):
                        found.append(o.strip())
                elif isinstance(o, dict):
                    for v in o.values():
                        walk_json(v)
                elif isinstance(o, list):
                    for v in o:
                        walk_json(v)

            walk_json(data)
            if found:
                seen, out = set(), []
                for d in found:
                    k = d.lower()
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append(d)
                return out
        except Exception:
            pass

    records = extract_records(text)
    clean, _ = unique_records_keep_order(records)
    return [r["id"] for r in clean]


def load_devices_from_file_verif(filepath: str) -> List[str]:
    """
    Baca device ID dari file TXT/JSON dengan batas ukuran 20 MB.
    """
    p = Path(filepath)
    if not p.is_file():
        raise FileNotFoundError(filepath)
    size = p.stat().st_size
    if size > MAX_FILE_SIZE:
        raise ValueError(
            f"Ukuran file {size / 1024 / 1024:.2f} MB melebihi batas maksimal 20 MB"
        )
    with p.open("r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()
    return read_device_ids_from_text_verif(text)


# ─── PATCHED: Retry helpers ──────────────────────────────────────────
def _verif_check_with_retry_valid(device_id: str, max_retry: int = VERIF_RETRY):
    """Retry valid check sampai sukses atau habis retry."""
    for attempt in range(max_retry):
        try:
            data = GameLogin(device_id).run()
            if data and data.get("account_id") and data.get("zone_id"):
                return data
        except Exception:
            pass
        time.sleep(0.4 * (attempt + 1))
    return None


def _verif_check_with_retry_ban(device_id: str, max_retry: int = VERIF_RETRY):
    """Retry ban check sampai dapat CLEAN/BANNED (bukan UNKNOWN)."""
    last_status, last_result = "UNKNOWN", device_id
    for attempt in range(max_retry):
        try:
            status, result = check_device_ban_silent(device_id)
            if status in ("CLEAN", "BANNED"):
                return status, result
            last_status, last_result = status, result
        except Exception:
            pass
        time.sleep(0.4 * (attempt + 1))
    if last_status == "UNKNOWN":
        try:
            verif_logger.warning(f"UNKNOWN after {max_retry}x retry: {device_id}")
        except Exception:
            pass
    return last_status, last_result


def _verif_single_scan(
    devices: List[str],
    scan_no: int,
    threads: int,
) -> Dict[str, dict]:
    """
    SATU siklus scan lengkap: Valid -> Banned.
    Dengan retry otomatis untuk device yang UNKNOWN.
    """
    total = len(devices)
    valid_devs: List[Tuple[str, dict]] = []
    invalid_devs: List[str] = []

    v_lock = threading.Lock()
    done_v = [0]
    last_v = [0.0]

    # ── LANGKAH 1: CEK VALID ──────────────────────────────────────
    def worker_v(d):
        try:
            return d, _verif_check_with_retry_valid(d)
        except Exception:
            return d, None

    def bulk_valid():
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
            futures = {ex.submit(worker_v, d): d for d in devices}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    d, data = fut.result()
                except Exception:
                    d, data = futures[fut], None
                with v_lock:
                    if data and data.get("account_id") and data.get("zone_id"):
                        valid_devs.append((d, data))
                    else:
                        invalid_devs.append(d)
                    done_v[0] += 1

    print()
    print(f"  {Fore.CYAN}╭─ SCAN {scan_no}/3 ─ 🔍 LANGKAH 1 : CEK VALID ─────────────────{Style.RESET_ALL}")
    vf = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    v_future = vf.submit(bulk_valid)
    while not v_future.done():
        now = time.time()
        if now - last_v[0] >= 0.8:
            last_v[0] = now
            done = done_v[0]
            pct = (done / max(total, 1)) * 100
            bw = 22
            fill = int(bw * done / max(total, 1))
            bar = "━" * fill + "─" * (bw - fill)
            sys_out = (
                f"\r  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} "
                f"{Fore.CYAN}{bar}{Style.RESET_ALL} "
                f"{Fore.YELLOW}{pct:5.1f}%{Style.RESET_ALL} "
                f"{Fore.WHITE}{done}/{total}{Style.RESET_ALL} "
                f"{Fore.GREEN}✓ {len(valid_devs)}{Style.RESET_ALL} "
                f"{Fore.RED}✗ {len(invalid_devs)}{Style.RESET_ALL}"
            )
            print(sys_out, end="", flush=True)
        time.sleep(0.2)
    try:
        v_future.result()
    except Exception:
        pass
    vf.shutdown(wait=False)
    print()

    # ── LANGKAH 2: CEK BANNED (dengan retry) ──────────────────────
    ban_map: Dict[str, Tuple[str, str]] = {}
    if valid_devs:
        tb = len(valid_devs)
        b_lock = threading.Lock()
        done_b = [0]
        last_b = [0.0]

        def worker_b(dev):
            try:
                return _verif_check_with_retry_ban(dev)
            except Exception:
                return "UNKNOWN", dev

        def bulk_ban():
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
                futures = {ex.submit(worker_b, d): d for d, _ in valid_devs}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        status, result = fut.result()
                    except Exception:
                        status, result = "UNKNOWN", futures[fut]
                    with b_lock:
                        ban_map[futures[fut]] = (status, result)
                        done_b[0] += 1

        print(f"  {Fore.CYAN}╰─ 🚫 LANGKAH 2 : CEK BANNED ─────────────────────────────────{Style.RESET_ALL}")
        bf = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        b_future = bf.submit(bulk_ban)
        while not b_future.done():
            now = time.time()
            if now - last_b[0] >= 0.8:
                last_b[0] = now
                done = done_b[0]
                pct = (done / max(tb, 1)) * 100
                bw = 22
                fill = int(bw * done / max(tb, 1))
                bar = "━" * fill + "─" * (bw - fill)
                banned_so_far = sum(1 for v in ban_map.values() if v[0] == "BANNED")
                clean_so_far = sum(1 for v in ban_map.values() if v[0] == "CLEAN")
                print(
                    f"\r  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} "
                    f"{Fore.CYAN}{bar}{Style.RESET_ALL} "
                    f"{Fore.YELLOW}{pct:5.1f}%{Style.RESET_ALL} "
                    f"{Fore.WHITE}{done}/{tb}{Style.RESET_ALL} "
                    f"{Fore.RED}🚫 {banned_so_far}{Style.RESET_ALL} "
                    f"{Fore.GREEN}✓ {clean_so_far}{Style.RESET_ALL}",
                    end="", flush=True,
                )
            time.sleep(0.2)
        try:
            b_future.result()
        except Exception:
            pass
        bf.shutdown(wait=False)
        print()

    result: Dict[str, dict] = {}
    for d in devices:
        result[d] = {
            "valid": False,
            "ban_status": None,
            "ban_string": None,
            "data": None,
        }
    for d, data in valid_devs:
        result[d]["valid"] = True
        result[d]["data"] = data
    for d, (st, st_str) in ban_map.items():
        if d in result:
            result[d]["ban_status"] = st
            result[d]["ban_string"] = st_str
    return result


# ─── PATCHED: Voting helper ──────────────────────────────────────────
def _verif_decide_single(s1: dict, s2: dict, s3: dict) -> Tuple[str, Any]:
    """
    Logika voting final.
    Return: (verdict, payload)
      verdict = "CLEAN" | "BANNED" | "INCONSISTENT" | "INVALID"
      payload = data dict (CLEAN), ban_str (BANNED), atau reason (INCONSISTENT)
    """
    v1 = bool(s1.get("valid"))
    v2 = bool(s2.get("valid"))
    v3 = bool(s3.get("valid"))
    b1 = s1.get("ban_status") or "UNKNOWN"
    b2 = s2.get("ban_status") or "UNKNOWN"
    b3 = s3.get("ban_status") or "UNKNOWN"

    if sum([v1, v2, v3]) < 2:
        return "INVALID", None

    clean_votes = [b1, b2, b3].count("CLEAN")
    banned_votes = [b1, b2, b3].count("BANNED")

    if clean_votes >= 2:
        data = s3.get("data") or s2.get("data") or s1.get("data") or {}
        return "CLEAN", data
    if banned_votes >= 2:
        ban_str = s3.get("ban_string") or s2.get("ban_string") or s1.get("ban_string")
        return "BANNED", ban_str
    return "INCONSISTENT", f"scan1={b1}, scan2={b2}, scan3={b3}"


def _verif_format_clean_record(device_id: str, data: dict) -> str:
    pd = (data or {}).get("player_data") or {}
    return (
        f"DEVICE ID  : {device_id}\n"
        f"ACCOUNT ID : {(data or {}).get('account_id', '-')}\n"
        f"ZONE ID    : {(data or {}).get('zone_id', '-')}\n"
        f"NICKNAME   : {pd.get('nickname', '-')}\n"
        f"LEVEL      : {pd.get('level', 0)}\n"
        f"SKIN       : {pd.get('skin_count', 0)}\n"
        f"HERO       : {pd.get('hero_count', 0)}\n"
        f"RANK       : {pd.get('current_rank', '-')}\n"
        f"HIGH RANK  : {pd.get('high_rank', '-')}\n"
        f"{'-' * 58}\n"
    )


def _verif_ban_line(device_id: str, ban_string: Optional[str]) -> str:
    if ban_string:
        return ban_string
    return (
        f"{device_id} |  Reason Name: Using Plug-in Apps to Compromise Competitive Fairness"
        f" |  Duration: Day -, 00:00:00"
    )


def verif_3x_bulk():
    banner()
    section("◈  4 VERIFIKASI LANGKAH — 3X SCAN")
    print()
    print(f"  {Fore.LIGHTBLACK_EX}Fitur ini menjalankan pemeriksaan berlapis:{Style.RESET_ALL}")
    print(f"    {Fore.CYAN}•{Style.RESET_ALL} Scan 1 → 🔍 Cek Valid + 🚫 Cek Banned")
    print(f"    {Fore.CYAN}•{Style.RESET_ALL} Scan 2 → 🔄 Ulangi Cek Valid + Cek Banned")
    print(f"    {Fore.CYAN}•{Style.RESET_ALL} Scan 3 → ✅ Verifikasi akhir (Valid + Banned)")
    print(f"    {Fore.CYAN}•{Style.RESET_ALL} Voting mayoritas (2/3) + auto-retry untuk UNKNOWN")
    print()
    print(f"  {Fore.LIGHTBLACK_EX}Output: 2 file terpisah (Tidak Terbanned & Sudah Terbanned){Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}Format input: {Style.RESET_ALL}{Fore.WHITE}.txt / .json{Style.RESET_ALL}"
          f" {Fore.LIGHTBLACK_EX}(max 20 MB){Style.RESET_ALL}")
    print()

    filepath = input(
        f"  {Fore.CYAN}FILE TXT / JSON{Style.RESET_ALL}\n"
        f"  {Fore.YELLOW}➤ {Style.RESET_ALL}"
    ).strip().strip('"').strip("'")

    if not filepath:
        print(f"\n  {Fore.RED}✖ Tidak ada file yang dipilih.{Style.RESET_ALL}")
        pause()
        return

    if not os.path.exists(filepath):
        print(f"\n  {Fore.RED}✖ File tidak ditemukan: {filepath}{Style.RESET_ALL}")
        pause()
        return

    lower = filepath.lower()
    if not (lower.endswith(".txt") or lower.endswith(".json")):
        print(f"\n  {Fore.RED}✖ File harus berekstensi .txt atau .json{Style.RESET_ALL}")
        pause()
        return

    try:
        fsize = os.path.getsize(filepath)
    except Exception as e:
        print(f"\n  {Fore.RED}✖ Gagal membaca ukuran file: {e}{Style.RESET_ALL}")
        pause()
        return

    if fsize > MAX_FILE_SIZE:
        print(
            f"\n  {Fore.RED}✖ Ukuran file terlalu besar: "
            f"{fsize / 1024 / 1024:.2f} MB (max 20.00 MB){Style.RESET_ALL}"
        )
        pause()
        return

    try:
        devices = load_devices_from_file_verif(filepath)
    except ValueError as e:
        print(f"\n  {Fore.RED}✖ {e}{Style.RESET_ALL}")
        pause()
        return
    except Exception as e:
        print(f"\n  {Fore.RED}✖ Gagal membaca file: {e}{Style.RESET_ALL}")
        pause()
        return

    if not devices:
        print(f"\n  {Fore.RED}✖ Tidak ada Device ID valid (and_/ios_) di dalam file.{Style.RESET_ALL}")
        pause()
        return

    try:
        t_input = input(
            f"\n  {Fore.CYAN}Jumlah threads [{VERIF_THREADS}]: {Style.RESET_ALL}"
        ).strip()
        threads = int(t_input) if t_input else VERIF_THREADS
    except ValueError:
        threads = VERIF_THREADS
    threads = max(1, min(30, threads))

    total = len(devices)
    print()
    print(f"  {Fore.GREEN}✓ File berhasil dibaca{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 📄 File      : {Fore.WHITE}{os.path.basename(filepath)}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 📱 Total ID  : {Fore.CYAN}{total}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 🧵 Threads   : {Fore.CYAN}{threads}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 🔁 Retry     : {Fore.CYAN}{VERIF_RETRY}x per device{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 📦 Max size  : {Fore.CYAN}20 MB{Style.RESET_ALL}")
    print()

    scan_results: List[Dict[str, dict]] = []
    for i in (1, 2, 3):
        header = {
            1: "SCAN 1/3 — 🔍 Pemeriksaan Pertama",
            2: "SCAN 2/3 — 🔄 Pengulangan Kedua",
            3: "SCAN 3/3 — ✅ Pemeriksaan Terakhir",
        }[i]
        print()
        print(f"  {Fore.MAGENTA}{Style.BRIGHT}╔══════════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
        print(f"  {Fore.MAGENTA}{Style.BRIGHT}║{Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}{header:<60}{Style.RESET_ALL} {Fore.MAGENTA}{Style.BRIGHT}║{Style.RESET_ALL}")
        print(f"  {Fore.MAGENTA}{Style.BRIGHT}╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

        res = _verif_single_scan(devices, i, threads)
        scan_results.append(res)

        cnt_valid = sum(1 for d in devices if res[d]["valid"])
        cnt_ban = sum(1 for d in devices if res[d]["ban_status"] == "BANNED")
        cnt_clean = sum(1 for d in devices if res[d]["ban_status"] == "CLEAN")
        cnt_unknown = sum(1 for d in devices if res[d]["ban_status"] == "UNKNOWN")
        print(f"  {Fore.GREEN}✓ SCAN {i}/3 selesai{Style.RESET_ALL}")
        print(f"    {Fore.LIGHTBLACK_EX}•{Style.RESET_ALL} 🔍 Valid   : {Fore.CYAN}{cnt_valid}{Style.RESET_ALL}")
        print(f"    {Fore.LIGHTBLACK_EX}•{Style.RESET_ALL} 🚫 Banned  : {Fore.RED}{cnt_ban}{Style.RESET_ALL}")
        print(f"    {Fore.LIGHTBLACK_EX}•{Style.RESET_ALL} ✅ Clean   : {Fore.GREEN}{cnt_clean}{Style.RESET_ALL}")
        print(f"    {Fore.LIGHTBLACK_EX}•{Style.RESET_ALL} ⚠️  Unknown : {Fore.YELLOW}{cnt_unknown}{Style.RESET_ALL}")

    print()
    print(f"  {Fore.CYAN}📊 Membandingkan hasil 3 scan (voting mayoritas)...{Style.RESET_ALL}")

    file_clean: List[Tuple[str, dict]] = []
    file_banned: List[Tuple[str, str]] = []
    inconsistent: List[Tuple[str, str]] = []
    invalid_final: List[str] = []

    for d in devices:
        s1 = scan_results[0].get(d) or {}
        s2 = scan_results[1].get(d) or {}
        s3 = scan_results[2].get(d) or {}

        verdict, payload = _verif_decide_single(s1, s2, s3)

        if verdict == "CLEAN":
            file_clean.append((d, payload or {}))
        elif verdict == "BANNED":
            file_banned.append((d, _verif_ban_line(d, payload)))
        elif verdict == "INVALID":
            invalid_final.append(d)
        else:
            inconsistent.append((d, payload or "unknown"))

    now = datetime.datetime.now()
    tanggal = now.strftime("%Y-%m-%d")
    waktu = now.strftime("%H-%M-%S")
    ts_full = now.strftime("%Y-%m-%d %H:%M:%S")

    out_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "verif_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    fname1 = f"Device ID Tidak Terbanned {tanggal} {waktu}.txt"
    fname2 = f"Device ID Sudah Terbanned {tanggal} {waktu}.txt"
    path1 = out_dir / fname1
    path2 = out_dir / fname2

    with path1.open("w", encoding="utf-8") as f:
        f.write("═" * 60 + "\n")
        f.write("WEIRDMARKET — DEVICE ID TIDAK TERBANNED\n")
        f.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
        f.write("═" * 60 + "\n")
        f.write(f"Timestamp       : {ts_full}\n")
        f.write(f"Total Input     : {total}\n")
        f.write(f"Verified Clean  : {len(file_clean)}\n")
        f.write(f"Verified Banned : {len(file_banned)}\n")
        f.write(f"Inconsistent    : {len(inconsistent)}\n")
        f.write(f"Invalid Device  : {len(invalid_final)}\n")
        f.write("═" * 60 + "\n\n")
        f.write("┌──────────────────────────────────────────────┐\n")
        f.write("│  ✅ DEVICE ID TIDAK TERBANNED (VERIFIED 3X) │\n")
        f.write("└──────────────────────────────────────────────┘\n")
        for d_id, data in file_clean:
            f.write(_verif_format_clean_record(d_id, data))
        if not file_clean:
            f.write("(Tidak ada device yang terverifikasi clean)\n")

        if inconsistent:
            f.write("\n")
            f.write("┌──────────────────────────────────────────────┐\n")
            f.write("│  ⚠️  INCONSISTENT (TIDAK DIVERIFIKASI)       │\n")
            f.write("└──────────────────────────────────────────────┘\n")
            for d_id, reason in inconsistent:
                f.write(f"{d_id} |  INCONSISTENT  |  {reason}\n")

        if invalid_final:
            f.write("\n")
            f.write("┌──────────────────────────────────────────────┐\n")
            f.write("│  ❌ INVALID DEVICE ID (GAGAL VALID)          │\n")
            f.write("└──────────────────────────────────────────────┘\n")
            for d_id in invalid_final:
                f.write(f"{d_id}\n")

    with path2.open("w", encoding="utf-8") as f:
        f.write("═" * 60 + "\n")
        f.write("WEIRDMARKET — DEVICE ID SUDAH TERBANNED\n")
        f.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
        f.write("═" * 60 + "\n")
        f.write(f"Timestamp       : {ts_full}\n")
        f.write(f"Total Input     : {total}\n")
        f.write(f"Verified Banned : {len(file_banned)}\n")
        f.write("═" * 60 + "\n\n")
        f.write("┌──────────────────────────────────────────────┐\n")
        f.write("│  🚫 DEVICE ID SUDAH TERBANNED (VERIFIED 3X) │\n")
        f.write("└──────────────────────────────────────────────┘\n")
        for _d_id, line in file_banned:
            f.write(line + "\n")
        if not file_banned:
            f.write("(Tidak ada device yang terverifikasi banned)\n")

    print()
    print(f"  {Fore.MAGENTA}{Style.BRIGHT}╔══════════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"  {Fore.MAGENTA}{Style.BRIGHT}║{Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}{'🏁  4 VERIFIKASI LANGKAH — SELESAI':<60}{Style.RESET_ALL} {Fore.MAGENTA}{Style.BRIGHT}║{Style.RESET_ALL}")
    print(f"  {Fore.MAGENTA}{Style.BRIGHT}╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print()
    print(f"  {Fore.LIGHTBLACK_EX}┌─ Ringkasan ────────────────────────────────────────────┐{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 📱 Total Input        : {Fore.CYAN}{total}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} ✅ Verified Clean     : {Fore.GREEN}{len(file_clean)}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} 🚫 Verified Banned    : {Fore.RED}{len(file_banned)}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} ⚠️  Inconsistent      : {Fore.YELLOW}{len(inconsistent)}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}│{Style.RESET_ALL} ❌ Invalid Device     : {Fore.MAGENTA}{len(invalid_final)}{Style.RESET_ALL}")
    print(f"  {Fore.LIGHTBLACK_EX}└────────────────────────────────────────────────────────┘{Style.RESET_ALL}")
    print()
    print(f"  {Fore.LIGHTBLACK_EX}📁 File hasil:{Style.RESET_ALL}")
    print(f"    {Fore.GREEN}✓{Style.RESET_ALL} {path1}")
    print(f"    {Fore.GREEN}✓{Style.RESET_ALL} {path2}")

    footer()
    pause()


def verif_menu():
    while True:
        banner()
        section("◈  4 VERIFIKASI LANGKAH — 3X SCAN")
        print()
        print(f"  {Fore.LIGHTBLACK_EX}Alur verifikasi 3x scan berurutan:{Style.RESET_ALL}")
        print(f"    {Fore.CYAN}🔍 Scan 1{Style.RESET_ALL} → Cek Valid  →  {Fore.RED}🚫{Style.RESET_ALL} Cek Banned")
        print(f"    {Fore.CYAN}🔄 Scan 2{Style.RESET_ALL} → Cek Valid  →  {Fore.RED}🚫{Style.RESET_ALL} Cek Banned")
        print(f"    {Fore.CYAN}✅ Scan 3{Style.RESET_ALL} → Cek Valid  →  {Fore.RED}🚫{Style.RESET_ALL} Cek Banned")
        print()
        print(f"  {Fore.LIGHTBLACK_EX}Voting mayoritas (2/3) + auto-retry UNKNOWN (3x).{Style.RESET_ALL}")
        print()
        print(f"  {Fore.CYAN}[1]{Style.RESET_ALL}  📦 BULK 3X SCAN  {Fore.LIGHTBLACK_EX}(TXT / JSON, max 20 MB){Style.RESET_ALL}")
        print(f"  {Fore.LIGHTBLACK_EX}[0]{Style.RESET_ALL}  BACK")
        choice = input(f"\n{Fore.CYAN}Pilih menu [0-1]: {Style.RESET_ALL}").strip()

        if choice == "1":
            verif_3x_bulk()
        elif choice == "0":
            return
        else:
            print(f"{Fore.RED}Pilihan tidak valid.{Style.RESET_ALL}")
            pause()


# ══════════════════════════════════════════════════════════════════════
# MENU SUB-FITUR
# ══════════════════════════════════════════════════════════════════════
def valid_menu():
    while True:
        banner()
        section("CEK VALID")
        print(
            f"\n  {Fore.CYAN}[1]{Style.RESET_ALL}  SINGLE CHECK"
            f"\n  {Fore.CYAN}[2]{Style.RESET_ALL}  BULK CHECK"
            f"\n  {Fore.LIGHTBLACK_EX}[0]{Style.RESET_ALL}  BACK"
        )
        choice = input(f"\n{Fore.CYAN}Pilih menu [0-2]: {Style.RESET_ALL}").strip()

        if choice == "1":
            valid_single()
        elif choice == "2":
            valid_bulk()
        elif choice == "0":
            return
        else:
            print(f"{Fore.RED}Pilihan tidak valid.{Style.RESET_ALL}")
            pause()


def ban_menu():
    while True:
        banner()
        section("CEK BAN")
        print(
            f"\n  {Fore.CYAN}[1]{Style.RESET_ALL}  SINGLE CHECK"
            f"\n  {Fore.CYAN}[2]{Style.RESET_ALL}  BULK CHECK"
            f"\n  {Fore.LIGHTBLACK_EX}[0]{Style.RESET_ALL}  BACK"
        )
        choice = input(f"\n{Fore.CYAN}Pilih menu [0-2]: {Style.RESET_ALL}").strip()

        if choice == "1":
            ban_single()
        elif choice == "2":
            run_bulk_mode()
            pause()
        elif choice == "0":
            return
        else:
            print(f"{Fore.RED}Pilihan tidak valid.{Style.RESET_ALL}")
            pause()


# ══════════════════════════════════════════════════════════════════════
# MAIN MENU
# ══════════════════════════════════════════════════════════════════════
def main_menu():
    while True:
        banner()
        section("MAIN MENU")
        print(
            f"\n  {Fore.YELLOW}{Style.BRIGHT}[1]{Style.RESET_ALL}  {TITLE}CEK VALID{Style.RESET_ALL}"
            f"   {MUTED}Single & Bulk Device ID validation{Style.RESET_ALL}\n"
            f"  {Fore.YELLOW}{Style.BRIGHT}[2]{Style.RESET_ALL}  {TITLE}CEK BAN{Style.RESET_ALL}"
            f"     {MUTED}Single & Bulk ban status checking{Style.RESET_ALL}\n"
            f"  {Fore.YELLOW}{Style.BRIGHT}[3]{Style.RESET_ALL}  {TITLE}SPLIT / DEVICE MANAGER{Style.RESET_ALL}"
            f" {MUTED}Full info, Device ID, Android & iOS{Style.RESET_ALL}\n"
            f"  {Fore.MAGENTA}{Style.BRIGHT}[4]{Style.RESET_ALL}  {TITLE}4 VERIFIKASI LANGKAH — 3X SCAN{Style.RESET_ALL}"
            f" {MUTED}Valid + Banned · voting mayoritas{Style.RESET_ALL}\n"
            f"  {Fore.RED}{Style.BRIGHT}[0]{Style.RESET_ALL}  {TITLE}KELUAR{Style.RESET_ALL}"
        )
        footer()
        choice = input(
            f"\n{Fore.CYAN}{Style.BRIGHT}WEIRD TOOLS {Style.RESET_ALL}"
            f"{MUTED}› {Style.RESET_ALL}Pilih menu [0-4]: "
        ).strip()

        if choice == "1":
            valid_menu()
        elif choice == "2":
            ban_menu()
        elif choice == "3":
            split_manager_menu()
        elif choice == "4":
            verif_menu()
        elif choice == "0":
            clear_screen()
            print()
            print(f"{Fore.MAGENTA}╭{'═' * (UI_WIDTH - 2)}╮{Style.RESET_ALL}")
            center("WEIRD TOOLS", Fore.CYAN, True)
            center("Program selesai. Terima kasih.", Fore.LIGHTBLACK_EX)
            print(f"{Fore.MAGENTA}╰{'═' * (UI_WIDTH - 2)}╯{Style.RESET_ALL}")
            break
        else:
            print(f"{Fore.RED}Pilihan tidak valid. Gunakan 0, 1, 2, 3, atau 4.{Style.RESET_ALL}")
            pause()


# ══════════════════════════════════════════════════════════════════════
# TELEGRAM BOT INTEGRATION
# ══════════════════════════════════════════════════════════════════════
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN = "8867228317:AAFBS1ke3wGF8BHOuvE9D3nJysdTAjn-SMA"
OWNER_ID = 7601958159

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
for _l in ("httpx", "telegram", "telegram.ext"):
    logging.getLogger(_l).setLevel(logging.WARNING)

BOT_USER_STATE: Dict[int, dict] = {}


def bot_get_state(uid: int) -> dict:
    if uid not in BOT_USER_STATE:
        BOT_USER_STATE[uid] = {
            "awaiting": None,
            "split_mode": None,
            "split_size": 50,
        }
    return BOT_USER_STATE[uid]


def bot_is_owner(uid: int) -> bool:
    return uid == OWNER_ID


def bot_main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CEK VALID", callback_data="menu_valid"),
         InlineKeyboardButton("🚫 CEK BAN", callback_data="menu_ban")],
        [InlineKeyboardButton("⚡ 4 VERIFIKASI LANGKAH — 3X SCAN", callback_data="menu_verif")],
        [InlineKeyboardButton("✂️ SPLIT / DEVICE MANAGER", callback_data="menu_split")],
    ])


def bot_valid_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 SINGLE", callback_data="valid_single"),
         InlineKeyboardButton("📦 BULK", callback_data="valid_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def bot_ban_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 SINGLE", callback_data="ban_single"),
         InlineKeyboardButton("📦 BULK", callback_data="ban_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def bot_verif_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 BULK 3X SCAN (TXT / JSON)", callback_data="verif_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def bot_split_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 SPLIT FULL INFO", callback_data="split_full")],
        [InlineKeyboardButton("🆔 SPLIT DEVICE ID", callback_data="split_devid")],
        [InlineKeyboardButton("🤖 SPLIT ANDROID / iOS", callback_data="split_plat")],
        [InlineKeyboardButton("🗑️ DEDUP + EXPORT FULL INFO", callback_data="split_dedup")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def bot_back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")]
    ])


def bot_cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="menu_main")]
    ])


def bot_chat_id(update: Update):
    if update.callback_query:
        return update.callback_query.message.chat_id
    return update.message.chat_id


async def bot_edit_or_send(update, context, text, kb=None, parse_mode="Markdown"):
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text, parse_mode=parse_mode, reply_markup=kb)
            return update.callback_query.message
        except Exception:
            try:
                return await context.bot.send_message(
                    chat_id=bot_chat_id(update), text=text,
                    parse_mode=parse_mode, reply_markup=kb)
            except Exception:
                return None
    else:
        try:
            return await update.message.reply_text(
                text, parse_mode=parse_mode, reply_markup=kb)
        except Exception:
            return None


def _bot_run_valid_single(device_id: str):
    try:
        return GameLogin(device_id).run()
    except Exception:
        return None


def _bot_run_ban_single(device_id: str):
    try:
        return check_device_ban_silent(device_id)
    except Exception:
        return "UNKNOWN", device_id


async def bot_cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not bot_is_owner(u.id):
        await update.message.reply_text("❌ Bot private.")
        return
    text = (
        "🌟 *WEIRDMARKET TELEGRAM BOT* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Halo *{u.first_name}*! 👋\n\n"
        "Pilih menu di bawah ini:\n\n"
        "  ✅ *CEK VALID* — Single & Bulk\n"
        "  🚫 *CEK BAN* — Single & Bulk\n"
        "  ⚡ *4 VERIFIKASI LANGKAH* — 3X SCAN\n"
        "  ✂️ *SPLIT / DEVICE MANAGER*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_WEIRDMARKET • OFFICIAL TOOLS_"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=bot_main_menu_kb())


async def bot_cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = None
    st["split_mode"] = None
    await update.message.reply_text(
        "❌ Dibatalkan.", reply_markup=bot_back_kb())


async def bot_button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not bot_is_owner(q.from_user.id):
        return
    data = q.data

    if data == "menu_main":
        await bot_show_main(update, context)
    elif data == "menu_valid":
        await bot_show_valid(update, context)
    elif data == "menu_ban":
        await bot_show_ban(update, context)
    elif data == "menu_verif":
        await bot_show_verif(update, context)
    elif data == "menu_split":
        await bot_show_split(update, context)
    elif data == "valid_single":
        await bot_show_valid_single(update, context)
    elif data == "valid_bulk":
        await bot_show_valid_bulk(update, context)
    elif data == "ban_single":
        await bot_show_ban_single(update, context)
    elif data == "ban_bulk":
        await bot_show_ban_bulk(update, context)
    elif data == "verif_bulk":
        await bot_show_verif_bulk(update, context)
    elif data in ("split_full", "split_devid", "split_plat", "split_dedup"):
        await bot_show_split_input(update, context, data)


async def bot_show_main(update, context):
    text = (
        "🌟 *WEIRDMARKET TELEGRAM BOT* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Pilih menu:\n\n"
        "  ✅ *CEK VALID* — Single & Bulk\n"
        "  🚫 *CEK BAN* — Single & Bulk\n"
        "  ⚡ *4 VERIFIKASI LANGKAH* — 3X SCAN\n"
        "  ✂️ *SPLIT* / DEVICE MANAGER\n"
    )
    await bot_edit_or_send(update, context, text, kb=bot_main_menu_kb())


async def bot_show_valid(update, context):
    await bot_edit_or_send(
        update, context,
        "✅ *CEK VALID*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Logic: login server → game server → role info\n\n"
        "Pilih mode:",
        kb=bot_valid_menu_kb())


async def bot_show_ban(update, context):
    await bot_edit_or_send(
        update, context,
        "🚫 *CEK BAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Cek status ban akun MLBB.\n\n"
        "Pilih mode:",
        kb=bot_ban_menu_kb())


async def bot_show_verif(update, context):
    await bot_edit_or_send(
        update, context,
        "⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Fitur ini menjalankan pemeriksaan berlapis untuk\n"
        "memastikan device ID benar-benar *valid* dan *tidak terbanned*.\n\n"
        "🔄 *Alur Verifikasi:*\n"
        "  🔍 Scan 1 → Cek Valid ✅ + Cek Banned 🚫\n"
        "  🔄 Scan 2 → Ulangi Cek Valid ✅ + Cek Banned 🚫\n"
        "  ✅ Scan 3 → Verifikasi akhir ✅ + 🚫\n\n"
        "📊 *Voting Mayoritas (2/3) + Auto Retry UNKNOWN (3x)*\n\n"
        "📁 *Hasil Akhir (2 file terpisah):*\n"
        "  ✅ `Device ID Tidak Terbanned [tanggal] [waktu]`\n"
        "  🚫 `Device ID Sudah Terbanned [tanggal] [waktu]`\n\n"
        "📄 Support file *.txt* / *.json*\n"
        "📦 Max 20 MB\n\n"
        "⚡ Proses otomatis setelah file dikirim.",
        kb=bot_verif_menu_kb())


async def bot_show_split(update, context):
    await bot_edit_or_send(
        update, context,
        "✂️ *SPLIT / DEVICE MANAGER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Upload file *.txt* berisi Device ID.\n\n"
        "Pilih tipe split:",
        kb=bot_split_menu_kb())


async def bot_show_valid_single(update, context):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "valid_single"
    await bot_edit_or_send(
        update, context,
        "✅ *CEK VALID — SINGLE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim *satu Device ID* untuk dicek.",
        kb=bot_cancel_kb())


async def bot_show_valid_bulk(update, context):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "valid_bulk"
    await bot_edit_or_send(
        update, context,
        "✅ *CEK VALID — BULK*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* / *.json* berisi Device ID.\n\n"
        "📦 Max 20 MB\n"
        "⚡ Bot langsung eksekusi otomatis.",
        kb=bot_cancel_kb())


async def bot_show_ban_single(update, context):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "ban_single"
    await bot_edit_or_send(
        update, context,
        "🚫 *CEK BAN — SINGLE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim *satu Device ID* untuk dicek.",
        kb=bot_cancel_kb())


async def bot_show_ban_bulk(update, context):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "ban_bulk"
    await bot_edit_or_send(
        update, context,
        "🚫 *CEK BAN — BULK*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* / *.json* berisi Device ID.\n\n"
        "📦 Max 20 MB\n"
        "⚡ Bot langsung eksekusi otomatis.",
        kb=bot_cancel_kb())


async def bot_show_verif_bulk(update, context):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "verif_bulk"
    await bot_edit_or_send(
        update, context,
        "⚡ *4 VERIFIKASI — BULK 3X SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📂 Kirim file *.txt* atau *.json* berisi Device ID.\n"
        "📦 Max 20 MB\n\n"
        "Bot akan otomatis menjalankan 3 scan berturut-turut:\n"
        "  🔍 Valid → 🚫 Banned → 🔄 ulangi → ✅ verifikasi akhir\n\n"
        "📊 Voting mayoritas (2/3) + auto-retry UNKNOWN.\n\n"
        "⚡ Langsung eksekusi setelah file dikirim.",
        kb=bot_cancel_kb())


async def bot_show_split_input(update, context, mode):
    st = bot_get_state(update.effective_user.id)
    st["awaiting"] = "split"
    st["split_mode"] = mode
    mode_label = {
        "split_full": "📄 SPLIT FULL INFO",
        "split_devid": "🆔 SPLIT DEVICE ID",
        "split_plat": "🤖 SPLIT ANDROID / iOS",
        "split_dedup": "🗑️ DEDUP + EXPORT FULL INFO",
    }.get(mode, "SPLIT")
    await bot_edit_or_send(
        update, context,
        f"✂️ *{mode_label}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* berisi Device ID.\n\n"
        "📦 Ukuran file default: 50 ID per file\n"
        "Ketik angka dulu untuk mengubah (opsional), atau langsung kirim file.",
        kb=bot_cancel_kb())


async def bot_on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not bot_is_owner(u.id):
        return
    st = bot_get_state(u.id)
    text = (update.message.text or "").strip()
    awaiting = st.get("awaiting")

    if awaiting == "valid_single":
        st["awaiting"] = None
        if not text.startswith(("and_", "ios_")):
            await update.message.reply_text(
                "❌ Device ID harus mulai `and_` atau `ios_`",
                parse_mode="Markdown")
            return
        msg = await update.message.reply_text(
            "⏳ *Checking valid...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _bot_run_valid_single, text)
        if not data or not data.get("account_id") or not data.get("zone_id"):
            await msg.edit_text(
                f"❌ *LOGIN / VALIDATION FAILED*\n\n`{text[:60]}`",
                parse_mode="Markdown", reply_markup=bot_back_kb())
            return
        pd = data.get("player_data") or {}
        out = (
            "✅ *VALID HIT*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 *Device:*\n`{text[:60]}`\n\n"
            f"🆔 *Account:* `{data.get('account_id')}`\n"
            f"🌐 *Zone:* `{data.get('zone_id')}`\n"
            f"👤 *Nickname:* {pd.get('nickname', '-')}\n"
            f"📊 *Level:* {pd.get('level', 0)}\n"
            f"🎨 *Skin:* {pd.get('skin_count', 0)}\n"
            f"🦸 *Hero:* {pd.get('hero_count', 0)}\n"
            f"🏆 *Rank:* {pd.get('current_rank', '-')}\n"
            f"⭐ *High Rank:* {pd.get('high_rank', '-')}"
        )
        await msg.edit_text(out, parse_mode="Markdown",
                            reply_markup=bot_back_kb())
        return

    if awaiting == "ban_single":
        st["awaiting"] = None
        if not text.startswith(("and_", "ios_")):
            await update.message.reply_text("❌ Device ID invalid.")
            return
        msg = await update.message.reply_text(
            "⏳ *Checking ban status...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        status, result = await loop.run_in_executor(
            None, _bot_run_ban_single, text)
        if status == "BANNED":
            out = f"🚫 *BANNED*\n\n`{result}`"
        elif status == "CLEAN":
            out = f"✅ *NOT BANNED*\n\n`{result}`"
        else:
            out = f"⚠️ *UNKNOWN / CHECK FAILED*\n\n`{result}`"
        await msg.edit_text(out, parse_mode="Markdown",
                            reply_markup=bot_back_kb())
        return

    if awaiting == "split":
        if text.isdigit():
            st["split_size"] = int(text)
            await update.message.reply_text(
                f"✅ Size: {st['split_size']} ID per file.\nSekarang kirim file *.txt*",
                reply_markup=bot_cancel_kb())
            return


async def bot_on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not bot_is_owner(u.id):
        return
    st = bot_get_state(u.id)
    awaiting = st.get("awaiting")
    doc = update.message.document
    fname = (doc.file_name or "").lower()

    if not (fname.endswith(".txt") or fname.endswith(".json")):
        await update.message.reply_text("⚠️ File harus *.txt* atau *.json*")
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"⚠️ File terlalu besar (max 20 MB).\n"
            f"Ukuran file: {doc.file_size / 1024 / 1024:.2f} MB")
        return

    try:
        f = await doc.get_file()
        raw = await f.download_as_bytearray()
        text = raw.decode("utf-8", errors="ignore")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca file: {e}")
        return

    if awaiting == "valid_bulk":
        st["awaiting"] = None
        devices = read_device_ids_from_text_verif(text)
        if not devices:
            await update.message.reply_text(
                "❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"📦 *BULK VALID CHECK*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `20`\n\n"
            f"⏳ *Memproses...*",
            parse_mode="Markdown")
        asyncio.create_task(bot_bulk_valid(update, context, u.id, devices, msg))
        return

    if awaiting == "ban_bulk":
        st["awaiting"] = None
        devices = read_device_ids_from_text_verif(text)
        if not devices:
            await update.message.reply_text(
                "❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"🚫 *BULK BAN CHECK*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `20`\n\n"
            f"⏳ *Memproses...*",
            parse_mode="Markdown")
        asyncio.create_task(bot_bulk_ban(update, context, u.id, devices, msg))
        return

    if awaiting == "verif_bulk":
        st["awaiting"] = None
        devices = read_device_ids_from_text_verif(text)
        if not devices:
            await update.message.reply_text(
                "❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `{VERIF_THREADS}`\n"
            f"🔁 Retry: `{VERIF_RETRY}x`\n"
            f"📦 Max: `20 MB`\n\n"
            f"🔄 *SCAN 1/3 — Cek Valid...*",
            parse_mode="Markdown")
        asyncio.create_task(
            bot_verif_3x(update, context, u.id, devices, msg))
        return

    if awaiting == "split":
        st["awaiting"] = None
        size = st.pop("split_size", 50)
        mode = st.get("split_mode")
        st["split_mode"] = None
        records = extract_records(text)
        if not records:
            await update.message.reply_text("❌ Tidak ada record valid.")
            return
        clean, duplicates = unique_records_keep_order(records)
        if not clean:
            await update.message.reply_text(
                "❌ Semua record duplikat / tidak valid.")
            return
        msg = await update.message.reply_text(
            "⏳ *Memproses split...*", parse_mode="Markdown")
        await bot_do_split(update, context, clean, duplicates, mode, size, msg)
        return

    devices = read_device_ids_from_text_verif(text)
    if devices:
        await update.message.reply_text(
            f"ℹ️ File terdeteksi berisi `{len(devices)}` Device ID.\n\n"
            f"Pilih menu dulu:\n"
            f"  ✅ CEK VALID → BULK\n"
            f"  🚫 CEK BAN → BULK\n"
            f"  ⚡ 4 VERIFIKASI → BULK\n"
            f"  ✂️ SPLIT",
            parse_mode="Markdown", reply_markup=bot_back_kb())
    else:
        await update.message.reply_text(
            "ℹ️ File diterima, tapi tidak ada Device ID valid.\nPilih menu dulu.",
            reply_markup=bot_back_kb())


async def bot_bulk_valid(update, context, uid, devices, msg):
    cid = msg.chat_id
    total = len(devices)
    loop = asyncio.get_running_loop()

    valid = 0
    fail = 0
    done = 0
    results = []
    lock = threading.Lock()
    last_edit = [0.0]

    def worker(d):
        try:
            return d, _bot_run_valid_single(d)
        except Exception:
            return d, None

    def bulk_run():
        nonlocal valid, fail, done
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(worker, d): d for d in devices}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    d, data = fut.result()
                except Exception:
                    d, data = futures[fut], None
                with lock:
                    if data and data.get("account_id") and data.get("zone_id"):
                        valid += 1
                        results.append((d, data))
                    else:
                        fail += 1
                    done += 1

    future = loop.run_in_executor(None, bulk_run)
    while not future.done():
        now = time.time()
        if now - last_edit[0] >= 2.0:
            last_edit[0] = now
            pct = int(done / max(total, 1) * 100)
            bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
            try:
                await context.bot.edit_message_text(
                    chat_id=cid, message_id=msg.message_id,
                    text=(f"📦 *BULK VALID CHECK*\n"
                          f"━━━━━━━━━━━━━━━━━━━━\n"
                          f"📊 Progress: `{done}/{total}` ({pct}%)\n"
                          f"`{bar}`\n\n"
                          f"✅ Valid  : `{valid}`\n"
                          f"❌ Failed : `{fail}`"),
                    parse_mode="Markdown")
            except Exception:
                pass
        await asyncio.sleep(1.0)
    try:
        await future
    except Exception:
        pass

    buf = io.StringIO()
    buf.write("# WEIRDMARKET — HASIL BULK VALID\n")
    buf.write(f"# Total: {total} | Valid: {valid} | Failed: {fail}\n\n")
    for d, data in results:
        pd = data.get("player_data") or {}
        buf.write(
            f"DEVICE ID  : {d}\n"
            f"ACCOUNT ID : {data.get('account_id')}\n"
            f"ZONE ID    : {data.get('zone_id')}\n"
            f"NICKNAME   : {pd.get('nickname', '-')}\n"
            f"LEVEL      : {pd.get('level', 0)}\n"
            f"SKIN       : {pd.get('skin_count', 0)}\n"
            f"HERO       : {pd.get('hero_count', 0)}\n"
            f"RANK       : {pd.get('current_rank', '-')}\n"
            f"HIGH RANK  : {pd.get('high_rank', '-')}\n"
            f"{'-' * 58}\n"
        )
    out = io.BytesIO(buf.getvalue().encode("utf-8"))
    if valid > 0:
        try:
            await context.bot.send_document(
                chat_id=cid,
                document=InputFile(out, filename="VALID_RESULTS.txt"),
                caption=(f"✅ *BULK VALID SELESAI*\n\n"
                         f"📱 Total  : `{total}`\n"
                         f"✅ Valid  : `{valid}`\n"
                         f"❌ Failed : `{fail}`"),
                parse_mode="Markdown")
        except Exception as e:
            print(f"[BOT BULK VALID] send doc err: {e}")

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *BULK VALID SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total  : `{total}`\n"
                  f"✅ Valid  : `{valid}`\n"
                  f"❌ Failed : `{fail}`"),
            parse_mode="Markdown", reply_markup=bot_back_kb())
    except Exception:
        pass


async def bot_bulk_ban(update, context, uid, devices, msg):
    cid = msg.chat_id
    total = len(devices)
    loop = asyncio.get_running_loop()

    banned = 0
    clean = 0
    unknown = 0
    done = 0
    banned_lines = []
    clean_lines = []
    unknown_lines = []
    lock = threading.Lock()
    last_edit = [0.0]

    def worker(d):
        try:
            return check_device_ban_silent(d)
        except Exception:
            return "UNKNOWN", d

    def bulk_run():
        nonlocal banned, clean, unknown, done
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(worker, d): d for d in devices}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    status, result = fut.result()
                except Exception:
                    status, result = "UNKNOWN", futures[fut]
                with lock:
                    if status == "BANNED":
                        banned += 1
                        banned_lines.append(result)
                    elif status == "CLEAN":
                        clean += 1
                        clean_lines.append(result)
                    else:
                        unknown += 1
                        unknown_lines.append(result)
                    done += 1

    future = loop.run_in_executor(None, bulk_run)
    while not future.done():
        now = time.time()
        if now - last_edit[0] >= 2.0:
            last_edit[0] = now
            pct = int(done / max(total, 1) * 100)
            bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
            try:
                await context.bot.edit_message_text(
                    chat_id=cid, message_id=msg.message_id,
                    text=(f"🚫 *BULK BAN CHECK*\n"
                          f"━━━━━━━━━━━━━━━━━━━━\n"
                          f"📊 Progress: `{done}/{total}` ({pct}%)\n"
                          f"`{bar}`\n\n"
                          f"🚫 Banned  : `{banned}`\n"
                          f"✅ Clean   : `{clean}`\n"
                          f"⚠️ Unknown : `{unknown}`"),
                    parse_mode="Markdown")
            except Exception:
                pass
        await asyncio.sleep(1.0)
    try:
        await future
    except Exception:
        pass

    buf = io.StringIO()
    buf.write("# WEIRDMARKET — HASIL BULK BAN\n")
    buf.write(
        f"# Total: {total} | Banned: {banned} | Clean: {clean} | Unknown: {unknown}\n\n")
    buf.write("═════ BANNED ═════\n")
    for l in banned_lines: buf.write(l + "\n")
    buf.write("\n═════ CLEAN ═════\n")
    for l in clean_lines: buf.write(l + "\n")
    buf.write("\n═════ UNKNOWN ═════\n")
    for l in unknown_lines: buf.write(l + "\n")
    out = io.BytesIO(buf.getvalue().encode("utf-8"))
    if banned + clean + unknown > 0:
        try:
            await context.bot.send_document(
                chat_id=cid,
                document=InputFile(out, filename="BAN_RESULTS.txt"),
                caption=(f"🚫 *BULK BAN SELESAI*\n\n"
                         f"📱 Total  : `{total}`\n"
                         f"🚫 Banned : `{banned}`\n"
                         f"✅ Clean  : `{clean}`\n"
                         f"⚠️ Unknown: `{unknown}`"),
                parse_mode="Markdown")
        except Exception as e:
            print(f"[BOT BULK BAN] send doc err: {e}")

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *BULK BAN SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total  : `{total}`\n"
                  f"🚫 Banned : `{banned}`\n"
                  f"✅ Clean  : `{clean}`\n"
                  f"⚠️ Unknown: `{unknown}`"),
            parse_mode="Markdown", reply_markup=bot_back_kb())
    except Exception:
        pass


async def bot_verif_3x(update, context, uid, devices, msg):
    cid = msg.chat_id
    total = len(devices)
    loop = asyncio.get_running_loop()

    scan_results: List[Dict[str, dict]] = []
    for i in (1, 2, 3):
        header = {
            1: "SCAN 1/3 — 🔍 Pemeriksaan Pertama",
            2: "SCAN 2/3 — 🔄 Pengulangan Kedua",
            3: "SCAN 3/3 — ✅ Pemeriksaan Terakhir",
        }[i]
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                      f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                      f"🔄 *{header}*\n\n"
                      f"📱 Total: `{total}` device\n"
                      f"🧵 Threads: `{VERIF_THREADS}`\n"
                      f"🔁 Retry: `{VERIF_RETRY}x`\n\n"
                      f"⏳ Menjalankan Cek Valid + Cek Banned..."),
                parse_mode="Markdown")
        except Exception:
            pass

        res = await loop.run_in_executor(
            None, _verif_single_scan, devices, i, VERIF_THREADS)
        scan_results.append(res)

        cnt_valid = sum(1 for d in devices if res[d]["valid"])
        cnt_ban = sum(1 for d in devices if res[d]["ban_status"] == "BANNED")
        cnt_clean = sum(1 for d in devices if res[d]["ban_status"] == "CLEAN")
        cnt_unknown = sum(1 for d in devices if res[d]["ban_status"] == "UNKNOWN")

        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                      f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                      f"✅ *{header} SELESAI*\n\n"
                      f"  🔍 Valid   : `{cnt_valid}`\n"
                      f"  🚫 Banned  : `{cnt_ban}`\n"
                      f"  ✅ Clean   : `{cnt_clean}`\n"
                      f"  ⚠️ Unknown : `{cnt_unknown}`"),
                parse_mode="Markdown")
        except Exception:
            pass
        await asyncio.sleep(0.5)

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=("⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                  "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                  "📊 *Membandingkan hasil 3 scan (voting mayoritas)...*"),
            parse_mode="Markdown")
    except Exception:
        pass

    file_clean: List[Tuple[str, dict]] = []
    file_banned: List[Tuple[str, str]] = []
    inconsistent: List[Tuple[str, str]] = []
    invalid_final: List[str] = []

    for d in devices:
        s1 = scan_results[0].get(d) or {}
        s2 = scan_results[1].get(d) or {}
        s3 = scan_results[2].get(d) or {}

        verdict, payload = _verif_decide_single(s1, s2, s3)

        if verdict == "CLEAN":
            file_clean.append((d, payload or {}))
        elif verdict == "BANNED":
            file_banned.append((d, _verif_ban_line(d, payload)))
        elif verdict == "INVALID":
            invalid_final.append(d)
        else:
            inconsistent.append((d, payload or "unknown"))

    now = datetime.datetime.now()
    tanggal = now.strftime("%Y-%m-%d")
    waktu = now.strftime("%H-%M-%S")
    ts_full = now.strftime("%Y-%m-%d %H:%M:%S")

    fname1 = f"Device ID Tidak Terbanned {tanggal} {waktu}.txt"
    fname2 = f"Device ID Sudah Terbanned {tanggal} {waktu}.txt"

    buf1 = io.StringIO()
    buf1.write("═" * 60 + "\n")
    buf1.write("WEIRDMARKET — DEVICE ID TIDAK TERBANNED\n")
    buf1.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
    buf1.write("═" * 60 + "\n")
    buf1.write(f"Timestamp       : {ts_full}\n")
    buf1.write(f"Total Input     : {total}\n")
    buf1.write(f"Verified Clean  : {len(file_clean)}\n")
    buf1.write(f"Verified Banned : {len(file_banned)}\n")
    buf1.write(f"Inconsistent    : {len(inconsistent)}\n")
    buf1.write(f"Invalid Device  : {len(invalid_final)}\n")
    buf1.write("═" * 60 + "\n\n")
    buf1.write("┌──────────────────────────────────────────────┐\n")
    buf1.write("│  ✅ DEVICE ID TIDAK TERBANNED (VERIFIED 3X) │\n")
    buf1.write("└──────────────────────────────────────────────┘\n")
    for d_id, data in file_clean:
        buf1.write(_verif_format_clean_record(d_id, data))
    if not file_clean:
        buf1.write("(Tidak ada device yang terverifikasi clean)\n")
    if inconsistent:
        buf1.write("\n")
        buf1.write("┌──────────────────────────────────────────────┐\n")
        buf1.write("│  ⚠️  INCONSISTENT (TIDAK DIVERIFIKASI)       │\n")
        buf1.write("└──────────────────────────────────────────────┘\n")
        for d_id, reason in inconsistent:
            buf1.write(f"{d_id} |  INCONSISTENT  |  {reason}\n")
    if invalid_final:
        buf1.write("\n")
        buf1.write("┌──────────────────────────────────────────────┐\n")
        buf1.write("│  ❌ INVALID DEVICE ID (GAGAL VALID)          │\n")
        buf1.write("└──────────────────────────────────────────────┘\n")
        for d_id in invalid_final:
            buf1.write(f"{d_id}\n")

    buf2 = io.StringIO()
    buf2.write("═" * 60 + "\n")
    buf2.write("WEIRDMARKET — DEVICE ID SUDAH TERBANNED\n")
    buf2.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
    buf2.write("═" * 60 + "\n")
    buf2.write(f"Timestamp       : {ts_full}\n")
    buf2.write(f"Total Input     : {total}\n")
    buf2.write(f"Verified Banned : {len(file_banned)}\n")
    buf2.write("═" * 60 + "\n\n")
    buf2.write("┌──────────────────────────────────────────────┐\n")
    buf2.write("│  🚫 DEVICE ID SUDAH TERBANNED (VERIFIED 3X) │\n")
    buf2.write("└──────────────────────────────────────────────┘\n")
    for _d_id, line in file_banned:
        buf2.write(line + "\n")
    if not file_banned:
        buf2.write("(Tidak ada device yang terverifikasi banned)\n")

    out1 = io.BytesIO(buf1.getvalue().encode("utf-8"))
    out2 = io.BytesIO(buf2.getvalue().encode("utf-8"))

    try:
        await context.bot.send_document(
            chat_id=cid,
            document=InputFile(out1, filename=fname1),
            caption=(f"✅ *DEVICE ID TIDAK TERBANNED*\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n"
                     f"📅 {ts_full}\n\n"
                     f"📱 Total       : `{total}`\n"
                     f"✅ Verified    : `{len(file_clean)}`\n"
                     f"⚠️ Inconsistent: `{len(inconsistent)}`\n"
                     f"❌ Invalid     : `{len(invalid_final)}`"),
            parse_mode="Markdown")
    except Exception as e:
        print(f"[BOT VERIF3X] send file1 err: {e}")

    try:
        await context.bot.send_document(
            chat_id=cid,
            document=InputFile(out2, filename=fname2),
            caption=(f"🚫 *DEVICE ID SUDAH TERBANNED*\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n"
                     f"📅 {ts_full}\n\n"
                     f"🚫 Verified Banned : `{len(file_banned)}`"),
            parse_mode="Markdown")
    except Exception as e:
        print(f"[BOT VERIF3X] send file2 err: {e}")

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *4 VERIFIKASI LANGKAH SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total        : `{total}`\n"
                  f"✅ Clean (3x)   : `{len(file_clean)}`\n"
                  f"🚫 Banned (3x)  : `{len(file_banned)}`\n"
                  f"⚠️ Inconsistent : `{len(inconsistent)}`\n"
                  f"❌ Invalid      : `{len(invalid_final)}`\n\n"
                  f"📁 File hasil sudah dikirim di atas."),
            parse_mode="Markdown", reply_markup=bot_back_kb())
    except Exception:
        pass


async def bot_do_split(update, context, clean, duplicates, mode, size, msg):
    cid = msg.chat_id
    out_dir = RESULTS / "split_bot"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.txt"):
        try:
            old.unlink()
        except Exception:
            pass

    def write_chunks(items, prefix, full_info=False):
        parts = 0
        for start in range(0, len(items), size):
            parts += 1
            chunk = items[start:start + size]
            path = out_dir / f"{prefix}_{parts:03d}.txt"
            with path.open("w", encoding="utf-8") as f:
                for idx, item in enumerate(chunk, 1):
                    if full_info:
                        lines = item["text"].splitlines()
                        if lines:
                            f.write(f"{idx}. {lines[0]}\n")
                            for line in lines[1:]:
                                f.write(line + "\n")
                        f.write("---\n")
                    else:
                        f.write(item + "\n")
        return parts

    try:
        if mode == "split_full":
            parts = write_chunks(clean, "full_info", full_info=True)
            await msg.edit_text(
                f"✅ *SPLIT FULL INFO*\n\n📄 Total: `{len(clean)}`\n🔢 File: `{parts}`",
                parse_mode="Markdown", reply_markup=bot_back_kb())
        elif mode == "split_devid":
            ids = [r["id"] for r in clean]
            parts = write_chunks(ids, "device_id")
            await msg.edit_text(
                f"✅ *SPLIT DEVICE ID*\n\n📄 Total: `{len(ids)}`\n🔢 File: `{parts}`",
                parse_mode="Markdown", reply_markup=bot_back_kb())
        elif mode == "split_plat":
            ids_and = [r["id"] for r in clean if r["id"].lower().startswith("and_")]
            ids_ios = [r["id"] for r in clean if r["id"].lower().startswith("ios_")]
            parts_and = write_chunks(ids_and, "android_and")
            parts_ios = write_chunks(ids_ios, "ios")
            await msg.edit_text(
                f"✅ *SPLIT ANDROID / iOS*\n\n"
                f"🤖 Android: `{len(ids_and)}` ID / `{parts_and}` file\n"
                f"🍎 iOS: `{len(ids_ios)}` ID / `{parts_ios}` file",
                parse_mode="Markdown", reply_markup=bot_back_kb())
        elif mode == "split_dedup":
            android = [r for r in clean if r["id"].lower().startswith("and_")]
            ios = [r for r in clean if r["id"].lower().startswith("ios_")]

            def save_num(path, recs):
                with path.open("w", encoding="utf-8") as f:
                    for i, record in enumerate(recs, 1):
                        lines = record["text"].splitlines()
                        if lines:
                            f.write(f"{i}. {lines[0]}\n")
                            for line in lines[1:]:
                                f.write(line + "\n")
                        f.write("---\n")

            save_num(out_dir / "all_devices.txt", clean)
            save_num(out_dir / "android_and.txt", android)
            save_num(out_dir / "ios.txt", ios)
            await msg.edit_text(
                f"✅ *DEDUP + EXPORT FULL INFO*\n\n"
                f"📄 Total unik: `{len(clean)}`\n"
                f"🗑️ Duplikat: `{duplicates}`",
                parse_mode="Markdown", reply_markup=bot_back_kb())

        try:
            zip_path = out_dir / "_all_split.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in out_dir.glob("*.txt"):
                    zf.write(fp, arcname=fp.name)
            with open(zip_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=cid,
                    document=InputFile(f, filename="_all_split.zip"),
                    caption=f"📦 *Semua file split* ({len(clean)} record)",
                    parse_mode="Markdown")
        except Exception as e:
            print(f"[BOT SPLIT] zip err: {e}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}", reply_markup=bot_back_kb())


async def bot_post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        me = await app.bot.get_me()
        print(f"🤖 Bot: @{me.username} (id: {me.id})")
    except Exception as e:
        print(f"[BOT POST_INIT] {e}")


def run_telegram_bot():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("❌ Token invalid!")
        return

    print("=" * 60)
    print("🌟 WEIRDMARKET TELEGRAM BOT")
    print("=" * 60)
    print(f"Token   : {BOT_TOKEN[:20]}...")
    print(f"Owner   : {OWNER_ID}")
    print(f"MaxFile : {MAX_FILE_SIZE // 1024 // 1024} MB")
    print(f"Threads : {VERIF_THREADS} | Retry: {VERIF_RETRY}x")
    print("=" * 60)

    app = Application.builder().token(BOT_TOKEN).post_init(bot_post_init).build()

    app.add_handler(CommandHandler("start", bot_cmd_start))
    app.add_handler(CommandHandler("cancel", bot_cmd_cancel))
    app.add_handler(CallbackQueryHandler(bot_button_router))
    app.add_handler(MessageHandler(filters.Document.ALL, bot_on_document))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, bot_on_text))

    print("✅ Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True)


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1].lower() == "cli":
        main_menu()
    else:
        run_telegram_bot()
