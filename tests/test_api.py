"""Test del client cloud con un finto server Hik-Connect (nessuna rete reale)."""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "custom_components" / "hikvision_axpro_cloud"))
import api  # noqa: E402

md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731
REALM, NONCE, AUTHINFO, USER, SERIAL = "DS-AXPRO", "abc123", "secret-authinfo", "utente_test", "Q123"


class FakeResp:
    def __init__(self, obj, status=200):
        self.status = status
        self._txt = obj if isinstance(obj, str) else json.dumps(obj)

    async def text(self):
        return self._txt

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeCloud:
    """Simula le risposte del cloud e della centrale dentro il tunnel."""

    def __init__(self):
        self.sessions = 0
        self.valid_session = None
        self.expire_next = False
        self.network_down = False
        self.reject_arm = False
        self.arming = "disarm"
        self.calls = []
        self.devices = [
            {"deviceSerial": "OTHER", "deviceType": "DS-2CD2143"},
            {"deviceSerial": SERIAL, "deviceType": "DS-PWA96-M-WE", "name": "Casa", "version": "V1.2.9"}]
        self.cloud_users = [{"userName": USER, "userNameSessionAuthInfo": AUTHINFO}]
        self.feature_codes = set()

    def request(self, method, url, data=None, headers=None, timeout=None):
        if self.network_down:
            raise aiohttp.ClientConnectionError("down")
        self.calls.append(url.split("?")[0].rsplit("/", 1)[-1])
        self.feature_codes.add(headers.get("featureCode"))
        if url.endswith("/login/v2"):
            if data["password"] != md5("pw"):
                return FakeResp({"meta": {"code": 1013}})
            self.sessions += 1
            self.valid_session = f"S{self.sessions}"
            return FakeResp({"meta": {"code": 200}, "loginSession": {"sessionId": self.valid_session},
                             "loginUser": {"username": USER}, "loginArea": {"apiDomain": "apiieu.test"}})
        if headers.get("sessionId") != self.valid_session or self.expire_next:
            self.expire_next = False
            self.valid_session = None
            return FakeResp({"meta": {"code": 401}})
        if "pagelist" in url:
            return FakeResp({"meta": {"code": 200}, "deviceInfos": self.devices})
        if url.endswith("/isapi"):
            return FakeResp({"meta": {"code": 200}, "data": self._isapi(data["apiData"])})
        return FakeResp("not found", 404)

    def _isapi(self, raw):
        head, _, body = raw.partition("\r\n\r\n")
        method, uri, _ = head.split("\r\n")[0].split(" ")
        if uri.startswith("/ISAPI/Security/CloudUserManage/users"):
            return "HTTP/1.1 200 OK\r\n\r\n" + json.dumps(
                {"List": [{"CloudUserManage": u} for u in self.cloud_users]})
        m = re.search(r'response="([0-9a-f]+)"', head)
        ok = m and m.group(1) == md5(f"{md5(f'{USER}:{REALM}:{AUTHINFO}')}:{NONCE}:{md5(f'{method}:{uri}')}")
        if not ok:
            return f'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}"\r\n\r\n'
        if "control/arm" in uri:
            if self.reject_arm:
                return 'HTTP/1.1 200 OK\r\n\r\n{"statusCode": 6, "subStatusCode": "zoneFault"}'
            self.arming = json.loads(body)["SubSysList"][0]["SubSys"]["armType"]
            return 'HTTP/1.1 200 OK\r\n\r\n{"statusCode": 1}'
        if "control/disarm" in uri:
            self.arming = "disarm"
            return 'HTTP/1.1 200 OK\r\n\r\n{"statusCode": 1}'
        subs = [{"SubSys": {"id": 1, "enabled": True, "arming": self.arming, "alarm": False, "name": "Area 1"}},
                {"SubSys": {"id": 2, "enabled": False, "arming": "disarm"}}]
        if "status/host" in uri:
            return "HTTP/1.1 200 OK\r\n\r\n" + json.dumps({"AlarmHostStatus": {
                "SubSysList": subs, "HostStatus": {"ACConnect": True},
                "BatteryList": [{"Battery": {"percent": 90}}], "CommuniStatus": {"cloud": "normal"}}})
        return "HTTP/1.1 200 OK\r\n\r\n" + json.dumps({"SubSysList": subs})


