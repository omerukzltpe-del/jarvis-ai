"""
J.A.R.V.I.S. — Nextcloud Entegrasyonu
CalDAV (takvim), WebDAV (dosyalar), Notes API
"""

import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from requests.auth import HTTPBasicAuth
import os

class NextcloudClient:
    def __init__(self, url: str, username: str, password: str):
        self.url      = url.rstrip("/")
        self.username = username
        self.password = password
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"OCS-APIRequest": "true"})

    # ── TAKVIM (CalDAV) ──────────────────────────────────────────────────────
    def get_today_events(self) -> list[dict]:
        """Bugünkü takvim etkinliklerini getir."""
        today     = datetime.now()
        tomorrow  = today + timedelta(days=1)
        tf_start  = today.strftime("%Y%m%dT000000Z")
        tf_end    = tomorrow.strftime("%Y%m%dT000000Z")

        caldav_url = f"{self.url}/remote.php/dav/calendars/{self.username}/"
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<c:calendar-query xmlns:c="urn:ietf:params:xml:ns:caldav"
                  xmlns:d="DAV:"
                  xmlns:cs="http://calendarserver.org/ns/"
                  xmlns:ical="http://apple.com/ns/ical/">
  <d:prop>
    <d:getetag/>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{tf_start}" end="{tf_end}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""

        events = []
        try:
            # Takvimleri listele
            r = self.session.request(
                "PROPFIND", caldav_url,
                headers={"Depth": "1", "Content-Type": "application/xml"},
                timeout=10
            )
            calendars = self._parse_caldav_calendars(r.text)

            for cal_url in calendars:
                r2 = self.session.request(
                    "REPORT", f"{self.url}{cal_url}",
                    data=body,
                    headers={"Depth": "1", "Content-Type": "application/xml"},
                    timeout=10
                )
                events.extend(self._parse_ical_events(r2.text))
        except Exception as e:
            print(f"Takvim hatası: {e}")
        return events

    def get_upcoming_events(self, days: int = 7) -> list[dict]:
        """Önümüzdeki N günün etkinliklerini getir."""
        today  = datetime.now()
        future = today + timedelta(days=days)
        caldav_url = f"{self.url}/remote.php/dav/calendars/{self.username}/"
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<c:calendar-query xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{today.strftime('%Y%m%dT000000Z')}"
                      end="{future.strftime('%Y%m%dT000000Z')}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""
        events = []
        try:
            r = self.session.request("PROPFIND", caldav_url,
                headers={"Depth":"1"}, timeout=10)
            for cal_url in self._parse_caldav_calendars(r.text):
                r2 = self.session.request(
                    "REPORT", f"{self.url}{cal_url}", data=body,
                    headers={"Depth":"1","Content-Type":"application/xml"},
                    timeout=10)
                events.extend(self._parse_ical_events(r2.text))
        except Exception as e:
            print(f"Takvim hatası: {e}")
        return sorted(events, key=lambda x: x.get("start",""))

    def add_event(self, title: str, start: datetime,
                  end: datetime = None, description: str = "") -> bool:
        """Takvime yeni etkinlik ekle."""
        if not end:
            end = start + timedelta(hours=1)
        uid = f"jarvis-{datetime.now().strftime('%Y%m%d%H%M%S')}@jarvis"
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//JARVIS//TR\r\n"
            f"BEGIN:VEVENT\r\nUID:{uid}\r\n"
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\r\n"
            f"SUMMARY:{title}\r\n"
            f"DESCRIPTION:{description}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        url = (f"{self.url}/remote.php/dav/calendars/"
               f"{self.username}/personal/{uid}.ics")
        try:
            r = self.session.put(url, data=ical.encode(),
                headers={"Content-Type":"text/calendar; charset=utf-8"},
                timeout=10)
            return r.status_code in (201, 204)
        except Exception as e:
            print(f"Etkinlik ekleme hatası: {e}")
            return False

    # ── NOTLAR ───────────────────────────────────────────────────────────────
    def get_notes(self, category: str = None) -> list[dict]:
        """Nextcloud Notes API ile notları getir."""
        url = f"{self.url}/index.php/apps/notes/api/v1/notes"
        params = {}
        if category:
            params["category"] = category
        try:
            r = self.session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                notes = r.json()
                return [{"id": n["id"], "title": n["title"],
                         "content": n["content"][:500],
                         "category": n.get("category",""),
                         "modified": n.get("modified",0)} for n in notes]
        except Exception as e:
            print(f"Notlar hatası: {e}")
        return []

    def create_note(self, title: str, content: str,
                    category: str = "JARVIS") -> bool:
        """Yeni not oluştur."""
        url = f"{self.url}/index.php/apps/notes/api/v1/notes"
        try:
            r = self.session.post(url, json={
                "title": title, "content": content, "category": category
            }, timeout=10)
            return r.status_code == 200
        except Exception as e:
            print(f"Not oluşturma hatası: {e}")
            return False

    def update_note(self, note_id: int, content: str) -> bool:
        """Notu güncelle."""
        url = f"{self.url}/index.php/apps/notes/api/v1/notes/{note_id}"
        try:
            r = self.session.put(url, json={"content": content}, timeout=10)
            return r.status_code == 200
        except Exception as e:
            print(f"Not güncelleme hatası: {e}")
            return False

    # ── DOSYALAR (WebDAV) ─────────────────────────────────────────────────────
    def list_files(self, path: str = "/") -> list[dict]:
        """WebDAV ile dosyaları listele."""
        url = f"{self.url}/remote.php/dav/files/{self.username}{path}"
        body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/><d:resourcetype/></d:prop>
