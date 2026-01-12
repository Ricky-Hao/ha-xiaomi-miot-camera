# -*- coding: utf-8 -*-
# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
"""
MIoT Type Definitions for Camera Integration.

Only includes types needed for camera operations.
"""
from enum import Enum, auto
from typing import Dict, Optional
from pydantic import BaseModel, Field


class BaseOAuthInfo(BaseModel):
    """Base OAuth Info."""
    access_token: str = Field(description="OAuth2 access token")
    refresh_token: str = Field(description="OAuth2 refresh token")
    expires_ts: int = Field(description="OAuth2 access token expire time")


class MIoTOauthInfo(BaseOAuthInfo):
    """MIoT OAuth Info."""
    pass


class MIoTCameraStatus(int, Enum):
    """MIoT Camera Video Status."""
    DISCONNECTED = 1
    CONNECTING = auto()
    RE_CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class MIoTDeviceInfo(BaseModel):
    """MIoT Device Info."""
    did: str = Field(description="Device id")
    name: str = Field(description="Device name")
    uid: str = Field(default="", description="Device user id")
    urn: str = Field(default="", description="Device urn")
    model: str = Field(default="", description="Device model")
    manufacturer: str = Field(default="", description="Device manufacturer")
    connect_type: int = Field(default=0, description="Device connect type")
    pid: int = Field(default=0, description="Device pid")
    token: str = Field(default="", description="Device token")
    online: bool = Field(default=False, description="Device online status")
    voice_ctrl: int = Field(default=0, description="Device voice control status")
    order_time: int = Field(default=0, description="Device bind or share time")
    sub_devices: Dict[str, "MIoTDeviceInfo"] = Field(default={}, description="Device sub devices")
    is_set_pincode: int = Field(default=0, description="Device is set pincode")
    pincode_type: int = Field(default=0, description="Device pincode type")
    home_id: Optional[str] = Field(default=None, description="Device home id")
    home_name: Optional[str] = Field(default=None, description="Device home name")
    room_id: Optional[str] = Field(default=None, description="Device room id")
    room_name: Optional[str] = Field(default=None, description="Device room name")
    rssi: Optional[int] = Field(default=None, description="Device rssi")
    lan_status: Optional[bool] = Field(default=None, description="Device lan status")
    local_ip: Optional[str] = Field(default=None, description="Device local ip")
    ssid: Optional[str] = Field(default=None, description="Device ssid")
    bssid: Optional[str] = Field(default=None, description="Device bssid")
    icon: Optional[str] = Field(default=None, description="Device icon")
    parent_id: Optional[str] = Field(default=None, description="Device parent id")
    owner_id: Optional[str] = Field(default=None, description="Device owner id")
    owner_nickname: Optional[str] = Field(default=None, description="Device owner nickname")
    fw_version: Optional[str] = Field(default=None, description="Device firmware version")
    mcu_version: Optional[str] = Field(default=None, description="Device mcu version")
    platform: Optional[str] = Field(default=None, description="Device platform")


class MIoTCameraInfo(MIoTDeviceInfo):
    """MIoT Camera Info, inherited from MIoTDeviceInfo."""
    channel_count: int = Field(default=1, description="Camera channel count")
    camera_status: MIoTCameraStatus = Field(default=MIoTCameraStatus.DISCONNECTED, description="Camera status")
