"""Client cloud Hik-Connect per centrali AX PRO condivise (via tunnel ISAPI).

Reverse-engineered dall'app Hik-Connect. API non ufficiale: può cambiare senza
preavviso. Funziona anche con centrali raggiungibili SOLO via cloud (SIM/4G),
non in rete locale.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOGIN_DOMAIN = "api.hik-connect.com"
API_KEY = "100044"
CHANNEL = "1"
# Sigle dei modelli AX PRO / AX Hybrid PRO nel campo deviceType (es. DS-PWA96-M-WE)
PANEL_TYPE_HINTS = ("PWA", "PHA", "AXPRO", "AX PRO", "AXHYBRID")


def new_feature_code() -> str:
    """Identificativo casuale del "telefono" client, uno per installazione."""
    return secrets.token_hex(16)
TIMEOUT = aiohttp.ClientTimeout(total=25)

STATE_MAP = {"disarm": "disarmed", "away": "armed_away", "stay": "armed_home",
             "arming": "arming", "disarming": "disarming"}


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class HikAxProError(Exception):
    """Errore generico del client."""


class HikAxProAuthError(HikAxProError):
    """Credenziali Hik-Connect non valide."""


class HikAxProSessionError(HikAxProError):
    """Sessione cloud scaduta o rifiutata: basta rifare il login."""


class HikAxProCloud:
    """Dialoga con una centrale AX PRO attraverso il cloud Hik-Connect."""

    def __init__(self, account: str, password: str, session: aiohttp.ClientSession,
                 serial: str | None = None, feature_code: str | None = None) -> None:
        self._headers = {"clientType": "55", "lang": "en-US",
                         "featureCode": feature_code or new_feature_code()}
        self._account = account
        self._password = password
        self._session = session
        self._serial = serial
        self._dev_name: str | None = None
        self._dev_version: str | None = None
        self._dev_type: str | None = None
        self._base = f"https://{LOGIN_DOMAIN}"
        self._session_id: str | None = None
        self._username: str | None = None
        self._authinfo: str | None = None
        self._realm: str | None = None
        self._nonce: str | None = None
        self._discovered = False
        self._lock = asyncio.Lock()

    @property
    def serial(self) -> str | None:
        return self._serial

    @property
    def feature_code(self) -> str:
        return self._headers["featureCode"]

    @property
    def device_name(self) -> str | None:
        return self._dev_name

    @property
    def firmware(self) -> str | None:
        return self._dev_version

    @property
    def model(self) -> str | None:
        return self._dev_type

    # ---------- HTTP di base ----------

    async def _request(self, method: str, url: str, headers: dict,
                       form: dict | None = None) -> dict | str:
        try:
            async with self._session.request(
                method, url, data=form, headers=headers, timeout=TIMEOUT
            ) as r:
                txt = await r.text()
                status = r.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise HikAxProError(f"Hik-Connect cloud unreachable: {err!r}") from err
        if status == 401 and headers.get("sessionId"):
            raise HikAxProSessionError("Session rejected (HTTP 401)")
        try:
            return json.loads(txt)
        except ValueError:
            return txt

    async def _post_form(self, url: str, form: dict, headers: dict) -> dict | str:
        return await self._request("POST", url, headers, form)

    async def _get(self, url: str, headers: dict) -> dict | str:
        return await self._request("GET", url, headers)

    # ---------- login ----------

    async def login(self) -> None:
        form = {"account": self._account, "password": _md5(self._password)}
        res = await self._post_form(f"{self._base}/v3/users/login/v2", form, self._headers)
        if isinstance(res, dict) and (res.get("meta") or {}).get("code") == 1100:
            self._base = "https://" + res["loginArea"]["apiDomain"]
            res = await self._post_form(f"{self._base}/v3/users/login/v2", form, self._headers)
        if not isinstance(res, dict):
            raise HikAxProError("Invalid login response")
        code = (res.get("meta") or {}).get("code")
        if code in (1013, 1014):
            raise HikAxProAuthError("Wrong Hik-Connect email or password")
        sess = res.get("loginSession") or {}
        sid = sess.get("sessionId")
        if not sid:
            msg = (res.get("meta") or {}).get("message") or ""
            raise HikAxProError(
                f"Login failed (code {code} {msg}). If device/terminal verification is "
                "enabled for the account, disable it in the Hik-Connect app."
            )
        self._session_id = sid
        self._username = (res.get("loginUser") or {}).get("username")
        area = (res.get("loginArea") or {}).get("apiDomain")
        if area:
            self._base = f"https://{area}"
        # la sessione cambia: ricalcoliamo authinfo/nonce
        self._authinfo = None
        self._nonce = None

    def _auth_headers(self) -> dict:
        h = dict(self._headers)
        h["sessionId"] = self._session_id or ""
        return h

    # ---------- tunnel ISAPI ----------

    @staticmethod
    def _body_of(inner: Any) -> str:
        if not isinstance(inner, str):
            return ""
        i = inner.find("\r\n\r\n")
        return inner[i + 4:] if i >= 0 else inner

    async def _tunnel(self, method: str, path: str, digest: str | None = None,
                      body: str = "") -> str:
        lines = [f"{method} {path} HTTP/1.1"]
        if digest:
            lines.append(f"Authorization: {digest}")
            lines.append("UserType: Operator")
        api_data = "\r\n".join(lines) + "\r\n\r\n" + body
        form = {"deviceSerial": self._serial, "channelNo": CHANNEL,
                "apiKey": API_KEY, "apiData": api_data}
        res = await self._post_form(f"{self._base}/v3/userdevices/v1/isapi",
                                    form, self._auth_headers())
        if not isinstance(res, dict):
            raise HikAxProError("Invalid tunnel response")
        code = (res.get("meta") or {}).get("code")
        data = res.get("data") or ""
        if code is not None and str(code) != "200" and not data:
            # 401 o altri codici senza risposta della centrale:
            # quasi sempre sessione cloud scaduta -> il chiamante rifà il login
            raise HikAxProSessionError(f"Tunnel rejected by the cloud (code {code})")
        return data

    # ---------- scoperta centrale ----------

    async def _list_devices(self) -> list[dict]:
        """Tutti i dispositivi dell'account (propri e condivisi)."""
        out: list[dict] = []
        offset = 0
        while True:
            url = (f"{self._base}/v3/userdevices/v1/devices/pagelist"
                   f"?groupId=-1&limit=50&offset={offset}&filter=STATUS")
            res = await self._get(url, self._auth_headers())
            if not isinstance(res, dict):
                break
            page = res.get("deviceInfos") or []
            out.extend(d for d in page if d.get("deviceSerial"))
            if len(page) < 50 or offset >= 500:
                break
            offset += 50
        return out

    @staticmethod
    def _is_panel(dev: dict) -> bool:
        t = str(dev.get("deviceType", "")).upper().replace("-", "")
        return any(h.replace(" ", "") in t for h in PANEL_TYPE_HINTS)

    async def list_panels(self) -> list[dict]:
        """Centrali AX PRO sull'account: [{serial, name, model, firmware}].

        Se nessun dispositivo è riconosciuto come AX PRO (modello con sigla
        sconosciuta) restituisce tutti i dispositivi, così l'utente può scegliere.
        """
        if not self._session_id:
            await self.login()
        devices = await self._list_devices()
        panels = [d for d in devices if self._is_panel(d)] or devices
        return [{"serial": d["deviceSerial"], "name": d.get("name"),
                 "model": d.get("deviceType"), "firmware": d.get("version")}
                for d in panels]

    async def discover_serial(self) -> str | None:
        """Trova la centrale sull'account e ne legge nome/modello/firmware.

        Se il seriale è già noto cerca proprio quello, altrimenti la prima AX PRO.
        """
        for d in await self._list_devices():
            if self._serial:
                match = d.get("deviceSerial") == self._serial
            else:
                match = self._is_panel(d)
            if match:
                self._serial = d["deviceSerial"]
                self._dev_name = d.get("name")
                self._dev_version = d.get("version")
                self._dev_type = d.get("deviceType")
                return self._serial
        return None

    # ---------- autenticazione centrale (Digest) ----------

    async def _fetch_authinfo(self) -> None:
        inner = await self._tunnel("GET", "/ISAPI/Security/CloudUserManage/users?format=json")
        try:
            obj = json.loads(self._body_of(inner))
        except ValueError:
            raise HikAxProError("Cannot read the panel cloud users")
        users = [(item.get("CloudUserManage") or {}) for item in obj.get("List") or []]
        users = [u for u in users if u.get("userNameSessionAuthInfo")]
        # di solito userName = username Hik-Connect; a volte coincide con l'email
        wanted = {(self._username or "").lower(), self._account.lower()} - {""}
        for cu in users:
            if (cu.get("userName") or "").lower() in wanted:
                self._username = cu.get("userName")
                self._authinfo = cu.get("userNameSessionAuthInfo")
                return
        if len(users) == 1:
            # un solo utente cloud con credenziali: è per forza il nostro
            self._username = users[0].get("userName") or self._username
            self._authinfo = users[0].get("userNameSessionAuthInfo")
            return
        raise HikAxProError(
            f"User '{self._username}' not found among the {len(users)} cloud users of the panel"
        )

    async def _fetch_challenge(self) -> None:
        inner = await self._tunnel("GET", "/ISAPI/SecurityCP/status/subSystems?format=json")
        mr = re.search(r'realm="([^"]+)"', inner or "")
        mn = re.search(r'nonce="([^"]+)"', inner or "")
        if not (mr and mn):
            raise HikAxProError("No digest challenge received from the panel")
        self._realm, self._nonce = mr.group(1), mn.group(1)

    def _digest(self, method: str, uri: str) -> str:
        ha1 = _md5(f"{self._username}:{self._realm}:{self._authinfo}")
        ha2 = _md5(f"{method}:{uri}")
        resp = _md5(f"{ha1}:{self._nonce}:{ha2}")
        return (f'Digest username="{self._username}", nonce="{self._nonce}", '
                f'response="{resp}", UserType="Operator"')

    async def ensure_ready(self) -> None:
        """Garantisce login + serial + authinfo + nonce validi."""
        if not self._session_id:
            await self.login()
        if not self._discovered:
            # anche col seriale già salvato: serve per nome/modello/firmware
            found = await self.discover_serial()
            if not found and not self._serial:
                raise HikAxProError("No AX PRO panel found on the account")
            self._discovered = True
        if not self._authinfo:
            await self._fetch_authinfo()
        if not self._nonce:
            await self._fetch_challenge()

    # ---------- operazioni con ri-login automatico ----------

    async def _authed_tunnel(self, method: str, uri: str, body: str = "") -> str:
        async with self._lock:
            try:
                await self.ensure_ready()
                dh = self._digest(method, uri)
                data = await self._tunnel(method, uri, digest=dh, body=body)
            except HikAxProSessionError as err:
                # sessione scaduta: rifaccio tutto (login, authinfo, nonce) una volta
                _LOGGER.debug("Cloud session to renew: %s", err)
                self._session_id = None
                await self.ensure_ready()
                dh = self._digest(method, uri)
                data = await self._tunnel(method, uri, digest=dh, body=body)
            # se la centrale risponde Unauthorized, nonce (o authinfo) sono cambiati
            if "Unauthorized" in data:
                await self._fetch_authinfo()
                await self._fetch_challenge()
                dh = self._digest(method, uri)
                data = await self._tunnel(method, uri, digest=dh, body=body)
            return data

    async def get_areas(self) -> dict[int, dict]:
        """Ritorna {id_area: {'name':.., 'state':.., 'alarm':..}} per le aree attive."""
        data = await self._authed_tunnel("GET", "/ISAPI/SecurityCP/status/subSystems?format=json")
        try:
            subs = json.loads(self._body_of(data)).get("SubSysList") or []
        except ValueError:
            raise HikAxProError("Cannot read the areas status")
        return self._parse_areas(subs)

    @staticmethod
    def _parse_host(host: dict) -> dict:
        """Estrae i dati per i sensori diagnostici dall'AlarmHostStatus."""
        hs = host.get("HostStatus") or {}
        comm = host.get("CommuniStatus") or {}
        batt = None
        bl = host.get("BatteryList") or []
        if bl:
            batt = (bl[0] or {}).get("Battery") or {}
        return {
            "battery_percent": (batt or {}).get("percent"),
            "battery_status": (batt or {}).get("status"),
            "battery_voltage": (batt or {}).get("voltage"),
            "ac_connect": hs.get("ACConnect"),
            "tamper": hs.get("tamperEvident"),
            "fault_num": hs.get("faultNum"),
            "network": hs.get("EzvizNetwork"),
            "sim_operator": comm.get("SIMOperatorName"),
            "connected_sim": comm.get("connectedSIM"),
            "mobile_status": comm.get("mobile"),
            "mobile_signal": comm.get("mobileSignal"),
            "wifi_status": comm.get("wifi"),
            "wifi_signal": comm.get("wifiSignal"),
            "wired_status": comm.get("wired"),
            "cloud_status": comm.get("cloud"),
            "flow": comm.get("flow"),
        }

    @staticmethod
    def _parse_areas(subs: list) -> dict:
        out = {}
        for s in subs or []:
            ss = s.get("SubSys") or {}
            if ss.get("enabled"):
                out[int(ss["id"])] = {
                    "name": ss.get("name") or f"Area {ss['id']}",
                    "state": STATE_MAP.get(ss.get("arming"), "unknown"),
                    "alarm": bool(ss.get("alarm")),
                }
        return out

    async def get_full_status(self) -> dict:
        """Una sola chiamata: stato completo (aree + diagnostica).

        Usa /status/host (contiene tutto). Se non disponibile, ripiega su
        /status/subSystems per le sole aree.
        """
        try:
            data = await self._authed_tunnel("GET", "/ISAPI/SecurityCP/status/host?format=json")
            obj = json.loads(self._body_of(data)).get("AlarmHostStatus")
        except (HikAxProError, ValueError, AttributeError):
            obj = None
        if isinstance(obj, dict) and obj.get("SubSysList") is not None:
            return {"areas": self._parse_areas(obj.get("SubSysList")),
                    "host": self._parse_host(obj)}
        # ripiego: solo aree
        return {"areas": await self.get_areas(), "host": None}

    async def _control(self, action: str, area_id: int) -> None:
        if action == "disarm":
            uri = "/ISAPI/SecurityCP/control/disarm?format=json"
            body = '{"SubSysList":[{"SubSys":{"id":%d}}]}' % area_id
        else:  # away | stay
            uri = "/ISAPI/SecurityCP/control/arm?format=json"
            body = '{"SubSysList":[{"SubSys":{"id":%d,"armType":"%s"}}]}' % (area_id, action)
        data = await self._authed_tunnel("PUT", uri, body)
        if '"statusCode": 1' not in data and '"statusCode":1' not in data:
            raise HikAxProError(f"Command '{action}' rejected by the panel: {self._body_of(data)[:200]}")

    async def arm_away(self, area_id: int) -> None:
        await self._control("away", area_id)

    async def arm_home(self, area_id: int) -> None:
        await self._control("stay", area_id)

    async def disarm(self, area_id: int) -> None:
        await self._control("disarm", area_id)