</d:propfind>"""
        try:
            r = self.session.request("PROPFIND", url, data=body,
                headers={"Depth":"1","Content-Type":"application/xml"},
                timeout=10)
            return self._parse_webdav_files(r.text, path)
        except Exception as e:
            print(f"Dosya listesi hatası: {e}")
            return []

    def read_file(self, path: str) -> str:
        """Metin dosyasını oku."""
        url = f"{self.url}/remote.php/dav/files/{self.username}{path}"
        try:
            r = self.session.get(url, timeout=15)
            if r.status_code == 200:
                return r.text
        except Exception as e:
            print(f"Dosya okuma hatası: {e}")
        return ""

    def upload_file(self, path: str, content: bytes,
                    content_type: str = "text/plain") -> bool:
        """Dosya yükle/güncelle."""
        url = f"{self.url}/remote.php/dav/files/{self.username}{path}"
        try:
            r = self.session.put(url, data=content,
                headers={"Content-Type": content_type}, timeout=30)
            return r.status_code in (200, 201, 204)
        except Exception as e:
            print(f"Dosya yükleme hatası: {e}")
            return False

    def search_files(self, query: str) -> list[dict]:
        """Dosya adında arama yap."""
        files = self.list_files("/")
        return [f for f in files if query.lower() in f.get("name","").lower()]

    # ── GÖREVLER (Tasks - CalDAV VTODO) ──────────────────────────────────────
    def get_tasks(self, only_incomplete: bool = True) -> list[dict]:
        """Görevleri getir."""
        url = f"{self.url}/remote.php/dav/calendars/{self.username}/"
        body = """<?xml version="1.0" encoding="UTF-8"?>
