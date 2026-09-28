#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEIRDMARKET TELEGRAM BOT — Combined Checker (FULL + FULLCHECK + 4-STEP VERIFY)
Created by: WEIRDMARKET
"""

import socket
import zlib
import zstandard as zstd
import datetime
import struct
import os
import re
import io
import json
import asyncio
import logging
import threading
import time
import zipfile
from pathlib import Path
from enum import Enum
from typing import Any, Tuple, Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from Crypto.Cipher import AES

import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "8824575468:AAGWZRWE41AVnl7n7tbyzp3dah1xbm1cQ-0")
OWNER_ID = int(os.getenv("TG_CHAT_ID", "7601958159"))

DEVICE_RE = re.compile(r"(?i)(?:and_|ios_)[A-Za-z0-9_-]+")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = Path(BASE_DIR) / "results"
os.makedirs(RESULTS, exist_ok=True)

BULK_THREADS = 30
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
FULLCHECK_BATCH_SIZE = 1000

AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV = b'\x00' * 16
CLIENT_VERSION = '2.2.16.1232.1'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
for _l in ("httpx", "telegram", "telegram.ext"):
    logging.getLogger(_l).setLevel(logging.WARNING)


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
                return tag, self._read_number()
            elif data_type == SdpDataType.INTEGER_NEGATIVE:
                return tag, -self._read_number()
            elif data_type == SdpDataType.FLOAT:
                value = self._read_number().to_bytes(4, 'little')
                return tag, struct.unpack("<f", value)[0]
            elif data_type == SdpDataType.DOUBLE:
                value = self._read_number().to_bytes(8, 'little')
                return tag, struct.unpack("<d", value)[0]
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

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(5)
        self.socket.connect((self.host, self.port))

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
            return id, SdpStruct(res)
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
        (0, 4, "Warrior III"), (5, 9, "Warrior II"), (10, 14, "Warrior I"),
        (15, 19, "Elite IV"), (20, 24, "Elite III"), (25, 29, "Elite II"), (30, 34, "Elite I"),
        (35, 39, "Master IV"), (40, 44, "Master III"), (45, 49, "Master II"), (50, 54, "Master I"),
        (55, 59, "Grandmaster IV"), (60, 64, "Grandmaster III"), (65, 69, "Grandmaster II"), (70, 74, "Grandmaster I"),
        (75, 81, "Epic IV"), (82, 88, "Epic III"), (89, 95, "Epic II"), (96, 107, "Epic I"),
        (108, 114, "Legend IV"), (115, 121, "Legend III"), (122, 128, "Legend II"), (129, 135, "Legend I"),
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
# GAME LOGIN
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
        self.client_version = CLIENT_VERSION
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
            0: self.account_id, 1: self.session_key, 2: self.zone_id,
            4: self.client_version, 13: self.channel, 15: self.device_id
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
        try:
            self.connect()
            if not self.login_to_login_server():
                return None
            if not self.get_game_server():
                return None
            if not self.connect_to_game_server():
                return None
            role_info = None
            try:
                role_info = self.get_skin_role_info(self.account_id, self.zone_id)
            except Exception:
                pass
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
            except Exception:
                pass
            return {
                "account_id": self.account_id,
                "zone_id": self.zone_id,
                "session_key": self.session_key,
                "creation_ts": self.creation_ts,
                "game_server": f"{self.game_server_host}:{self.game_server_port}",
                "player_data": pdata,
                "kick": self.kick_detected,
            }
        except Exception:
            return None
        finally:
            self.cleanup()


# ══════════════════════════════════════════════════════════════════════
# BAN CHECKER
# ══════════════════════════════════════════════════════════════════════
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
        self.client_version = CLIENT_VERSION
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
        self.socket.settimeout(5)
        self.socket.connect((self.host, self.port))

    def cleanup(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.sequence = 1
            self.socket = None

    def send_data(self, pkt_id, sdp):
        packet = SdpStruct({0: pkt_id, 1: self.sequence, 5: sdp.data}).data
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
                        details['reason_name'] = BAN_REASONS.get(
                            code_str, "Using Plug-in Apps to Compromise Competitive Fairness")
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


def format_ban_string(device_id, ban_info):
    reason = ban_info.get('reason_name', 'Using Plug-in Apps to Compromise Competitive Fairness')
    day = ban_info.get('endtime_day')
    hour = ban_info.get('endtime_hour', '00')
    minute = ban_info.get('endtime_min', '00')
    sec = ban_info.get('endtime_sec', '00')
    return f"{device_id} |  Reason Name: {reason} |  Duration: Day {day}, {hour}:{minute}:{sec}"


def check_device_ban_silent(device_id):
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


# ══════════════════════════════════════════════════════════════════════
# PARSER
# ══════════════════════════════════════════════════════════════════════
def extract_records(text):
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


def read_device_ids_from_text(text):
    text = text or ""
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            found = []
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


# ══════════════════════════════════════════════════════════════════════
# TELEGRAM BOT
# ══════════════════════════════════════════════════════════════════════
USER_STATE = {}


def get_state(uid):
    if uid not in USER_STATE:
        USER_STATE[uid] = {"bulk_running": False, "bulk_stop": False}
    return USER_STATE[uid]


def is_owner(uid):
    return uid == OWNER_ID


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CEK VALID", callback_data="menu_valid"),
         InlineKeyboardButton("🚫 CEK BAN", callback_data="menu_ban")],
        [InlineKeyboardButton("🔥 FULL CHECK (VALID+BAN)", callback_data="menu_fullcheck")],
        [InlineKeyboardButton("⚡ 4 VERIFIKASI LANGKAH — 3X SCAN", callback_data="menu_verif")],
        [InlineKeyboardButton("✂️ SPLIT / DEVICE MANAGER", callback_data="menu_split")],
    ])


def valid_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 SINGLE", callback_data="valid_single"),
         InlineKeyboardButton("📦 BULK", callback_data="valid_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def ban_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 SINGLE", callback_data="ban_single"),
         InlineKeyboardButton("📦 BULK", callback_data="ban_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def fullcheck_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 BULK FULL CHECK", callback_data="fullcheck_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def verif_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 BULK 3X SCAN (TXT / JSON)", callback_data="verif_bulk")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def split_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 SPLIT FULL INFO", callback_data="split_full")],
        [InlineKeyboardButton("🆔 SPLIT DEVICE ID", callback_data="split_devid")],
        [InlineKeyboardButton("🤖 SPLIT ANDROID / iOS", callback_data="split_plat")],
        [InlineKeyboardButton("🗑️ DEDUP + EXPORT FULL INFO", callback_data="split_dedup")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_main")]
    ])


def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="menu_main")]
    ])


def txt(update):
    if update.callback_query:
        return update.callback_query.message.chat_id
    return update.message.chat_id


async def edit_or_send(update, context, text, kb=None, parse_mode="Markdown"):
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text, parse_mode=parse_mode, reply_markup=kb)
            return update.callback_query.message
        except Exception:
            try:
                return await context.bot.send_message(
                    chat_id=txt(update), text=text,
                    parse_mode=parse_mode, reply_markup=kb)
            except Exception:
                return None
    else:
        try:
            return await update.message.reply_text(
                text, parse_mode=parse_mode, reply_markup=kb)
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────
# COMMANDS
# ──────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_owner(u.id):
        await update.message.reply_text("❌ Bot private.")
        return
    text = (
        "🌟 *WEIRDMARKET TELEGRAM BOT* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Halo *{u.first_name}*! 👋\n\n"
        "Pilih menu di bawah. ✨\n\n"
        "  ✅ CEK VALID — Single & Bulk\n"
        "  🚫 CEK BAN — Single & Bulk\n"
        "  🔥 FULL CHECK — Valid + Ban\n"
        "  ⚡ 4 VERIFIKASI LANGKAH — 3X SCAN\n"
        "  ✂️ SPLIT / DEVICE MANAGER\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_WEIRDMARKET • OFFICIAL TOOLS_"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=main_menu_kb())


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_state(update.effective_user.id)["awaiting"] = None
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=back_kb())
    return ConversationHandler.END


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_owner(q.from_user.id):
        return
    data = q.data

    if data == "menu_main":
        await show_main_menu(update, context)
    elif data == "menu_valid":
        await show_valid_menu(update, context)
    elif data == "menu_ban":
        await show_ban_menu(update, context)
    elif data == "menu_fullcheck":
        await show_fullcheck_menu(update, context)
    elif data == "menu_verif":
        await show_verif_menu(update, context)
    elif data == "menu_split":
        await show_split_menu(update, context)
    elif data == "valid_single":
        await show_valid_single(update, context)
    elif data == "valid_bulk":
        await show_valid_bulk(update, context)
    elif data == "ban_single":
        await show_ban_single(update, context)
    elif data == "ban_bulk":
        await show_ban_bulk(update, context)
    elif data == "fullcheck_bulk":
        await show_fullcheck_bulk(update, context)
    elif data == "verif_bulk":
        await show_verif_bulk(update, context)
    elif data == "split_full":
        await show_split_input(update, context, "split_full")
    elif data == "split_devid":
        await show_split_input(update, context, "split_devid")
    elif data == "split_plat":
        await show_split_input(update, context, "split_plat")
    elif data == "split_dedup":
        await show_split_input(update, context, "split_dedup")


async def show_main_menu(update, context):
    text = (
        "🌟 *WEIRDMARKET TELEGRAM BOT* 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Pilih menu:\n\n"
        "  ✅ *CEK VALID* — Single & Bulk\n"
        "  🚫 *CEK BAN* — Single & Bulk\n"
        "  🔥 *FULL CHECK* — Valid + Ban sekaligus\n"
        "  ⚡ *4 VERIFIKASI LANGKAH* — 3X SCAN\n"
        "  ✂️ *SPLIT* / DEVICE MANAGER\n"
    )
    await edit_or_send(update, context, text, kb=main_menu_kb())


async def show_valid_menu(update, context):
    await edit_or_send(update, context,
        "✅ *CEK VALID*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Logic: login server → game server → role info\n\nPilih mode:",
        kb=valid_menu_kb())


async def show_ban_menu(update, context):
    await edit_or_send(update, context,
        "🚫 *CEK BAN*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Cek status ban akun MLBB.\n\nPilih mode:",
        kb=ban_menu_kb())


async def show_fullcheck_menu(update, context):
    await edit_or_send(update, context,
        "🔥 *FULL CHECK — VALID + BAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bot akan:\n"
        "  1️⃣ Scan valid device ID (login → game → role)\n"
        "  2️⃣ Cek status ban akun yang valid\n"
        "  3️⃣ Hasil dikirim dalam file .txt\n\n"
        "📄 Support file *.txt* / *.json*\n"
        "📦 Max 20 MB\n\n"
        "⚡ Proses otomatis setelah file dikirim.",
        kb=fullcheck_menu_kb())


async def show_verif_menu(update, context):
    await edit_or_send(update, context,
        "⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Fitur ini menjalankan pemeriksaan berlapis untuk memastikan\n"
        "device ID benar-benar *valid* dan *tidak terbanned*.\n\n"
        "🔄 *Alur Verifikasi:*\n"
        "  🔍 Scan 1 → Cek Valid ✅ + Cek Banned 🚫\n"
        "  🔄 Scan 2 → Ulangi Cek Valid ✅ + Cek Banned 🚫\n"
        "  ✅ Scan 3 → Verifikasi akhir ✅ + 🚫\n\n"
        "📊 *Perbandingan Hasil:*\n"
        "Ketiga hasil scan akan dibandingkan per device ID.\n"
        "Device yang *konsisten* di semua scan dianggap terverifikasi.\n"
        "Jika berbeda → ditandai *tidak konsisten*.\n\n"
        "📁 *Hasil Akhir (2 file terpisah):*\n"
        "  ✅ `Device ID Tidak Terbanned [tanggal] [waktu]`\n"
        "  🚫 `Device ID Sudah Terbanned [tanggal] [waktu]`\n\n"
        "📄 Support file *.txt* / *.json*\n"
        "📦 Max 20 MB\n\n"
        "⚡ Proses otomatis setelah file dikirim.",
        kb=verif_menu_kb())


async def show_split_menu(update, context):
    await edit_or_send(update, context,
        "✂️ *SPLIT / DEVICE MANAGER*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Upload file *.txt* berisi Device ID.\n\nPilih tipe split:",
        kb=split_menu_kb())


async def show_valid_single(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "valid_single"
    await edit_or_send(update, context,
        "✅ *CEK VALID — SINGLE*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim *satu Device ID* untuk dicek.",
        kb=cancel_kb())


async def show_valid_bulk(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "valid_bulk_file"
    await edit_or_send(update, context,
        "✅ *CEK VALID — BULK*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* / *.json* berisi Device ID.\n"
        "⚡ Bot langsung eksekusi otomatis.",
        kb=cancel_kb())


async def show_ban_single(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "ban_single"
    await edit_or_send(update, context,
        "🚫 *CEK BAN — SINGLE*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim *satu Device ID* untuk dicek.",
        kb=cancel_kb())


async def show_ban_bulk(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "ban_bulk_file"
    await edit_or_send(update, context,
        "🚫 *CEK BAN — BULK*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* / *.json* berisi Device ID.\n"
        "⚡ Bot langsung eksekusi otomatis.",
        kb=cancel_kb())


async def show_fullcheck_bulk(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "fullcheck_file"
    await edit_or_send(update, context,
        "🔥 *FULL CHECK — BULK*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Kirim file *.txt* / *.json* berisi Device ID.\n"
        "📦 Max 20 MB\n\n"
        "⚡ Bot langsung eksekusi otomatis.",
        kb=cancel_kb())


async def show_verif_bulk(update, context):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "verif_bulk_file"
    await edit_or_send(update, context,
        "⚡ *4 VERIFIKASI — BULK 3X SCAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📂 Kirim file *.txt* atau *.json* berisi Device ID.\n"
        "📦 Max 20 MB\n\n"
        "Bot akan otomatis menjalankan 3 scan berturut-turut:\n"
        "  🔍 Valid → 🚫 Banned → 🔄 ulangi → ✅ verifikasi akhir\n\n"
        "⚡ Langsung eksekusi setelah file dikirim.",
        kb=cancel_kb())


async def show_split_input(update, context, mode):
    s = get_state(update.effective_user.id)
    s["awaiting"] = "split_file"
    s["split_mode"] = mode
    mode_label = {
        "split_full": "📄 SPLIT FULL INFO",
        "split_devid": "🆔 SPLIT DEVICE ID",
        "split_plat": "🤖 SPLIT ANDROID / iOS",
        "split_dedup": "🗑️ DEDUP + EXPORT FULL INFO",
    }.get(mode, "SPLIT")
    await edit_or_send(update, context,
        f"✂️ *{mode_label}*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Kirim file *.txt* berisi Device ID.\n\n"
        f"Ketik angka (size per file), atau langsung kirim file untuk default 50.",
        kb=cancel_kb())


# ──────────────────────────────────────────────────────────────────────
# TEXT HANDLER
# ──────────────────────────────────────────────────────────────────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_owner(u.id):
        return
    s = get_state(u.id)
    text = (update.message.text or "").strip()
    awaiting = s.get("awaiting")

    if awaiting == "valid_single":
        s["awaiting"] = None
        if not text.startswith(("and_", "ios_")):
            await update.message.reply_text("❌ Device ID harus mulai `and_` atau `ios_`",
                                            parse_mode="Markdown")
            return
        msg = await update.message.reply_text("⏳ *Checking...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _run_valid_single, text)
        if not data:
            await msg.edit_text(f"❌ *LOGIN / VALIDATION FAILED*\n\n`{text[:60]}`",
                                parse_mode="Markdown", reply_markup=back_kb())
            return
        pd = data.get("player_data") or {}
        text_out = (
            f"✅ *VALID HIT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
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
        await msg.edit_text(text_out, parse_mode="Markdown", reply_markup=back_kb())
        return

    if awaiting == "ban_single":
        s["awaiting"] = None
        if not text.startswith(("and_", "ios_")):
            await update.message.reply_text("❌ Device ID invalid.")
            return
        msg = await update.message.reply_text("⏳ *Checking ban status...*", parse_mode="Markdown")
        loop = asyncio.get_running_loop()
        status, result = await loop.run_in_executor(None, check_device_ban_silent, text)
        if status == "BANNED":
            out = f"🚫 *BANNED*\n\n`{result}`"
        elif status == "CLEAN":
            out = f"✅ *NOT BANNED*\n\n`{result}`"
        else:
            out = f"⚠️ *UNKNOWN / CHECK FAILED*\n\n`{result}`"
        await msg.edit_text(out, parse_mode="Markdown", reply_markup=back_kb())
        return

    if awaiting == "split_file":
        if text.isdigit():
            s["split_size"] = int(text)
            await update.message.reply_text(
                f"✅ Size: {s['split_size']} ID per file.\nSekarang kirim file *.txt*",
                reply_markup=cancel_kb())
            return


def _run_valid_single(device_id):
    bot = GameLogin(device_id)
    return bot.run()


# ──────────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER
# ──────────────────────────────────────────────────────────────────────
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_owner(u.id):
        return
    s = get_state(u.id)
    awaiting = s.get("awaiting")
    doc = update.message.document
    fname = doc.file_name.lower()

    if not (fname.endswith(".txt") or fname.endswith(".json")):
        await update.message.reply_text("⚠️ File harus *.txt* atau *.json*")
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"⚠️ File terlalu besar (max 20 MB).\nUkuran file: {doc.file_size / 1024 / 1024:.1f} MB")
        return

    f = await doc.get_file()
    raw = await f.download_as_bytearray()
    text = raw.decode("utf-8", errors="ignore")

    if awaiting == "valid_bulk_file":
        s["awaiting"] = None
        devices = read_device_ids_from_text(text)
        if not devices:
            await update.message.reply_text("❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"📦 *BULK VALID CHECK*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `{BULK_THREADS}`\n\n"
            f"⏳ *Memproses...*",
            parse_mode="Markdown")
        asyncio.create_task(run_bulk_valid(update, context, u.id, devices, msg))
        return

    if awaiting == "ban_bulk_file":
        s["awaiting"] = None
        devices = read_device_ids_from_text(text)
        if not devices:
            await update.message.reply_text("❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"🚫 *BULK BAN CHECK*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `{BULK_THREADS}`\n\n"
            f"⏳ *Memproses...*",
            parse_mode="Markdown")
        asyncio.create_task(run_bulk_ban(update, context, u.id, devices, msg))
        return

    if awaiting == "fullcheck_file":
        s["awaiting"] = None
        devices = read_device_ids_from_text(text)
        if not devices:
            await update.message.reply_text("❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"🔥 *FULL CHECK — VALID + BAN*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `{BULK_THREADS}`\n\n"
            f"⏳ *Tahap 1: Scan device valid...*",
            parse_mode="Markdown")
        asyncio.create_task(run_fullcheck(update, context, u.id, devices, msg))
        return

    if awaiting == "verif_bulk_file":
        s["awaiting"] = None
        devices = read_device_ids_from_text(text)
        if not devices:
            await update.message.reply_text("❌ Tidak ada Device ID valid di file.")
            return
        msg = await update.message.reply_text(
            f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 File : `{doc.file_name}`\n"
            f"📱 Total: `{len(devices)}` device\n"
            f"🧵 Threads: `{BULK_THREADS}`\n"
            f"📦 Max: `20 MB`\n\n"
            f"🔄 *SCAN 1/3 — Cek Valid...*",
            parse_mode="Markdown")
        asyncio.create_task(run_verif_3x(update, context, u.id, devices, msg))
        return

    if awaiting == "split_file":
        s["awaiting"] = None
        size = s.pop("split_size", 50)
        mode = s.get("split_mode")
        s["split_mode"] = None
        records = extract_records(text)
        if not records:
            await update.message.reply_text("❌ Tidak ada record valid.")
            return
        clean, duplicates = unique_records_keep_order(records)
        if not clean:
            await update.message.reply_text("❌ Semua record duplikat / tidak valid.")
            return
        msg = await update.message.reply_text("⏳ *Memproses split...*", parse_mode="Markdown")
        await _do_split_async(update, context, clean, duplicates, mode, size, msg)
        return

    devices = read_device_ids_from_text(text)
    if devices:
        await update.message.reply_text(
            f"ℹ️ File terdeteksi berisi `{len(devices)}` Device ID.\n\n"
            f"Pilih menu dulu:\n"
            f"  ✅ CEK VALID → BULK\n"
            f"  🚫 CEK BAN → BULK\n"
            f"  🔥 FULL CHECK → BULK\n"
            f"  ⚡ 4 VERIFIKASI → BULK\n"
            f"  ✂️ SPLIT",
            parse_mode="Markdown", reply_markup=back_kb())
    else:
        await update.message.reply_text(
            "ℹ️ File diterima, tapi tidak ada Device ID valid.\nPilih menu dulu.",
            reply_markup=back_kb())


# ──────────────────────────────────────────────────────────────────────
# SPLIT HANDLER
# ──────────────────────────────────────────────────────────────────────
async def _do_split_async(update, context, clean, duplicates, mode, size, msg):
    cid = txt(update)
    out_dir = RESULTS / "split"
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
        return parts

    try:
        if mode == "split_full":
            parts = write_chunks(clean, "full_info", full_info=True)
            await msg.edit_text(
                f"✅ *SPLIT FULL INFO*\n\n📄 Total: `{len(clean)}`\n🔢 File: `{parts}`",
                parse_mode="Markdown", reply_markup=back_kb())
        elif mode == "split_devid":
            ids = [r["id"] for r in clean]
            parts = write_chunks(ids, "device_id")
            await msg.edit_text(
                f"✅ *SPLIT DEVICE ID*\n\n📄 Total: `{len(ids)}`\n🔢 File: `{parts}`",
                parse_mode="Markdown", reply_markup=back_kb())
        elif mode == "split_plat":
            ids_and = [r["id"] for r in clean if r["id"].lower().startswith("and_")]
            ids_ios = [r["id"] for r in clean if r["id"].lower().startswith("ios_")]
            parts_and = write_chunks(ids_and, "android_and")
            parts_ios = write_chunks(ids_ios, "ios")
            await msg.edit_text(
                f"✅ *SPLIT ANDROID / iOS*\n\n🤖 Android: `{len(ids_and)}` ID / `{parts_and}` file\n"
                f"🍎 iOS: `{len(ids_ios)}` ID / `{parts_ios}` file",
                parse_mode="Markdown", reply_markup=back_kb())
        elif mode == "split_dedup":
            results_dir = RESULTS
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

            save_num(results_dir / "all_devices.txt", clean)
            save_num(results_dir / "android_and.txt", android)
            save_num(results_dir / "ios.txt", ios)

            await msg.edit_text(
                f"✅ *DEDUP + EXPORT FULL INFO*\n\n📄 Total unik: `{len(clean)}`\n"
                f"🗑️ Duplikat: `{duplicates}`",
                parse_mode="Markdown", reply_markup=back_kb())

        try:
            zip_path = out_dir / "_all_split.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in out_dir.glob("*.txt"):
                    zf.write(fp, arcname=fp.name)
            with open(zip_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=cid, document=InputFile(f, filename="_all_split.zip"),
                    caption=f"📦 *Semua file split* ({len(clean)} record)",
                    parse_mode="Markdown")
        except Exception as e:
            print(f"[SPLIT] zip err: {e}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}", reply_markup=back_kb())


# ──────────────────────────────────────────────────────────────────────
# BULK RUNNERS
# ──────────────────────────────────────────────────────────────────────
async def run_bulk_valid(update, context, uid, devices, msg):
    s = get_state(uid)
    cid = txt(update)
    total = len(devices)
    done = 0
    valid = 0
    fail = 0
    last_edit = [0.0]
    loop = asyncio.get_running_loop()
    results = []
    lock = threading.Lock()

    def worker(d):
        try:
            return d, _run_valid_single(d)
        except Exception:
            return d, None

    def bulk_run():
        nonlocal done, valid, fail
        with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
            futures = {ex.submit(worker, d): d for d in devices}
            for fut in as_completed(futures):
                if s.get("bulk_stop"):
                    break
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

    async def update_status():
        now = time.time()
        if now - last_edit[0] < 2.0 and done < total:
            return
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

    bulk_future = loop.run_in_executor(None, bulk_run)
    while not bulk_future.done():
        await update_status()
        await asyncio.sleep(1.0)
    await bulk_future
    await update_status()

    # Kirim file hasil
    buf = io.StringIO()
    buf.write(f"# WEIRDMARKET — HASIL BULK VALID\n")
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
            print(f"[BULK VALID] send doc err: {e}")
            await context.bot.send_message(
                chat_id=cid,
                text=f"✅ *BULK VALID SELESAI*\n\n"
                     f"📱 Total  : `{total}`\n"
                     f"✅ Valid  : `{valid}`\n"
                     f"❌ Failed : `{fail}`\n\n"
                     f"⚠️ File gagal dikirim: {e}",
                parse_mode="Markdown", reply_markup=back_kb())
            return

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *BULK VALID SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total  : `{total}`\n"
                  f"✅ Valid  : `{valid}`\n"
                  f"❌ Failed : `{fail}`"),
            parse_mode="Markdown", reply_markup=back_kb())
    except Exception:
        pass


async def run_bulk_ban(update, context, uid, devices, msg):
    s = get_state(uid)
    cid = txt(update)
    total = len(devices)
    done = 0
    banned = 0
    clean = 0
    unknown = 0
    last_edit = [0.0]
    loop = asyncio.get_running_loop()

    banned_lines = []
    clean_lines = []
    unknown_lines = []
    lock = threading.Lock()

    def worker(d):
        try:
            return check_device_ban_silent(d)
        except Exception:
            return "UNKNOWN", d

    def bulk_run():
        nonlocal done, banned, clean, unknown
        with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
            futures = {ex.submit(worker, d): d for d in devices}
            for fut in as_completed(futures):
                if s.get("bulk_stop"):
                    break
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

    async def update_status():
        now = time.time()
        if now - last_edit[0] < 2.0 and done < total:
            return
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

    bulk_future = loop.run_in_executor(None, bulk_run)
    while not bulk_future.done():
        await update_status()
        await asyncio.sleep(1.0)
    await bulk_future
    await update_status()

    buf = io.StringIO()
    buf.write(f"# WEIRDMARKET — HASIL BULK BAN\n")
    buf.write(f"# Total: {total} | Banned: {banned} | Clean: {clean} | Unknown: {unknown}\n\n")
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
            print(f"[BULK BAN] send doc err: {e}")
            await context.bot.send_message(
                chat_id=cid,
                text=f"🚫 *BULK BAN SELESAI*\n\n"
                     f"📱 Total  : `{total}`\n"
                     f"🚫 Banned : `{banned}`\n"
                     f"✅ Clean  : `{clean}`\n"
                     f"⚠️ Unknown: `{unknown}`\n\n"
                     f"⚠️ File gagal dikirim: {e}",
                parse_mode="Markdown", reply_markup=back_kb())
            return

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *BULK BAN SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total  : `{total}`\n"
                  f"🚫 Banned : `{banned}`\n"
                  f"✅ Clean  : `{clean}`\n"
                  f"⚠️ Unknown: `{unknown}`"),
            parse_mode="Markdown", reply_markup=back_kb())
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# FULL CHECK RUNNER (VALID + BAN)
# ──────────────────────────────────────────────────────────────────────
async def run_fullcheck(update, context, uid, devices, msg):
    s = get_state(uid)
    cid = txt(update)
    total = len(devices)
    loop = asyncio.get_running_loop()

    final_clean: List[Tuple[str, dict]] = []
    final_banned: List[str] = []
    final_unknown_ban: List[str] = []
    valid_fail_count = 0
    valid_total = 0
    done_valid = 0
    last_edit = [0.0]

    lock_valid = threading.Lock()
    lock_ban = threading.Lock()
    valid_buffer: List[Tuple[str, dict]] = []
    valid_buffer_lock = threading.Lock()

    async def flush_ban_buffer(buffer_snapshot: List[Tuple[str, dict]]):
        if not buffer_snapshot:
            return
        nonlocal valid_total
        total_buf = len(buffer_snapshot)
        done_ban = 0
        banned_cnt = 0
        clean_cnt = 0
        unknown_cnt = 0
        last_ban_edit = [0.0]

        def worker_ban(dev):
            try:
                return check_device_ban_silent(dev)
            except Exception:
                return "UNKNOWN", dev

        def bulk_ban_run():
            nonlocal done_ban, banned_cnt, clean_cnt, unknown_cnt
            with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
                futures = {ex.submit(worker_ban, d): d for d, _ in buffer_snapshot}
                for fut in as_completed(futures):
                    if s.get("bulk_stop"):
                        break
                    try:
                        status, result = fut.result()
                    except Exception:
                        status, result = "UNKNOWN", futures[fut]
                    with lock_ban:
                        if status == "BANNED":
                            banned_cnt += 1
                            final_banned.append(result)
                        elif status == "CLEAN":
                            clean_cnt += 1
                            for d_id, data in buffer_snapshot:
                                if d_id == result:
                                    final_clean.append((d_id, data))
                                    break
                        else:
                            unknown_cnt += 1
                            final_unknown_ban.append(result)
                        done_ban += 1

        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"🔥 *FULL CHECK — TAHAP 2/2 (BAN)*\n"
                      f"━━━━━━━━━━━━━━━━━━━━\n"
                      f"✅ Valid ditemukan: `{valid_total}`\n"
                      f"🧪 Batch size    : `{total_buf}`\n"
                      f"⏳ *Memproses cek ban...*"),
                parse_mode="Markdown")
        except Exception:
            pass

        ban_future = loop.run_in_executor(None, bulk_ban_run)
        while not ban_future.done():
            now = time.time()
            if now - last_ban_edit[0] >= 2.0:
                last_ban_edit[0] = now
                pct = int(done_ban / max(total_buf, 1) * 100)
                bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
                try:
                    await context.bot.edit_message_text(
                        chat_id=cid, message_id=msg.message_id,
                        text=(f"🔥 *FULL CHECK — TAHAP 2/2 (BAN)*\n"
                              f"━━━━━━━━━━━━━━━━━━━━\n"
                              f"📊 Batch: `{done_ban}/{total_buf}` ({pct}%)\n"
                              f"`{bar}`\n\n"
                              f"🚫 Banned  : `{banned_cnt}`\n"
                              f"✅ Clean   : `{clean_cnt}`\n"
                              f"⚠️ Unknown : `{unknown_cnt}`"),
                        parse_mode="Markdown")
                except Exception:
                    pass
            await asyncio.sleep(1.0)
        await ban_future

    def worker_valid(d):
        try:
            return d, _run_valid_single(d)
        except Exception:
            return d, None

    def bulk_valid_run():
        nonlocal done_valid, valid_total, valid_fail_count
        with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
            futures = {ex.submit(worker_valid, d): d for d in devices}
            for fut in as_completed(futures):
                if s.get("bulk_stop"):
                    break
                try:
                    d, data = fut.result()
                except Exception:
                    d, data = futures[fut], None
                with lock_valid:
                    if data and data.get("account_id") and data.get("zone_id"):
                        valid_total += 1
                        valid_buffer.append((d, data))
                    else:
                        valid_fail_count += 1
                    done_valid += 1

    async def update_status_valid():
        now = time.time()
        if now - last_edit[0] < 2.0 and done_valid < total:
            return
        last_edit[0] = now
        pct = int(done_valid / max(total, 1) * 100)
        bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"🔥 *FULL CHECK — TAHAP 1/2 (VALID)*\n"
                      f"━━━━━━━━━━━━━━━━━━━━\n"
                      f"📊 Progress: `{done_valid}/{total}` ({pct}%)\n"
                      f"`{bar}`\n\n"
                      f"✅ Valid  : `{valid_total}`\n"
                      f"❌ Failed : `{valid_fail_count}`\n"
                      f"📥 Buffer : `{len(valid_buffer)}/{FULLCHECK_BATCH_SIZE}`"),
                parse_mode="Markdown")
        except Exception:
            pass

    valid_future = loop.run_in_executor(None, bulk_valid_run)

    while True:
        if valid_future.done():
            break
        await update_status_valid()
        snapshot = None
        with valid_buffer_lock:
            if len(valid_buffer) >= FULLCHECK_BATCH_SIZE:
                snapshot = valid_buffer[:FULLCHECK_BATCH_SIZE]
                del valid_buffer[:FULLCHECK_BATCH_SIZE]
        if snapshot:
            await flush_ban_buffer(snapshot)
        await asyncio.sleep(1.0)

    try:
        await valid_future
    except Exception:
        pass

    remaining = []
    with valid_buffer_lock:
        remaining = list(valid_buffer)
        valid_buffer.clear()

    if remaining:
        await flush_ban_buffer(remaining)

    await update_status_valid()

    total_clean = len(final_clean)
    total_banned = len(final_banned)
    total_unknown = len(final_unknown_ban)

    buf = io.StringIO()
    buf.write("═" * 60 + "\n")
    buf.write("WEIRDMARKET — FULL CHECK (VALID + BAN)\n")
    buf.write("═" * 60 + "\n")
    buf.write(f"Total Input     : {total}\n")
    buf.write(f"Valid Device    : {valid_total}\n")
    buf.write(f"Invalid Device  : {valid_fail_count}\n")
    buf.write(f"Banned          : {total_banned}\n")
    buf.write(f"Clean (Not Ban) : {total_clean}\n")
    buf.write(f"Unknown         : {total_unknown}\n")
    buf.write("═" * 60 + "\n\n")

    buf.write("┌──────────────────────────────────────────────┐\n")
    buf.write("│  🚫 BANNED ACCOUNTS                          │\n")
    buf.write("└──────────────────────────────────────────────┘\n")
    for l in final_banned:
        buf.write(l + "\n")
    buf.write("\n")

    buf.write("┌──────────────────────────────────────────────┐\n")
    buf.write("│  ✅ CLEAN ACCOUNTS (FINAL RESULT)            │\n")
    buf.write("└──────────────────────────────────────────────┘\n")
    for d_id, data in final_clean:
        pd = data.get("player_data") or {}
        buf.write(
            f"DEVICE ID  : {d_id}\n"
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
    buf.write("\n")

    buf.write("┌──────────────────────────────────────────────┐\n")
    buf.write("│  ⚠️ UNKNOWN ACCOUNTS                         │\n")
    buf.write("└──────────────────────────────────────────────┘\n")
    for l in final_unknown_ban:
        buf.write(l + "\n")
    buf.write("\n")

    out = io.BytesIO(buf.getvalue().encode("utf-8"))
    try:
        await context.bot.send_document(
            chat_id=cid,
            document=InputFile(out, filename="FULL_CHECK_RESULTS.txt"),
            caption=(f"🔥 *FULL CHECK SELESAI*\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n"
                     f"📱 Total  : `{total}`\n"
                     f"✅ Valid  : `{valid_total}`\n"
                     f"🚫 Banned : `{total_banned}`\n"
                     f"✅ Clean  : `{total_clean}`\n"
                     f"⚠️ Unknown: `{total_unknown}`"),
            parse_mode="Markdown")
    except Exception as e:
        print(f"[FULLCHECK] send doc err: {e}")
        await context.bot.send_message(
            chat_id=cid,
            text=f"🔥 *FULL CHECK SELESAI*\n\n"
                 f"📱 Total  : `{total}`\n"
                 f"✅ Valid  : `{valid_total}`\n"
                 f"🚫 Banned : `{total_banned}`\n"
                 f"✅ Clean  : `{total_clean}`\n"
                 f"⚠️ Unknown: `{total_unknown}`\n\n"
                 f"⚠️ File gagal dikirim: {e}",
            parse_mode="Markdown", reply_markup=back_kb())
        return

    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"🏁 *FULL CHECK SELESAI*\n"
                  f"━━━━━━━━━━━━━━━━━━━━\n"
                  f"📱 Total  : `{total}`\n"
                  f"✅ Valid  : `{valid_total}`\n"
                  f"🚫 Banned : `{total_banned}`\n"
                  f"✅ Clean  : `{total_clean}`\n"
                  f"⚠️ Unknown: `{total_unknown}`"),
            parse_mode="Markdown", reply_markup=back_kb())
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# FITUR NOMOR 4 — 4 VERIFIKASI LANGKAH (3X SCAN)
# ══════════════════════════════════════════════════════════════════════
async def _verif_single_scan(context, cid, msg_id, scan_no, devices, s, loop, total):
    """
    Jalankan satu siklus scan lengkap (Valid -> Banned).
    Return: dict { device_id: {"valid": bool, "ban_status": "BANNED"/"CLEAN"/"UNKNOWN"/None,
                              "ban_string": str/None, "data": dict/None} }
    Menggunakan mekanisme ASLI dari fitur Cek Valid Single & Cek Banned Single.
    """
    valid_devs: List[Tuple[str, dict]] = []
    invalid_devs: List[str] = []
    done_v = [0]
    last_v = [0.0]
    v_lock = threading.Lock()

    # ---------- Langkah 1: Valid ----------
    def worker_v(d):
        try:
            return d, _run_valid_single(d)
        except Exception:
            return d, None

    def bulk_valid():
        with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
            futures = {ex.submit(worker_v, d): d for d in devices}
            for fut in as_completed(futures):
                if s.get("bulk_stop"):
                    break
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

    vf = loop.run_in_executor(None, bulk_valid)
    while not vf.done():
        now = time.time()
        if now - last_v[0] >= 2.0:
            last_v[0] = now
            pct = int(done_v[0] / max(total, 1) * 100)
            bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
            try:
                await context.bot.edit_message_text(
                    chat_id=cid, message_id=msg_id,
                    text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                          f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                          f"🔄 *SCAN {scan_no}/3* — 🔍 Langkah 1: Cek Valid\n"
                          f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                          f"📊 Progress: `{done_v[0]}/{total}` ({pct}%)\n"
                          f"`{bar}`\n\n"
                          f"✅ Valid  : `{len(valid_devs)}`\n"
                          f"❌ Failed : `{len(invalid_devs)}`"),
                    parse_mode="Markdown")
            except Exception:
                pass
        await asyncio.sleep(1.0)
    try:
        await vf
    except Exception:
        pass

    # ---------- Langkah 2: Banned (hanya untuk valid) ----------
    ban_map: Dict[str, Tuple[str, str]] = {}
    if valid_devs:
        done_b = [0]
        last_b = [0.0]
        tb = len(valid_devs)
        b_lock = threading.Lock()

        def worker_b(dev):
            try:
                return check_device_ban_silent(dev)
            except Exception:
                return "UNKNOWN", dev

        def bulk_ban():
            with ThreadPoolExecutor(max_workers=BULK_THREADS) as ex:
                futures = {ex.submit(worker_b, d): d for d, _ in valid_devs}
                for fut in as_completed(futures):
                    if s.get("bulk_stop"):
                        break
                    try:
                        status, result = fut.result()
                    except Exception:
                        status, result = "UNKNOWN", futures[fut]
                    with b_lock:
                        ban_map[futures[fut]] = (status, result)
                        done_b[0] += 1

        bf = loop.run_in_executor(None, bulk_ban)
        while not bf.done():
            now = time.time()
            if now - last_b[0] >= 2.0:
                last_b[0] = now
                pct = int(done_b[0] / max(tb, 1) * 100)
                bar = "▰" * int(pct / 10) + "▱" * (10 - int(pct / 10))
                try:
                    await context.bot.edit_message_text(
                        chat_id=cid, message_id=msg_id,
                        text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                              f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                              f"🔄 *SCAN {scan_no}/3* — 🚫 Langkah 2: Cek Banned\n"
                              f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                              f"📊 Progress: `{done_b[0]}/{tb}` ({pct}%)\n"
                              f"`{bar}`"),
                        parse_mode="Markdown")
                except Exception:
                    pass
            await asyncio.sleep(1.0)
        try:
            await bf
        except Exception:
            pass

    # ---------- Build result map ----------
    result: Dict[str, dict] = {}
    for d in devices:
        result[d] = {"valid": False, "ban_status": None, "ban_string": None, "data": None}
    for d, data in valid_devs:
        result[d]["valid"] = True
        result[d]["data"] = data
    for d, (st, st_str) in ban_map.items():
        if d in result:
            result[d]["ban_status"] = st
            result[d]["ban_string"] = st_str
    return result


async def run_verif_3x(update, context, uid, devices, msg):
    """
    Fitur Nomor 4 — 4 Verifikasi Langkah (3X Scan).
    Scan 1, Scan 2, Scan 3 masing-masing menjalankan Cek Valid + Cek Banned.
    Hasil dibandingkan, device dengan status konsisten dimasukkan ke file final.
    """
    s = get_state(uid)
    cid = txt(update)
    total = len(devices)
    loop = asyncio.get_running_loop()

    # ===== JALANKAN 3 SCAN =====
    scan_results: List[Dict[str, dict]] = []
    for i in (1, 2, 3):
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                      f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                      f"🔄 *Memulai SCAN {i}/3...*\n\n"
                      f"📱 Total device: `{total}`\n"
                      f"🧵 Threads     : `{BULK_THREADS}`"),
                parse_mode="Markdown")
        except Exception:
            pass
        res = await _verif_single_scan(context, cid, msg.message_id, i, devices, s, loop, total)
        scan_results.append(res)

        # Info selesai scan
        cnt_valid = sum(1 for d in devices if res[d]["valid"])
        cnt_ban = sum(1 for d in devices if res[d]["ban_status"] == "BANNED")
        cnt_clean = sum(1 for d in devices if res[d]["ban_status"] == "CLEAN")
        try:
            await context.bot.edit_message_text(
                chat_id=cid, message_id=msg.message_id,
                text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                      f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                      f"✅ *SCAN {i}/3 SELESAI*\n\n"
                      f"  🔍 Valid   : `{cnt_valid}`\n"
                      f"  🚫 Banned  : `{cnt_ban}`\n"
                      f"  ✅ Clean   : `{cnt_clean}`\n"),
                parse_mode="Markdown")
        except Exception:
            pass
        await asyncio.sleep(0.5)

    # ===== BANDINGKAN HASIL =====
    try:
        await context.bot.edit_message_text(
            chat_id=cid, message_id=msg.message_id,
            text=(f"⚡ *4 VERIFIKASI LANGKAH — 3X SCAN*\n"
                  f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                  f"📊 *Membandingkan hasil 3 scan...*"),
            parse_mode="Markdown")
    except Exception:
        pass

    file_clean: List[Tuple[str, dict]] = []   # (device_id, data)
    file_banned: List[str] = []                # ban string final
    inconsistent: List[Tuple[str, str]] = []   # (device_id, reason)
    invalid_final: List[str] = []

    for d in devices:
        s1 = scan_results[0].get(d) or {}
        s2 = scan_results[1].get(d) or {}
        s3 = scan_results[2].get(d) or {}

        v1 = bool(s1.get("valid")); v2 = bool(s2.get("valid")); v3 = bool(s3.get("valid"))
        b1 = s1.get("ban_status"); b2 = s2.get("ban_status"); b3 = s3.get("ban_status")

        # Wajib valid di semua 3 scan
        if not (v1 and v2 and v3):
            invalid_final.append(d)
            continue

        statuses = [b1, b2, b3]

        if all(x == "CLEAN" for x in statuses):
            data = s3.get("data") or s2.get("data") or s1.get("data") or {}
            file_clean.append((d, data))
        elif all(x == "BANNED" for x in statuses):
            # Ambil ban string dari scan 3 (terbaru & terverifikasi)
            bs = s3.get("ban_string") or s2.get("ban_string") or s1.get("ban_string")
            if not bs:
                bs = f"{d} |  Reason Name: Using Plug-in Apps to Compromise Competitive Fairness |  Duration: Day -, 00:00:00"
            file_banned.append(bs)
        else:
            # Cek apakah ada UNKNOWN -> tetap konsisten kalau UNKNOWN di semua
            if all(x == "UNKNOWN" for x in statuses):
                inconsistent.append((d, f"scan1={b1}, scan2={b2}, scan3={b3}"))
            else:
                inconsistent.append((d, f"scan1={b1}, scan2={b2}, scan3={b3}"))

    # ===== BUILD FILE HASIL =====
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # ----- FILE 1: TIDAK TERBANNED -----
    buf1 = io.StringIO()
    buf1.write("═" * 60 + "\n")
    buf1.write("WEIRDMARKET — DEVICE ID TIDAK TERBANNED\n")
    buf1.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
    buf1.write("═" * 60 + "\n")
    buf1.write(f"Timestamp       : {ts_str}\n")
    buf1.write(f"Total Input     : {total}\n")
    buf1.write(f"Verified Clean  : {len(file_clean)}\n")
    buf1.write(f"Verified Banned : {len(file_banned)}\n")
    buf1.write(f"Inconsistent    : {len(inconsistent)}\n")
    buf1.write(f"Invalid Device  : {len(invalid_final)}\n")
    buf1.write("═" * 60 + "\n\n")

    buf1.write("┌──────────────────────────────────────────────┐\n")
    buf1.write("│  ✅ DEVICE ID TIDAK TERBANNED (VERIFIED 3X) │\n")
    buf1.write("└──────────────────────────────────────────────┘\n")
    for d, data in file_clean:
        pd = (data or {}).get("player_data") or {}
        buf1.write(
            f"DEVICE ID  : {d}\n"
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
    if not file_clean:
        buf1.write("(Tidak ada device yang terverifikasi clean)\n")

    if inconsistent:
        buf1.write("\n")
        buf1.write("┌──────────────────────────────────────────────┐\n")
        buf1.write("│  ⚠️ INCONSISTENT (TIDAK DIVERIFIKASI)        │\n")
        buf1.write("└──────────────────────────────────────────────┘\n")
        for d, reason in inconsistent:
            buf1.write(f"{d} | INCONSISTENT | {reason}\n")

    if invalid_final:
        buf1.write("\n")
        buf1.write("┌──────────────────────────────────────────────┐\n")
        buf1.write("│  ❌ INVALID DEVICE ID (GAGAL VALID)          │\n")
        buf1.write("└──────────────────────────────────────────────┘\n")
        for d in invalid_final:
            buf1.write(f"{d}\n")

    # ----- FILE 2: SUDAH TERBANNED -----
    buf2 = io.StringIO()
    buf2.write("═" * 60 + "\n")
    buf2.write("WEIRDMARKET — DEVICE ID SUDAH TERBANNED\n")
    buf2.write("(Hasil Verifikasi 3X SCAN — Valid + Banned)\n")
    buf2.write("═" * 60 + "\n")
    buf2.write(f"Timestamp       : {ts_str}\n")
    buf2.write(f"Total Input     : {total}\n")
    buf2.write(f"Verified Banned : {len(file_banned)}\n")
    buf2.write("═" * 60 + "\n\n")

    buf2.write("┌──────────────────────────────────────────────┐\n")
    buf2.write("│  🚫 DEVICE ID SUDAH TERBANNED (VERIFIED 3X) │\n")
    buf2.write("└──────────────────────────────────────────────┘\n")
    for l in file_banned:
        buf2.write(l + "\n")
    if not file_banned:
        buf2.write("(Tidak ada device yang terverifikasi banned)\n")

    fname1 = f"Device ID Tidak Terbanned {date_str}.txt"
    fname2 = f"Device ID Sudah Terbanned {date_str}.txt"

    out1 = io.BytesIO(buf1.getvalue().encode("utf-8"))
    out2 = io.BytesIO(buf2.getvalue().encode("utf-8"))

    # ===== KIRIM FILE 1 =====
    try:
        await context.bot.send_document(
            chat_id=cid,
            document=InputFile(out1, filename=fname1),
            caption=(f"✅ *DEVICE ID TIDAK TERBANNED*\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n"
                     f"📅 {ts_str}\n\n"
                     f"📱 Total       : `{total}`\n"
                     f"✅ Verified    : `{len(file_clean)}`\n"
                     f"⚠️ Inconsistent: `{len(inconsistent)}`\n"
                     f"❌ Invalid     : `{len(invalid_final)}`"),
            parse_mode="Markdown")
    except Exception as e:
        print(f"[VERIF3X] send file1 err: {e}")

    # ===== KIRIM FILE 2 =====
    try:
        await context.bot.send_document(
            chat_id=cid,
            document=InputFile(out2, filename=fname2),
            caption=(f"🚫 *DEVICE ID SUDAH TERBANNED*\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n"
                     f"📅 {ts_str}\n\n"
                     f"🚫 Verified Banned : `{len(file_banned)}`"),
            parse_mode="Markdown")
    except Exception as e:
        print(f"[VERIF3X] send file2 err: {e}")

    # ===== EDIT FINAL STATUS =====
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
            parse_mode="Markdown", reply_markup=back_kb())
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# POST INIT & MAIN
# ──────────────────────────────────────────────────────────────────────
async def post_init(app):
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        me = await app.bot.get_me()
        print(f"🤖 Bot: @{me.username} (id: {me.id})")
    except Exception as e:
        print(f"[POST_INIT] {e}")


def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        print("❌ Token invalid!")
        import sys
        sys.exit(1)

    print("=" * 60)
    print("🌟 WEIRDMARKET TELEGRAM BOT (FULLCHECK + 4-STEP VERIFY)")
    print("=" * 60)
    print(f"Token   : {BOT_TOKEN[:20]}...")
    print(f"Owner   : {OWNER_ID}")
    print(f"Threads : {BULK_THREADS}")
    print(f"MaxFile : {MAX_FILE_SIZE // 1024 // 1024} MB")
    print("=" * 60)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("✅ Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
