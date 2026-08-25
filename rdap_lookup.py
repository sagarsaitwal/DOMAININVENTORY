"""Best-effort RDAP lookup; failures never interrupt inventory generation.

Author: Sagar Saitwal
"""

import logging
from datetime import date, datetime

import requests

from models import RDAPData


class RDAPLookup:
    def __init__(self, timeout: int, logger: logging.Logger) -> None:
        self.timeout = timeout
        self.logger = logger

    def lookup(self, domain: str) -> RDAPData:
        try:
            response = requests.get(f"https://rdap.org/domain/{domain}", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            registrar = next((entity.get("vcardArray", [None, []])[1][1][3] for entity in data.get("entities", []) if "registrar" in entity.get("roles", []) and len(entity.get("vcardArray", [None, []])[1]) > 1), "")
            expiry = next((event.get("eventDate") for event in data.get("events", []) if event.get("eventAction") in {"expiration", "expiry"}), None)
            return RDAPData(registrar=registrar or "", expiry_date=self._parse_date(expiry))
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            self.logger.info("RDAP unavailable for %s: %s", domain, exc)
            return RDAPData()

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