async def test_first_setup_finds_panel_and_reads_status():
    cloud = FakeCloud()
    c = api.HikAxProCloud("me@x.it", "pw", cloud)
    st = await (c.get_full_status())
    assert c.serial == SERIAL and c.device_name == "Casa" and c.firmware == "V1.2.9"
    assert st["areas"] == {1: {"name": "Area 1", "state": "disarmed", "alarm": False}}
    assert st["host"]["battery_percent"] == 90


async def test_saved_serial_still_loads_device_info():
    c = api.HikAxProCloud("me@x.it", "pw", FakeCloud(), serial=SERIAL)
    await (c.ensure_ready())
    assert c.device_name == "Casa" and c.model == "DS-PWA96-M-WE"


async def test_arm_and_disarm():
    cloud = FakeCloud()
    c = api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL)
    await (c.arm_away(1))
    assert cloud.arming == "away"
    await (c.disarm(1))
    assert cloud.arming == "disarm"


async def test_expired_session_is_renewed_without_reauth():
    cloud = FakeCloud()
    c = api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL)
    await (c.get_full_status())
    cloud.expire_next = True
    st = await (c.get_full_status())
    assert st["areas"][1]["state"] == "disarmed"
    assert cloud.sessions == 2
    assert cloud.calls.count("pagelist") == 1  # lista dispositivi letta una volta sola


async def test_wrong_password_is_auth_error():
    with pytest.raises(api.HikAxProAuthError):
        await (api.HikAxProCloud("me@x.it", "bad", FakeCloud()).ensure_ready())


async def test_network_down_is_clean_error():
    cloud = FakeCloud()
    cloud.network_down = True
    with pytest.raises(api.HikAxProError) as e:
        await (api.HikAxProCloud("me@x.it", "pw", cloud).ensure_ready())
    assert not isinstance(e.value, api.HikAxProAuthError)


async def test_rejected_arm_raises():
    cloud = FakeCloud()
    cloud.reject_arm = True
    with pytest.raises(api.HikAxProError, match="rejected"):
        await (api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL).arm_away(1))


async def test_list_panels_multiple_and_unknown_models():
    cloud = FakeCloud()
    cloud.devices.append({"deviceSerial": "H2", "deviceType": "DS-PHA64-LP", "name": "Ufficio"})
    panels = await (api.HikAxProCloud("me@x.it", "pw", cloud).list_panels())
    assert [p["serial"] for p in panels] == [SERIAL, "H2"]
    # nessun modello riconosciuto: vengono proposti tutti i dispositivi
    cloud.devices = [{"deviceSerial": "X1", "deviceType": "DS-NUOVO"}]
    assert [p["serial"] for p in await (api.HikAxProCloud("me@x.it", "pw", cloud).list_panels())] == ["X1"]


async def test_feature_code_random_per_install_and_kept():
    a = api.HikAxProCloud("me@x.it", "pw", FakeCloud())
    b = api.HikAxProCloud("me@x.it", "pw", FakeCloud())
    assert a.feature_code != b.feature_code and len(a.feature_code) == 32
    cloud = FakeCloud()
    await (api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL, feature_code="f" * 32).arm_away(1))
    assert cloud.feature_codes == {"f" * 32}


async def test_cloud_user_matched_by_email_or_single_user():
    cloud = FakeCloud()
    cloud.cloud_users = [{"userName": "me@x.it", "userNameSessionAuthInfo": AUTHINFO},
                         {"userName": "altro", "userNameSessionAuthInfo": "zzz"}]
    c = api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL)
    await (c.ensure_ready())
    assert c._authinfo == AUTHINFO and c._username == "me@x.it"
    cloud2 = FakeCloud()
    cloud2.cloud_users = [{"userName": "proprietario", "userNameSessionAuthInfo": AUTHINFO}]
    c2 = api.HikAxProCloud("me@x.it", "pw", cloud2, serial=SERIAL)
    await (c2.ensure_ready())
    assert c2._username == "proprietario"


async def test_unknown_cloud_user_among_many_fails_clearly():
    cloud = FakeCloud()
    cloud.cloud_users = [{"userName": "a", "userNameSessionAuthInfo": "1"},
                         {"userName": "b", "userNameSessionAuthInfo": "2"}]
    with pytest.raises(api.HikAxProError, match="not found"):
        await (api.HikAxProCloud("me@x.it", "pw", cloud, serial=SERIAL).ensure_ready())