<c:calendar-query xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VTODO"/>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""
        tasks = []
        try:
            r = self.session.request("PROPFIND", url,
                headers={"Depth":"1"}, timeout=10)
            for cal_url in self._parse_caldav_calendars(r.text):
                r2 = self.session.request("REPORT",
                    f"{self.url}{cal_url}", data=body,
                    headers={"Depth":"1","Content-Type":"application/xml"},
                    timeout=10)
                tasks.extend(self._parse_ical_tasks(r2.text))
        except Exception as e:
            print(f"Görev hatası: {e}")
        if only_incomplete:
            tasks = [t for t in tasks if t.get("status") != "COMPLETED"]
        return tasks

    # ── YARDIMCI PARSER'LAR ───────────────────────────────────────────────────
    def _parse_caldav_calendars(self, xml_text: str) -> list[str]:
        urls = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"d":"DAV:","c":"urn:ietf:params:xml:ns:caldav"}
            for resp in root.findall(".//d:response", ns):
                href = resp.find("d:href", ns)
                rtype = resp.find(".//d:resourcetype", ns)
                is_cal = rtype is not None and \
                         rtype.find("c:calendar", ns) is not None
                if href is not None and is_cal:
                    urls.append(href.text)
        except Exception:
            pass
        return urls

    def _parse_ical_events(self, xml_text: str) -> list[dict]:
        events = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"d":"DAV:","c":"urn:ietf:params:xml:ns:caldav"}
            for resp in root.findall(".//d:response", ns):
                cal_data = resp.find(".//c:calendar-data", ns)
                if cal_data is not None and cal_data.text:
                    ev = self._parse_vevent(cal_data.text)
                    if ev:
                        events.append(ev)
        except Exception:
            pass
        return events

    def _parse_ical_tasks(self, xml_text: str) -> list[dict]:
        tasks = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"d":"DAV:","c":"urn:ietf:params:xml:ns:caldav"}
            for resp in root.findall(".//d:response", ns):
                cal_data = resp.find(".//c:calendar-data", ns)
                if cal_data is not None and cal_data.text:
                    task = self._parse_vtodo(cal_data.text)
                    if task:
                        tasks.append(task)
        except Exception:
            pass
        return tasks

    def _parse_vevent(self, ical: str) -> dict | None:
        ev = {}
        in_event = False
        for line in ical.splitlines():
            if line.startswith("BEGIN:VEVENT"):
                in_event = True
            elif line.startswith("END:VEVENT"):
                break
            elif in_event:
                if line.startswith("SUMMARY:"):
                    ev["title"] = line[8:].strip()
                elif line.startswith("DTSTART"):
                    ev["start"] = line.split(":")[-1].strip()
                elif line.startswith("DTEND"):
                    ev["end"] = line.split(":")[-1].strip()
                elif line.startswith("DESCRIPTION:"):
                    ev["description"] = line[12:].strip()
                elif line.startswith("LOCATION:"):
                    ev["location"] = line[9:].strip()
        return ev if ev.get("title") else None

    def _parse_vtodo(self, ical: str) -> dict | None:
        task = {}
        in_todo = False
        for line in ical.splitlines():
            if line.startswith("BEGIN:VTODO"):
                in_todo = True
            elif line.startswith("END:VTODO"):
                break
            elif in_todo:
                if line.startswith("SUMMARY:"):
                    task["title"] = line[8:].strip()
                elif line.startswith("STATUS:"):
                    task["status"] = line[7:].strip()
                elif line.startswith("DUE:"):
                    task["due"] = line[4:].strip()
                elif line.startswith("PRIORITY:"):
                    task["priority"] = line[9:].strip()
        return task if task.get("title") else None

    def _parse_webdav_files(self, xml_text: str, base: str) -> list[dict]:
        files = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"d": "DAV:"}
            for resp in root.findall(".//d:response", ns):
                href = resp.find("d:href", ns)
                name_el = resp.find(".//d:displayname", ns)
                size_el = resp.find(".//d:getcontentlength", ns)
                mod_el  = resp.find(".//d:getlastmodified", ns)
                rtype   = resp.find(".//d:resourcetype/d:collection", ns)
                if href is not None:
                    files.append({
                        "name":     name_el.text if name_el is not None else "",
                        "path":     href.text,
                        "size":     int(size_el.text) if size_el is not None else 0,
                        "modified": mod_el.text if mod_el is not None else "",
                        "is_dir":   rtype is not None,
                    })
        except Exception:
            pass
        return files[1:]  # ilk eleman dizinin kendisi

    def format_event_time(self, dt_str: str) -> str:
        """YYYYMMDDTHHMMSSZ → okunabilir format"""
        try:
            if "T" in dt_str:
                dt = datetime.strptime(dt_str[:15], "%Y%m%dT%H%M%S")
                return dt.strftime("%H:%M")
            else:
                dt = datetime.strptime(dt_str[:8], "%Y%m%d")
                return dt.strftime("%d %B")
        except Exception:
            return dt_str

    def test_connection(self) -> dict:
        """Bağlantıyı test et."""
        try:
            r = self.session.get(
                f"{self.url}/ocs/v1.php/cloud/user",
                headers={"Accept":"application/json"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                user = data.get("ocs",{}).get("data",{})
                return {"ok": True, "display_name": user.get("display-name",""),
                        "email": user.get("email","")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
