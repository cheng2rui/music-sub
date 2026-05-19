"""Minimal WeCom callback crypto helpers.

Implements the Enterprise WeChat URL verification and encrypted XML decrypt
flow used by application callbacks. Based on Tencent's WXBizMsgCrypt protocol,
trimmed for Music Sub inbound messages.
"""
from __future__ import annotations

import base64
import hashlib
import socket
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from Crypto.Cipher import AES


class WeComCryptoError(RuntimeError):
    pass


@dataclass
class WeComMessage:
    from_user: str = ""
    to_user: str = ""
    msg_type: str = ""
    content: str = ""
    event: str = ""
    event_key: str = ""
    msg_id: str = ""
    raw_xml: str = ""


def sha1_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    values = [token or "", timestamp or "", nonce or "", encrypt or ""]
    values.sort()
    return hashlib.sha1("".join(values).encode("utf-8")).hexdigest()


def _aes_key(encoding_aes_key: str) -> bytes:
    if not encoding_aes_key or len(encoding_aes_key) != 43:
        raise WeComCryptoError("invalid encoding_aes_key")
    try:
        key = base64.b64decode(encoding_aes_key + "=")
    except Exception as exc:
        raise WeComCryptoError(f"invalid encoding_aes_key: {exc}") from exc
    if len(key) != 32:
        raise WeComCryptoError("invalid aes key length")
    return key


def _extract_encrypt(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
        node = root.find("Encrypt")
        return node.text or "" if node is not None else ""
    except Exception as exc:
        raise WeComCryptoError(f"parse encrypted xml failed: {exc}") from exc


def decrypt_encrypt(encrypt: str, encoding_aes_key: str, receive_id: str) -> str:
    key = _aes_key(encoding_aes_key)
    try:
        cipher = AES.new(key, AES.MODE_CBC, key[:16])
        plain = cipher.decrypt(base64.b64decode(encrypt))
    except Exception as exc:
        raise WeComCryptoError(f"aes decrypt failed: {exc}") from exc
    try:
        pad = plain[-1]
        if pad < 1 or pad > 32:
            raise ValueError("invalid padding")
        plain = plain[:-pad]
        content = plain[16:]
        xml_len = socket.ntohl(struct.unpack("I", content[:4])[0])
        xml = content[4:4 + xml_len]
        recv = content[4 + xml_len:].decode("utf-8")
        if receive_id and recv != receive_id:
            raise WeComCryptoError("receive_id mismatch")
        return xml.decode("utf-8")
    except WeComCryptoError:
        raise
    except Exception as exc:
        raise WeComCryptoError(f"invalid decrypted buffer: {exc}") from exc


def verify_url(*, token: str, encoding_aes_key: str, receive_id: str, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
    if sha1_signature(token, timestamp, nonce, echostr) != msg_signature:
        raise WeComCryptoError("signature mismatch")
    return decrypt_encrypt(echostr, encoding_aes_key, receive_id)


def decrypt_message(*, token: str, encoding_aes_key: str, receive_id: str, msg_signature: str, timestamp: str, nonce: str, body: str) -> str:
    encrypt = _extract_encrypt(body)
    if not encrypt:
        raise WeComCryptoError("missing Encrypt")
    if sha1_signature(token, timestamp, nonce, encrypt) != msg_signature:
        raise WeComCryptoError("signature mismatch")
    return decrypt_encrypt(encrypt, encoding_aes_key, receive_id)


def parse_plain_message(xml_text: str) -> WeComMessage:
    root = ET.fromstring(xml_text)
    def text(name: str) -> str:
        node = root.find(name)
        return (node.text or "") if node is not None else ""
    msg_type = text("MsgType")
    content = text("Content")
    event = text("Event")
    event_key = text("EventKey")
    if msg_type == "event" and not content:
        content = event_key or event
    return WeComMessage(
        from_user=text("FromUserName"),
        to_user=text("ToUserName"),
        msg_type=msg_type,
        content=content,
        event=event,
        event_key=event_key,
        msg_id=text("MsgId"),
        raw_xml=xml_text,
    )
