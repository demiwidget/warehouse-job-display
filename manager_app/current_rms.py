from datetime import datetime, timedelta

import requests


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    for parser in (
        lambda item: datetime.fromisoformat(item),
        lambda item: datetime.strptime(item[:19], "%Y-%m-%dT%H:%M:%S"),
        lambda item: datetime.strptime(item[:10], "%Y-%m-%d"),
    ):
        try:
            parsed = parser(text)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            pass
    return None


def nested_get(data, *path, default=""):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current not in (None, "") else default


def first_value(data, *keys, default=""):
    for key in keys:
        if isinstance(key, tuple):
            value = nested_get(data, *key, default="")
        else:
            value = data.get(key) if isinstance(data, dict) else ""
        if value not in (None, ""):
            return value
    return default


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


class CurrentRMSClient:
    def __init__(self, settings):
        rms = settings.get("current_rms", {})
        self.api_base = rms.get("api_base", "https://api.current-rms.com/api/v1").rstrip("/")
        self.api_key = rms.get("api_key", "")
        self.subdomain = rms.get("subdomain", "")
        self.view_id = str(rms.get("view_id", "") or "").strip()
        self.per_page = safe_int(rms.get("per_page"), 100)
        self.max_pages = max(1, safe_int(rms.get("max_pages"), 2))

    @property
    def configured(self):
        return bool(self.api_key and self.subdomain)

    def headers(self):
        return {
            "X-AUTH-TOKEN": self.api_key,
            "X-SUBDOMAIN": self.subdomain,
            "Accept": "application/json",
        }

    def test_connection(self):
        if not self.configured:
            return False, "API key and subdomain are required."

        try:
            response = requests.get(f"{self.api_base}/members/1", headers=self.headers(), timeout=8)
            if response.status_code in (200, 404):
                return True, "Connection successful."
            if response.status_code == 401:
                return False, "Current RMS rejected the API key or subdomain."
            return False, f"Current RMS returned HTTP {response.status_code}."
        except requests.RequestException as error:
            return False, f"Could not reach Current RMS: {error}"

    def fetch_opportunities(self):
        if not self.configured:
            return []

        opportunities = []
        for page in range(1, self.max_pages + 1):
            params = {"page": page, "per_page": self.per_page}
            if self.view_id:
                params["view_id"] = self.view_id

            response = requests.get(
                f"{self.api_base}/opportunities",
                headers=self.headers(),
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            page_items = payload.get("opportunities", [])
            opportunities.extend(page_items)

            meta = payload.get("meta", {})
            total_rows = safe_int(meta.get("total_row_count"), len(opportunities))
            if len(opportunities) >= total_rows or not page_items:
                break

        return opportunities

    def fetch_opportunity_items(self, opportunity_id):
        response = requests.get(
            f"{self.api_base}/opportunities/{opportunity_id}/opportunity_items",
            headers=self.headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("opportunity_items", [])


class DashboardBuilder:
    def __init__(self):
        self._cache_key = None
        self._cache_time = None
        self._cache = None
        self._last_error = ""

    def build(self, screen, settings):
        cache_key = self._settings_cache_key(settings)
        now = datetime.now()
        if self._cache and self._cache_key == cache_key and self._cache_time:
            if (now - self._cache_time).total_seconds() < 60:
                return self._cache.get(screen, self._empty_payload(screen))

        payloads = self._build_all(settings)
        self._cache = payloads
        self._cache_key = cache_key
        self._cache_time = now
        return payloads.get(screen, self._empty_payload(screen))

    def test_connection(self, settings):
        return CurrentRMSClient(settings).test_connection()

    def refresh(self):
        self._cache = None
        self._cache_time = None

    def _settings_cache_key(self, settings):
        rms = settings.get("current_rms", {})
        return (
            rms.get("api_base", ""),
            rms.get("api_key", ""),
            rms.get("subdomain", ""),
            str(rms.get("view_id", "")),
            str(rms.get("per_page", "")),
            str(rms.get("max_pages", "")),
        )

    def _build_all(self, settings):
        client = CurrentRMSClient(settings)
        if not client.configured:
            return self._payloads_with_notice("Current RMS is not configured in the PC manager yet.")

        try:
            opportunities = client.fetch_opportunities()
            self._last_error = ""
        except Exception as error:
            self._last_error = str(error)
            return self._payloads_with_notice(f"Current RMS sync failed: {error}")

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        item_limit = safe_int(settings.get("current_rms", {}).get("item_detail_limit"), 12)

        return {
            "today": self._jobs_payload("Today", opportunities, today),
            "tomorrow": self._jobs_payload("Tomorrow", opportunities, tomorrow),
            "prep": self._prep_payload(opportunities, client, item_limit),
            "outstanding": self._outstanding_payload(opportunities),
            "notifications": self._notifications_payload(opportunities),
        }

    def _payloads_with_notice(self, message):
        notification = {
            "Time": datetime.now().strftime("%H:%M"),
            "Title": message,
            "Job Number": "",
            "Job Name": "",
            "Owner": "PC Manager",
        }
        return {
            "today": self._empty_payload("Today"),
            "tomorrow": self._empty_payload("Tomorrow"),
            "prep": self._empty_payload("Prep Status"),
            "outstanding": self._empty_payload("Outstanding Items"),
            "notifications": {
                "title": "Notifications",
                "summary": {"Notifications": 1},
                "rows": [notification],
            },
        }

    def _empty_payload(self, title):
        return {"title": str(title).title(), "summary": {}, "rows": []}

    def _jobs_payload(self, title, opportunities, target_date):
        rows = []
        for opportunity in opportunities:
            start_dt = self._opportunity_start(opportunity)
            end_dt = self._opportunity_end(opportunity)
            if start_dt and start_dt.date() == target_date:
                rows.append(self._job_row(opportunity, "Out", start_dt))
            if end_dt and end_dt.date() == target_date:
                rows.append(self._job_row(opportunity, "In", end_dt))

        rows.sort(key=lambda row: (row.get("Time") or "99:99", row.get("Job Name") or ""))
        return {
            "title": title,
            "summary": {
                "Jobs Out": sum(1 for row in rows if row.get("Section") == "Out"),
                "Jobs In": sum(1 for row in rows if row.get("Section") == "In"),
            },
            "rows": rows,
        }

    def _prep_payload(self, opportunities, client, item_limit):
        rows = []
        prepared_total = 0
        remaining_total = 0

        for opportunity in opportunities[:item_limit]:
            opportunity_id = opportunity.get("id")
            if not opportunity_id:
                continue

            try:
                items = client.fetch_opportunity_items(opportunity_id)
            except Exception:
                items = []

            prepared, total, unprepped_items = self._prep_totals(items)
            remaining = max(total - prepared, 0)
            if total <= 0:
                continue

            prepared_total += prepared
            remaining_total += remaining
            rows.append(
                {
                    "Job Name": self._opportunity_name(opportunity),
                    "Job Number": self._opportunity_number(opportunity),
                    "Delivery Date": self._format_date(self._opportunity_start(opportunity)),
                    "Prepped": prepared,
                    "Remaining": remaining,
                    "Prep Progress": f"{round((prepared / total) * 100) if total else 0}%",
                    "Owner": self._opportunity_owner(opportunity),
                    "__progress": round((prepared / total) * 100) if total else 0,
                    "__unprepped_items": unprepped_items,
                }
            )

        rows.sort(key=lambda row: (row.get("Delivery Date") or "", row.get("Job Name") or ""))
        return {
            "title": "Prep Status",
            "summary": {
                "Prepared Qty": prepared_total,
                "Remaining Qty": remaining_total,
            },
            "rows": rows,
        }

    def _outstanding_payload(self, opportunities):
        rows = []
        for opportunity in opportunities:
            status = str(first_value(opportunity, "status_name", "status", default="")).lower()
            if "complete" in status or "cancel" in status:
                continue
            rows.append(
                {
                    "Job Number": self._opportunity_number(opportunity),
                    "Job Name": self._opportunity_name(opportunity),
                    "Booked Out": self._format_date(self._opportunity_start(opportunity)),
                    "Checked In": self._format_date(self._opportunity_end(opportunity)),
                    "Outstanding": "",
                    "Total Items": "",
                    "Owner": self._opportunity_owner(opportunity),
                }
            )
        return {
            "title": "Outstanding Items",
            "summary": {"Outstanding": len(rows)},
            "rows": rows,
        }

    def _notifications_payload(self, opportunities):
        rows = [
            {
                "Time": datetime.now().strftime("%H:%M"),
                "Title": f"Current RMS sync complete. {len(opportunities)} jobs loaded.",
                "Job Number": "",
                "Job Name": "",
                "Owner": "PC Manager",
            }
        ]
        return {
            "title": "Notifications",
            "summary": {"Notifications": len(rows)},
            "rows": rows,
        }

    def _prep_totals(self, items):
        prepared_total = 0
        total_qty = 0
        unprepped_items = []

        for item in items:
            total = safe_int(first_value(item, "quantity", "quantity_total", "booked_quantity", "total_quantity"), 1)
            prepared = safe_int(
                first_value(item, "prepared_quantity", "quantity_prepared", "prepped_quantity", "prepared"),
                0,
            )
            status = str(first_value(item, "status_name", "status", default="")).lower()
            if prepared == 0 and total > 0 and "prepared" in status:
                prepared = total

            prepared = min(prepared, total)
            total_qty += total
            prepared_total += prepared

            remaining = max(total - prepared, 0)
            if remaining:
                unprepped_items.append(
                    {
                        "Item": first_value(item, ("item", "name"), "name", "description", default="Item"),
                        "Code": first_value(item, ("item", "code"), "code", default=""),
                        "Prepared": prepared,
                        "Total": total,
                        "Remaining": remaining,
                        "Status": first_value(item, "status_name", "status", default="Not prepared"),
                    }
                )

        return prepared_total, total_qty, unprepped_items

    def _job_row(self, opportunity, section, event_dt):
        return {
            "Section": section,
            "Job Name": self._opportunity_name(opportunity),
            "Job Number": self._opportunity_number(opportunity),
            "Customer": self._opportunity_customer(opportunity),
            "Time": self._format_time(event_dt),
            "Client": self._opportunity_customer(opportunity),
            "Owner": self._opportunity_owner(opportunity),
            "Status": first_value(opportunity, "status_name", "status", default=""),
        }

    def _opportunity_name(self, opportunity):
        return first_value(opportunity, "subject", "name", "description", default="Unnamed Job")

    def _opportunity_number(self, opportunity):
        return first_value(opportunity, "number", "reference", "id", default="")

    def _opportunity_customer(self, opportunity):
        return first_value(opportunity, ("member", "name"), ("customer", "name"), "customer_name", default="")

    def _opportunity_owner(self, opportunity):
        return first_value(
            opportunity,
            ("owned_by", "name"),
            ("owner", "name"),
            ("member", "name"),
            "owner_name",
            default="",
        )

    def _opportunity_start(self, opportunity):
        return parse_datetime(
            first_value(
                opportunity,
                "starts_at",
                "delivery_starts_at",
                "deliver_starts_at",
                "out_at",
                "pickup_at",
                default="",
            )
        )

    def _opportunity_end(self, opportunity):
        return parse_datetime(
            first_value(
                opportunity,
                "ends_at",
                "return_starts_at",
                "collect_starts_at",
                "in_at",
                default="",
            )
        )

    def _format_time(self, value):
        return value.strftime("%H:%M") if value else ""

    def _format_date(self, value):
        return value.strftime("%d/%m/%Y") if value else ""
