from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
import html
import json
import math
import os
import re
from tempfile import NamedTemporaryFile

import requests


EVENT_META = {
    "new_job_today": {
        "source": "new job today",
        "title": "New Job Added for Today",
        "sound_suppressed": True,
    },
    "new_job_tomorrow": {
        "source": "new job tomorrow",
        "title": "New Job Added for Tomorrow",
        "sound_suppressed": True,
    },
    "new_job_next_7_days": {
        "source": "new job next 7 days",
        "title": "New Job Added Within The Next 7 Days",
        "sound_suppressed": True,
    },
    "job_returned": {
        "source": "job returned",
        "title": "Job Returned",
        "sound_suppressed": False,
    },
    "job_changed_today": {
        "source": "job changed",
        "title": "Today's Job Has Been Updated",
        "sound_suppressed": False,
    },
    "job_changed_tomorrow": {
        "source": "job changed",
        "title": "Tomorrow's Job Has Been Updated",
        "sound_suppressed": False,
    },
    "job_changed_next_7_days": {
        "source": "job changed",
        "title": "A Job Within The Next 7 Days Has Been Updated",
        "sound_suppressed": False,
    },
}

PREPARED_STATUS_CODES = {15, 20, 30, 40}
NOT_PREPARED_STATUS_CODES = {5}
CANCELLED_STATUS_CODES = {50}
ALL_DEPARTMENT_TARGET = "__all__"
NO_DEPARTMENT_TARGET = "__none__"
UNKNOWN_DEPARTMENT_TARGET = "__unknown__"
DEFAULT_OPPORTUNITY_INCLUDES = ("owner", "member")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREP_METRICS_FILE = PROJECT_ROOT / "manager_data" / "prep_metrics.json"


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


def as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def strip_html(html):
    text = re.sub(r"<[^>]*>", " ", str(html or ""))
    return re.sub(r"\s+", " ", text).strip()


class CurrentRMSClient:
    def __init__(self, settings):
        rms = settings.get("current_rms", {})
        self.api_base = rms.get("api_base", "https://api.current-rms.com/api/v1").rstrip("/")
        self.api_key = rms.get("api_key", "")
        self.subdomain = rms.get("subdomain", "")
        self.per_page = max(1, safe_int(rms.get("per_page"), 48))
        self.max_pages = max(1, safe_int(rms.get("max_pages"), 2))
        self.max_workers = max(1, min(24, safe_int(rms.get("api_workers"), 12)))
        self.hydrate_opportunities = as_bool(rms.get("hydrate_opportunities", True))
        includes = rms.get("opportunity_includes") or list(DEFAULT_OPPORTUNITY_INCLUDES)
        if isinstance(includes, str):
            includes = [includes]
        self.opportunity_includes = [str(value).strip() for value in includes or [] if str(value).strip()]
        self._opportunity_detail_cache = {}
        self._opportunity_detail_lock = Lock()

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

    def fetch_view(self, view_id):
        if not self.configured or not str(view_id or "").strip():
            return {"opportunities": [], "meta": {"total_row_count": 0}}

        opportunities = []
        meta = {"total_row_count": 0}

        for page in range(1, self.max_pages + 1):
            response = requests.get(
                f"{self.api_base}/opportunities",
                headers=self.headers(),
                params={
                    "page": page,
                    "per_page": self.per_page,
                    "view_id": str(view_id).strip(),
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            page_items = payload.get("opportunities", [])
            opportunities.extend(page_items)

            payload_meta = payload.get("meta", {}) or {}
            if page == 1:
                meta = dict(payload_meta)
            total_rows = safe_int(payload_meta.get("total_row_count"), len(opportunities))
            if len(opportunities) >= total_rows or not page_items:
                break

        meta["total_row_count"] = safe_int(meta.get("total_row_count"), len(opportunities))
        opportunities, hydrate_errors = self._hydrate_opportunities_if_needed(opportunities)
        if hydrate_errors:
            meta["opportunity_detail_errors"] = hydrate_errors
        return {"opportunities": opportunities, "meta": meta}

    def fetch_opportunity(self, opportunity_id):
        params = []
        for include in self.opportunity_includes:
            params.append(("include[]", include))

        response = requests.get(
            f"{self.api_base}/opportunities/{opportunity_id}",
            headers=self.headers(),
            params=params or None,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("opportunity", payload if isinstance(payload, dict) else {})

    def _hydrate_opportunities_if_needed(self, opportunities):
        if not self.hydrate_opportunities or not opportunities:
            return opportunities, 0

        missing_detail = [
            opportunity
            for opportunity in opportunities
            if self._opportunity_summary_needs_detail(opportunity)
        ]
        if not missing_detail:
            return opportunities, 0

        detail_by_id = {}
        errors = 0
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(missing_detail))) as executor:
            futures = {
                executor.submit(self._cached_opportunity_detail, opportunity.get("id")): str(opportunity.get("id"))
                for opportunity in missing_detail
                if opportunity.get("id")
            }
            for future in as_completed(futures):
                opportunity_id = futures[future]
                try:
                    detail = future.result()
                    if isinstance(detail, dict) and detail:
                        detail_by_id[opportunity_id] = detail
                except Exception:
                    errors += 1

        hydrated = []
        for opportunity in opportunities:
            detail = detail_by_id.get(str(opportunity.get("id")))
            if detail:
                merged = dict(opportunity)
                merged.update(detail)
                hydrated.append(merged)
            else:
                hydrated.append(opportunity)
        return hydrated, errors

    def _cached_opportunity_detail(self, opportunity_id):
        key = str(opportunity_id or "").strip()
        if not key:
            return {}

        with self._opportunity_detail_lock:
            cached = self._opportunity_detail_cache.get(key)
        if cached is not None:
            return cached

        detail = self.fetch_opportunity(key)
        with self._opportunity_detail_lock:
            self._opportunity_detail_cache[key] = detail
        return detail

    def _opportunity_summary_needs_detail(self, opportunity):
        if not isinstance(opportunity, dict):
            return False

        if not isinstance(opportunity.get("custom_fields"), dict):
            return True
        if "customer_collecting" not in opportunity or "customer_returning" not in opportunity:
            return True
        if "deliver_starts_at" not in opportunity or "deliver_ends_at" not in opportunity:
            return True
        if not first_value(opportunity, ("owner", "name"), ("owned_by", "name"), "owner_name", default=""):
            return True
        if not first_value(opportunity, ("member", "name"), ("customer", "name"), "customer_name", default=""):
            return True
        return False

    def fetch_opportunity_items(self, opportunity_id):
        response = requests.get(
            f"{self.api_base}/opportunities/{opportunity_id}/opportunity_items",
            headers=self.headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("opportunity_items", [])

    def fetch_product(self, product_id):
        response = requests.get(
            f"{self.api_base}/products/{product_id}",
            headers=self.headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("product", {})

    def fetch_quarantines(self, per_page=None, max_pages=None):
        if not self.configured:
            return {"quarantines": [], "meta": {"total_row_count": 0}}

        page_size = max(1, min(500, safe_int(per_page, self.per_page)))
        page_limit = max(1, min(100, safe_int(max_pages, 20)))

        def fetch_page(page):
            response = requests.get(
                f"{self.api_base}/quarantines",
                headers=self.headers(),
                params={"page": page, "per_page": page_size},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            return page, payload

        first_page, first_payload = fetch_page(1)
        quarantines = list(first_payload.get("quarantines", []) or [])
        meta = dict(first_payload.get("meta", {}) or {})
        total_rows = safe_int(meta.get("total_row_count"), len(quarantines))
        actual_page_size = safe_int(meta.get("per_page"), page_size) or page_size
        expected_pages = max(1, math.ceil(total_rows / max(1, actual_page_size)))
        final_page = min(page_limit, expected_pages)

        if final_page > first_page:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, final_page - first_page)) as executor:
                futures = [executor.submit(fetch_page, page) for page in range(first_page + 1, final_page + 1)]
                page_payloads = []
                for future in as_completed(futures):
                    page_payloads.append(future.result())
            for _page, payload in sorted(page_payloads, key=lambda item: item[0]):
                quarantines.extend(payload.get("quarantines", []) or [])

        meta["total_row_count"] = total_rows
        meta["fetched_row_count"] = len(quarantines)
        return {"quarantines": quarantines, "meta": meta}


class DashboardBuilder:
    def __init__(self):
        self._payloads = {}
        self._last_error = ""
        self._history = []
        self._history_day = datetime.now().date()
        self._new_job_snapshots = {}
        self._returned_job_ids = None
        self._item_snapshots = {}
        self._last_excluded_item_ids = None
        self._sound_gate_started_at = datetime.now()
        self._prep_metric_state = self._load_prep_metric_state()

    def build(self, screen, settings):
        if not self._payloads:
            self.refresh_data(settings)
        return self._payloads.get(screen, self._empty_payload(screen))

    def test_connection(self, settings):
        return CurrentRMSClient(settings).test_connection()

    def refresh(self):
        self._payloads = {}

    def _load_prep_metric_state(self):
        try:
            data = json.loads(PREP_METRICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return {
            "date": str(data.get("date") or datetime.now().date().isoformat()),
            "count": safe_int(data.get("count"), 0),
            "previous_date": str(data.get("previous_date") or ""),
            "previous_count": safe_int(data.get("previous_count"), 0),
            "snapshot": data.get("snapshot", {}) if isinstance(data.get("snapshot"), dict) else {},
        }

    def _save_prep_metric_state(self):
        PREP_METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=PREP_METRICS_FILE.parent,
                prefix=f".{PREP_METRICS_FILE.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(self._prep_metric_state, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(PREP_METRICS_FILE)
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except Exception:
                    pass

    def _roll_prep_metrics_if_new_day(self):
        today = datetime.now().date().isoformat()
        if self._prep_metric_state.get("date") == today:
            return
        self._prep_metric_state = {
            "date": today,
            "count": 0,
            "previous_date": str(self._prep_metric_state.get("date") or ""),
            "previous_count": safe_int(self._prep_metric_state.get("count"), 0),
            "snapshot": {},
        }
        self._save_prep_metric_state()

    def create_manual_alert(
        self,
        title,
        message,
        settings,
        sound_name="",
        play_sound=True,
        show_popup=True,
        source="manual test",
    ):
        clean_title = str(title or "").strip() or "Test Notification"
        clean_message = str(message or "").strip()
        if not clean_message and not show_popup and play_sound:
            clean_message = clean_title
        if not clean_message:
            return None

        html_message = "<br>".join(html.escape(line) for line in clean_message.splitlines()) or html.escape(clean_message)
        popup = {
            "title": clean_title,
            "html": (
                "<div style=\"font-size: 2.0em; line-height: 1.6; padding: 0.6em 0.8em;\">"
                f"{html_message}"
                "</div>"
            ),
        }

        self._append_history(clean_title, source, popup.get("html", ""), settings, details=clean_message)
        if self._payloads is not None:
            self._payloads["notifications"] = self._history_payload()

        return {
            "type": "manual_test",
            "title": clean_title,
            "html": popup.get("html", ""),
            "show_popup": bool(show_popup),
            "play_sound": bool(play_sound and str(sound_name or "").strip()),
            "sound": str(sound_name or "").strip(),
        }

    def refresh_data(self, settings):
        self._reset_history_if_new_day(settings)
        self._roll_prep_metrics_if_new_day()
        excluded_item_ids = self._excluded_item_ids(settings)
        if self._last_excluded_item_ids is not None and excluded_item_ids != self._last_excluded_item_ids:
            self._item_snapshots = {}
        self._last_excluded_item_ids = set(excluded_item_ids)

        client = CurrentRMSClient(settings)
        if not client.configured:
            self._last_error = "Current RMS is not configured in the PC manager yet."
            self._payloads = self._payloads_with_notice(self._last_error)
            return self._payloads, []

        try:
            views = self._fetch_views(client, settings)
            item_cache = {}
            product_cache = {}
            self._prefetch_refresh_items(client, item_cache, views)
            quarantine_view = self._fetch_quarantine_view(client, settings)
            payloads = {
                "today": self._today_payload(views.get("today_out"), views.get("today_in"), settings),
                "tomorrow": self._tomorrow_payload(views.get("tomorrow_out"), views.get("tomorrow_in")),
                "prep": self._prep_payload(views.get("prep"), client, item_cache, settings),
                "outstanding": self._outstanding_payload(views.get("outstanding"), client, item_cache),
                "unreturned": self._unreturned_payload(views.get("unreturned")),
                "quarantines": self._quarantine_payload(quarantine_view, settings),
            }

            alerts = []
            alerts.extend(self._new_job_alerts("today", "new_job_today", views.get("today_out", {}), settings))
            alerts.extend(
                self._new_job_alerts("tomorrow", "new_job_tomorrow", views.get("tomorrow_out", {}), settings)
            )
            alerts.extend(self._new_job_alerts("next_7_days", "new_job_next_7_days", views.get("prep", {}), settings))
            alerts.extend(self._job_returned_alerts(views.get("today_in", {}), settings))
            alerts.extend(
                self._job_change_alerts(
                    "today",
                    "job_changed_today",
                    views.get("today_out", {}),
                    client,
                    item_cache,
                    product_cache,
                    settings,
                )
            )
            alerts.extend(
                self._job_change_alerts(
                    "tomorrow",
                    "job_changed_tomorrow",
                    views.get("tomorrow_out", {}),
                    client,
                    item_cache,
                    product_cache,
                    settings,
                )
            )
            alerts.extend(
                self._job_change_alerts(
                    "next_7_days",
                    "job_changed_next_7_days",
                    views.get("prep", {}),
                    client,
                    item_cache,
                    product_cache,
                    settings,
                )
            )

            payloads["notifications"] = self._history_payload()
            self._last_error = ""
            self._payloads = payloads
            return payloads, alerts
        except Exception as error:
            self._last_error = str(error)
            self._payloads = self._payloads_with_notice(f"Current RMS sync failed: {error}")
            return self._payloads, []

    def _fetch_views(self, client, settings):
        rms = settings.get("current_rms", {})
        view_settings = rms.get("views", {}) or {}
        requested = {
            "today_out": str(view_settings.get("today_out", "")).strip(),
            "today_in": str(view_settings.get("today_in", "")).strip(),
            "tomorrow_out": str(view_settings.get("tomorrow_out", "")).strip(),
            "tomorrow_in": str(view_settings.get("tomorrow_in", "")).strip(),
            "prep": str(view_settings.get("prep", "")).strip(),
            "outstanding": str(view_settings.get("outstanding", "")).strip(),
            "unreturned": str(view_settings.get("unreturned", "")).strip(),
        }

        by_view_id = {"": client.fetch_view("")}
        results = {}

        view_ids = []
        seen_view_ids = set()
        for view_id in requested.values():
            if view_id and view_id not in seen_view_ids:
                view_ids.append(view_id)
                seen_view_ids.add(view_id)

        if view_ids:
            with ThreadPoolExecutor(max_workers=min(client.max_workers, len(view_ids))) as executor:
                futures = {executor.submit(client.fetch_view, view_id): view_id for view_id in view_ids}
                for future in as_completed(futures):
                    by_view_id[futures[future]] = future.result()

        for name, view_id in requested.items():
            results[name] = by_view_id[view_id]
        return results

    def _fetch_quarantine_view(self, client, settings):
        quarantine_settings = settings.get("current_rms", {}).get("quarantines", {}) or {}
        if not as_bool(quarantine_settings.get("enabled", True)):
            return {"quarantines": [], "meta": {"disabled": True, "total_row_count": 0}}

        try:
            return client.fetch_quarantines(
                per_page=quarantine_settings.get("per_page", 100),
                max_pages=quarantine_settings.get("max_pages", 20),
            )
        except Exception as error:
            return {"quarantines": [], "meta": {"error": str(error), "total_row_count": 0}}

    def _prefetch_refresh_items(self, client, item_cache, views):
        opportunity_ids = []
        for view_name in ("prep", "today_out", "tomorrow_out", "outstanding"):
            for opportunity in (views.get(view_name) or {}).get("opportunities", []):
                if view_name == "outstanding":
                    status = str(first_value(opportunity, "status_name", "status", default="")).strip().lower()
                    if status != "active":
                        continue
                opportunity_id = opportunity.get("id")
                if opportunity_id:
                    opportunity_ids.append(opportunity_id)
        self._prefetch_opportunity_items(client, item_cache, opportunity_ids)

    def _today_payload(self, out_view, in_view, settings):
        out_rows = [self._today_out_row(opportunity, settings) for opportunity in (out_view or {}).get("opportunities", [])]
        in_rows = [self._return_row(opportunity) for opportunity in (in_view or {}).get("opportunities", [])]
        return {
            "title": "Today",
            "summary": {
                "Jobs Out": safe_int((out_view or {}).get("meta", {}).get("total_row_count"), len(out_rows)),
                "Jobs In": safe_int((in_view or {}).get("meta", {}).get("total_row_count"), len(in_rows)),
            },
            "out_rows": out_rows,
            "in_rows": in_rows,
        }

    def _tomorrow_payload(self, out_view, in_view):
        out_rows = [self._tomorrow_out_row(opportunity) for opportunity in (out_view or {}).get("opportunities", [])]
        in_rows = [self._return_row(opportunity) for opportunity in (in_view or {}).get("opportunities", [])]
        return {
            "title": "Tomorrow",
            "summary": {
                "Jobs Out": safe_int((out_view or {}).get("meta", {}).get("total_row_count"), len(out_rows)),
                "Jobs In": safe_int((in_view or {}).get("meta", {}).get("total_row_count"), len(in_rows)),
            },
            "out_rows": out_rows,
            "in_rows": in_rows,
        }

    def _prep_payload(self, prep_view, client, item_cache, settings):
        rows = []
        prepared_total = 0
        remaining_total = 0
        prepared_by_job = {}

        for opportunity in (prep_view or {}).get("opportunities", []):
            opportunity_id = opportunity.get("id")
            if not opportunity_id:
                continue

            items = self._opportunity_items(client, item_cache, opportunity_id)
            prep = self._prep_totals(items, settings)
            if prep["total_qty"] <= 0:
                continue

            prepared_total += prep["prepared_qty"]
            remaining_total += prep["remaining_qty"]
            job_key = str(opportunity_id)
            prepared_by_job[job_key] = prep["prepared_qty"]
            prep_status = "Booked Out" if prep["booked_out"] else f"{prep['prepared_qty']}/{prep['total_qty']}"
            rows.append(
                {
                    "__job_id": job_key,
                    "Job Name": self._opportunity_name(opportunity),
                    "Job Number": self._opportunity_number(opportunity),
                    "Delivery Date": self._format_date(parse_datetime(first_value(opportunity, "deliver_starts_at"))),
                    "Prep Status": prep_status,
                    "Owner": self._opportunity_owner(opportunity),
                    "__unprepped_items": prep["unprepped_items"],
                    "__prepared_qty": prep["prepared_qty"],
                    "__total_qty": prep["total_qty"],
                    "__remaining_qty": prep["remaining_qty"],
                }
            )

        daily_prep = self._update_daily_prep_metrics(prepared_by_job)
        return {
            "title": "Prep Status",
            "summary": {
                "Prepared Qty": prepared_total,
                "Remaining Qty": remaining_total,
                "Prepped Today": daily_prep["count"],
                "Previous Day Prepped": daily_prep["previous_count"],
                "Previous Day": daily_prep["previous_date"],
                "Efficiency Score": daily_prep["efficiency_score"],
                "Efficiency Label": daily_prep["efficiency_label"],
            },
            "rows": rows,
        }

    def _update_daily_prep_metrics(self, prepared_by_job):
        self._roll_prep_metrics_if_new_day()
        state = self._prep_metric_state
        snapshot = state.get("snapshot", {}) if isinstance(state.get("snapshot"), dict) else {}
        next_snapshot = dict(snapshot)
        count = safe_int(state.get("count"), 0)
        changed = False

        for job_key, prepared_qty in (prepared_by_job or {}).items():
            key = str(job_key)
            current_qty = safe_int(prepared_qty, 0)
            previous_value = snapshot.get(key)
            if previous_value is None:
                next_snapshot[key] = current_qty
                changed = True
                continue

            previous_qty = safe_int(previous_value, 0)
            if current_qty > previous_qty:
                count += current_qty - previous_qty
                next_snapshot[key] = current_qty
                changed = True

        if count != safe_int(state.get("count"), 0):
            state["count"] = count
            changed = True
        if next_snapshot != snapshot:
            state["snapshot"] = next_snapshot
            changed = True
        if changed:
            self._save_prep_metric_state()

        previous_count = safe_int(state.get("previous_count"), 0)
        if previous_count > 0:
            efficiency_score = round((count / previous_count) * 100)
            efficiency_label = f"{efficiency_score}% of previous day"
        else:
            efficiency_score = None
            efficiency_label = "No previous day baseline"

        return {
            "count": count,
            "previous_count": previous_count,
            "previous_date": state.get("previous_date", ""),
            "efficiency_score": efficiency_score,
            "efficiency_label": efficiency_label,
        }

    def _outstanding_payload(self, outstanding_view, client, item_cache):
        rows = []
        opportunities = (outstanding_view or {}).get("opportunities", [])

        for opportunity in opportunities:
            if str(first_value(opportunity, "status_name", "status", default="")).strip().lower() != "active":
                continue

            opportunity_id = opportunity.get("id")
            if not opportunity_id:
                continue

            items = self._opportunity_items(client, item_cache, opportunity_id)
            outstanding = self._outstanding_totals(items)
            rows.append(
                {
                    "Job Number": self._opportunity_number(opportunity),
                    "Job Name": self._opportunity_name(opportunity),
                    "Booked Out": outstanding["booked_out_qty"],
                    "Checked In": outstanding["checked_in_qty"],
                    "Total Items": outstanding["total_items"],
                    "Owner": self._opportunity_owner(opportunity),
                    "__outstanding_items": outstanding["outstanding_items"],
                }
            )

        rows.sort(
            key=lambda row: (
                -safe_int(row.get("Total Items"), 0),
                str(row.get("Job Number") or ""),
            )
        )

        return {
            "title": "Outstanding Items",
            "summary": {
                "Outstanding": sum(safe_int(row.get("Booked Out"), 0) for row in rows),
                "Jobs": safe_int((outstanding_view or {}).get("meta", {}).get("total_row_count"), len(rows)),
            },
            "rows": rows,
        }

    def _unreturned_payload(self, unreturned_view):
        rows = [self._return_row(opportunity) for opportunity in (unreturned_view or {}).get("opportunities", [])]
        return {
            "title": "Unreturned Jobs",
            "summary": {
                "Jobs": safe_int((unreturned_view or {}).get("meta", {}).get("total_row_count"), len(rows)),
            },
            "rows": rows,
        }

    def _history_payload(self):
        rows = [
            {
                "Time": entry["Time"],
                "Title": entry["Title"],
                "Source": entry["Source"],
                "Details": entry["Details"],
            }
            for entry in self._history
        ]
        return {
            "title": "Notification History",
            "summary": {"Notifications": len(rows)},
            "rows": rows,
        }

    def _quarantine_payload(self, quarantine_view, settings):
        quarantine_settings = settings.get("current_rms", {}).get("quarantines", {}) or {}
        field_name = str(
            quarantine_settings.get("department_field") or "department_responsible_for_repair"
        ).strip()
        if not field_name:
            field_name = "department_responsible_for_repair"

        mappings = {
            str(key).strip(): str(value).strip()
            for key, value in (quarantine_settings.get("department_mappings", {}) or {}).items()
            if str(key).strip() and str(value).strip()
        }
        excluded_department_ids = {
            str(item).strip()
            for item in quarantine_settings.get("excluded_department_ids", []) or []
            if str(item).strip()
        }
        active_only = as_bool(quarantine_settings.get("active_only", True))
        meta = dict((quarantine_view or {}).get("meta", {}) or {})
        seed_configured_departments = not meta.get("disabled") and not meta.get("error")
        rows_by_department = {}
        detail_rows = []
        if seed_configured_departments:
            rows_by_department = {
                department_id: {
                    "Tag": department_id,
                    "Department": department_name,
                    "Quarantines": 0,
                }
                for department_id, department_name in mappings.items()
            }
        unassigned_count = 0

        for quarantine in (quarantine_view or {}).get("quarantines", []):
            if active_only and quarantine.get("active") is False:
                continue

            department_id = str(first_value(quarantine.get("custom_fields", {}), field_name, default="")).strip()
            if department_id in excluded_department_ids:
                continue
            if not department_id:
                department_id = "Unassigned"
                unassigned_count += 1
            department_name = mappings.get(department_id) or (
                "Unassigned" if department_id == "Unassigned" else f"Department {department_id}"
            )
            detail_rows.append(self._quarantine_detail_row(quarantine, department_name))
            row = rows_by_department.setdefault(
                department_id,
                {
                    "Tag": department_id,
                    "Department": department_name,
                    "Quarantines": 0,
                },
            )
            row["Quarantines"] += 1

        rows = sorted(
            rows_by_department.values(),
            key=lambda row: (safe_int(row.get("Quarantines"), 0), str(row.get("Department", "")).lower()),
        )
        for index, row in enumerate(rows, start=1):
            row["Rank"] = index

        detail_rows.sort(
            key=lambda row: (
                str(row.get("Department", "")).lower(),
                str(row.get("Item", "")).lower(),
                str(row.get("Asset", "")).lower(),
            )
        )

        total = sum(safe_int(row.get("Quarantines"), 0) for row in rows)
        summary = {
            "Total": total,
            "Departments": len(rows),
            "Unassigned": unassigned_count,
            "Fetched": safe_int(meta.get("fetched_row_count"), total),
            "API Total": safe_int(meta.get("total_row_count"), total),
        }
        if meta.get("disabled"):
            summary["Status"] = "Disabled in PC Manager"
        elif meta.get("error"):
            summary["Status"] = f"Error: {meta.get('error')}"
        elif summary["Fetched"] < summary["API Total"]:
            summary["Status"] = f"Limited to {summary['Fetched']} of {summary['API Total']} rows"
        else:
            summary["Status"] = "Current"

        return {
            "title": "Quarantines",
            "summary": summary,
            "rows": rows,
            "detail_rows": detail_rows,
        }

    def _quarantine_detail_row(self, quarantine, department_name):
        custom_fields = quarantine.get("custom_fields", {}) if isinstance(quarantine, dict) else {}
        item_name = first_value(
            quarantine,
            "name",
            "item_name",
            ("item", "name"),
            ("product", "name"),
            ("stock_level", "name"),
            "description",
            default="",
        )
        if not item_name:
            item_name = f"Quarantine {first_value(quarantine, 'id', default='')}".strip()
        asset = first_value(
            quarantine,
            "asset_number",
            "stock_level_asset_number",
            "stock_level_id",
            ("asset", "number"),
            ("stock_level", "asset_number"),
            ("stock_level", "id"),
            default="",
        )
        reason = first_value(quarantine, "reason", "notes", "comment", "description", default="")
        created = parse_datetime(first_value(quarantine, "created_at", "created_on", "opened_at", default=""))
        return {
            "Department": department_name,
            "Item": strip_html(item_name),
            "Asset": strip_html(asset),
            "Reason": strip_html(reason),
            "Status": "Active" if quarantine.get("active", True) else "Inactive",
            "Created": self._format_date(created) if created else "",
            "ID": first_value(quarantine, "id", default=""),
            "Tag": first_value(custom_fields, "department_responsible_for_repair", default=""),
        }

    def _payloads_with_notice(self, message):
        rows = self._history_payload().get("rows", [])
        if not rows:
            rows = [
                {
                    "Time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    "Title": message,
                    "Source": "pc manager",
                    "Details": "",
                }
            ]
        return {
            "today": self._empty_payload("Today"),
            "tomorrow": self._empty_payload("Tomorrow"),
            "prep": self._empty_payload("Prep Status"),
            "outstanding": self._empty_payload("Outstanding Items"),
            "unreturned": self._empty_payload("Unreturned Jobs"),
            "quarantines": self._empty_payload("Quarantines"),
            "notifications": {
                "title": "Notification History",
                "summary": {"Notifications": len(rows)},
                "rows": rows,
            },
        }

    def _empty_payload(self, title):
        return {"title": str(title).title(), "summary": {}, "rows": [], "out_rows": [], "in_rows": []}

    def _today_out_row(self, opportunity, settings):
        locations = settings.get("current_rms", {}).get("collection_locations", {}) or {}
        location_id = str(first_value(opportunity.get("custom_fields", {}), "collection_location", default="")).strip()
        customer_collecting = "No"
        if as_bool(opportunity.get("customer_collecting")):
            location_name = locations.get(location_id, "Unknown")
            customer_collecting = f"Yes - {location_name}"

        status_code = safe_int(first_value(opportunity, "status", "status_id", default=0), 0)
        status_name = str(first_value(opportunity, "status_name", default="")).strip().lower()
        booked_out = "Yes" if status_code == 20 or status_name == "booked out" else ""

        return {
            "Job Name": self._opportunity_name(opportunity),
            "Job Number": self._opportunity_number(opportunity),
            "Customer collecting": customer_collecting,
            "Time": self._format_time_range(
                parse_datetime(first_value(opportunity, "deliver_starts_at")),
                parse_datetime(first_value(opportunity, "deliver_ends_at")),
            ),
            "Client": self._opportunity_customer(opportunity),
            "Owner": self._opportunity_owner(opportunity),
            "Booked Out": booked_out,
        }

    def _tomorrow_out_row(self, opportunity):
        return {
            "Job Name": self._opportunity_name(opportunity),
            "Job Number": self._opportunity_number(opportunity),
            "Customer collecting": "Yes" if as_bool(opportunity.get("customer_collecting")) else "No",
            "Time": self._format_time_range(
                parse_datetime(first_value(opportunity, "deliver_starts_at")),
                parse_datetime(first_value(opportunity, "deliver_ends_at")),
            ),
            "Client": self._opportunity_customer(opportunity),
            "Owner": self._opportunity_owner(opportunity),
        }

    def _return_row(self, opportunity):
        returned_field = str(first_value(opportunity.get("custom_fields", {}), "job_returned_but_unchecked", default=""))
        return {
            "Job Name": self._opportunity_name(opportunity),
            "Job Number": self._opportunity_number(opportunity),
            "Customer Returning": "Yes" if as_bool(opportunity.get("customer_returning")) else "No",
            "Time": self._format_time_range(
                parse_datetime(first_value(opportunity, "deliver_starts_at")),
                parse_datetime(first_value(opportunity, "deliver_ends_at")),
            ),
            "Client": self._opportunity_customer(opportunity),
            "Owner": self._opportunity_owner(opportunity),
            "Job Returned": "Yes" if returned_field.strip().lower() == "yes" else "No",
        }

    def _new_job_alerts(self, bucket, event_type, view_payload, settings):
        jobs = (view_payload or {}).get("opportunities", [])
        current_ids = [str(self._opportunity_number(job) or job.get("id") or "").strip() for job in jobs]
        current_ids = [item for item in current_ids if item]
        previous_ids = self._new_job_snapshots.get(bucket)

        self._new_job_snapshots[bucket] = current_ids
        if previous_ids is None:
            return []

        previous_set = set(previous_ids)
        new_jobs = [job for job in jobs if str(self._opportunity_number(job) or job.get("id") or "").strip() not in previous_set]
        return [self._emit_alert(event_type, self._new_job_popup(event_type, job), settings) for job in new_jobs]

    def _job_returned_alerts(self, view_payload, settings):
        jobs = (view_payload or {}).get("opportunities", [])
        returned_jobs = [
            job
            for job in jobs
            if str(first_value(job.get("custom_fields", {}), "job_returned_but_unchecked", default="")).strip().lower()
            == "yes"
        ]
        current_ids = [str(job.get("id") or "") for job in returned_jobs if job.get("id")]
        previous_ids = self._returned_job_ids
        self._returned_job_ids = current_ids
        if previous_ids is None:
            return []

        previous_set = set(previous_ids)
        alerts = []
        for job in returned_jobs:
            job_id = str(job.get("id") or "")
            if job_id and job_id not in previous_set:
                alerts.append(self._emit_alert("job_returned", self._job_returned_popup(job), settings))
        return alerts

    def _job_change_alerts(self, bucket, event_type, view_payload, client, item_cache, product_cache, settings):
        jobs = (view_payload or {}).get("opportunities", [])
        excluded_item_ids = self._excluded_item_ids(settings)
        snapshot = self._item_snapshots.setdefault(bucket, {})
        alerts = []
        self._prefetch_opportunity_items(
            client,
            item_cache,
            [job.get("id") for job in jobs if job.get("id")],
        )

        if not snapshot:
            for job in jobs:
                opportunity_id = job.get("id")
                if opportunity_id:
                    snapshot[str(opportunity_id)] = self._item_snapshot(
                        self._opportunity_items(client, item_cache, opportunity_id),
                        excluded_item_ids,
                        settings,
                        include_accessories=False,
                    )
            return []

        next_snapshot = {}
        for job in jobs:
            opportunity_id = job.get("id")
            if not opportunity_id:
                continue

            key = str(opportunity_id)
            current_items = self._item_snapshot(
                self._opportunity_items(client, item_cache, opportunity_id),
                excluded_item_ids,
                settings,
                include_accessories=False,
            )
            changes = self._compare_items(snapshot.get(key, {}), current_items)
            if changes:
                self._enrich_change_departments(changes, client, product_cache, settings)
                for target_departments, routed_changes in self._department_change_groups(changes, settings):
                    alert = self._emit_alert(
                        event_type,
                        self._job_change_popup(event_type, self._opportunity_name(job), routed_changes),
                        settings,
                        target_departments=target_departments,
                    )
                    if alert:
                        alerts.append(alert)
            next_snapshot[key] = current_items

        self._item_snapshots[bucket] = next_snapshot
        return alerts

    def _compare_items(self, previous_items, current_items):
        changes = []

        for item_id, item in current_items.items():
            previous = previous_items.get(item_id)
            if not previous and safe_int(item.get("status"), 0) == 5:
                changes.append({"type": "added", "item": item})
            elif previous and str(previous.get("quantity")) != str(item.get("quantity")):
                changes.append({"type": "updated", "item": item, "old_quantity": previous.get("quantity", 0)})

        for item_id, item in previous_items.items():
            if item_id not in current_items:
                changes.append({"type": "removed", "item": item})

        displayable = []
        for change in changes:
            quantity = safe_int(change.get("item", {}).get("quantity"), 0)
            if change["type"] in {"added", "updated"} and quantity == 0:
                continue
            displayable.append(change)
        return displayable

    def _department_change_groups(self, changes, settings):
        routing = settings.get("alerts", {}).get("department_routing", {}) or {}
        if not as_bool(routing.get("enabled", True)):
            return [([], changes)]

        grouped = {}
        unknown_changes = []
        for change in changes:
            departments = [
                str(value).strip()
                for value in change.get("item", {}).get("prep_departments", []) or []
                if str(value).strip()
            ]
            if not departments:
                unknown_changes.append(change)
                continue
            for department in departments:
                grouped.setdefault(department, []).append(change)

        routed_groups = [([department], grouped[department]) for department in sorted(grouped)]
        if unknown_changes:
            routes = routing.get("routes", {}) if isinstance(routing.get("routes", {}), dict) else {}
            if routes.get(UNKNOWN_DEPARTMENT_TARGET):
                target = UNKNOWN_DEPARTMENT_TARGET
            elif as_bool(routing.get("send_unknown_to_all", True)):
                target = ALL_DEPARTMENT_TARGET
            else:
                target = NO_DEPARTMENT_TARGET
            routed_groups.append(([target], unknown_changes))
        return routed_groups or [([NO_DEPARTMENT_TARGET], changes)]

    def _enrich_change_departments(self, changes, client, product_cache, settings):
        product_ids = []
        for change in changes:
            item = change.get("item", {})
            if item.get("prep_departments"):
                continue
            product_id = first_value(item, "item_id", "resource_item_id", "source_id", default="")
            if str(product_id).strip():
                product_ids.append(product_id)

        self._prefetch_products(client, product_cache, product_ids)

        for change in changes:
            item = change.get("item", {})
            if item.get("prep_departments"):
                continue
            product_id = str(first_value(item, "item_id", "resource_item_id", "source_id", default="")).strip()
            product = product_cache.get(product_id, {})
            departments = self._item_prep_departments(product, settings)
            if departments:
                item["prep_departments"] = departments

    def _emit_alert(self, event_type, popup, settings, target_departments=None):
        if not popup:
            return None

        event_config = self._event_settings(settings, event_type)
        if not event_config.get("enabled", True):
            return None

        show_popup = event_config.get("show_popup", True)
        play_sound = event_config.get("play_sound", True) and bool(event_config.get("sound", "").strip())
        if EVENT_META.get(event_type, {}).get("sound_suppressed"):
            play_sound = play_sound and self._sound_allowed(settings)

        self._append_history(
            popup.get("title") or EVENT_META.get(event_type, {}).get("title", "Notification"),
            EVENT_META.get(event_type, {}).get("source", event_type),
            popup.get("html", ""),
            settings,
        )

        alert = {
            "type": event_type,
            "title": popup.get("title", ""),
            "html": popup.get("html", ""),
            "show_popup": show_popup,
            "play_sound": play_sound,
            "sound": str(event_config.get("sound", "")).strip(),
        }
        if isinstance(popup.get("email_context"), dict):
            alert["email_context"] = dict(popup.get("email_context"))
        if target_departments:
            alert["target_departments"] = list(target_departments)
        return alert

    def _append_history(self, title, source, html_content, settings, details=None):
        history_entry = {
            "ts": datetime.now().timestamp(),
            "Time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "Title": title,
            "Source": source,
            "Details": details if details is not None else strip_html(html_content),
        }
        self._history.append(history_entry)
        self._history.sort(key=lambda item: item["ts"], reverse=True)
        history_limit = max(1, safe_int(settings.get("alerts", {}).get("history_limit"), 500))
        self._history = self._history[:history_limit]

    def _event_settings(self, settings, event_type):
        default = {
            "enabled": True,
            "show_popup": True,
            "play_sound": True,
            "sound": "",
        }
        values = settings.get("alerts", {}).get("event_types", {}).get(event_type, {})
        merged = dict(default)
        merged.update(values or {})
        return merged

    def _sound_allowed(self, settings):
        alerts = settings.get("alerts", {})
        quiet_start = max(0, min(23, safe_int(alerts.get("quiet_hours_start"), 21)))
        quiet_end = max(0, min(23, safe_int(alerts.get("quiet_hours_end"), 7)))
        suppress_seconds = max(0, safe_int(alerts.get("startup_sound_suppress_seconds"), 20))
        now = datetime.now()

        if suppress_seconds and (now - self._sound_gate_started_at).total_seconds() < suppress_seconds:
            return False

        hour = now.hour
        if quiet_start == quiet_end:
            return True
        if quiet_start < quiet_end:
            return not (quiet_start <= hour < quiet_end)
        return not (hour >= quiet_start or hour < quiet_end)

    def _new_job_popup(self, event_type, opportunity):
        meta = EVENT_META.get(event_type, {})
        job_name = self._opportunity_name(opportunity)
        job_number = self._opportunity_number(opportunity)
        owner = self._opportunity_owner(opportunity) or "Unassigned"

        if event_type == "new_job_next_7_days":
            html = (
                "<ul style=\"font-size: 2.0em; line-height: 1.6; padding-left: 1em;\">"
                f"<li><b>Job Name:</b> {job_name}</li>"
                f"<li><b>Job #:</b> {job_number}</li>"
                f"<li><b>Load:</b> {self._format_popup_datetime(parse_datetime(first_value(opportunity, 'load_starts_at')))}</li>"
                f"<li><b>Owner:</b> {owner}</li>"
                f"<li><b>Client:</b> {self._opportunity_customer(opportunity) or 'Unknown'}</li>"
                "</ul>"
            )
        else:
            html = (
                "<ul style=\"font-size: 2.0em; line-height: 1.6; padding-left: 1em;\">"
                f"<li><b>Job Name:</b> {job_name}</li>"
                f"<li><b>Job #:</b> {job_number}</li>"
                f"<li><b>Load:</b> {self._format_popup_datetime(parse_datetime(first_value(opportunity, 'load_starts_at')))}</li>"
                f"<li><b>Start:</b> {self._format_popup_datetime(parse_datetime(first_value(opportunity, 'deliver_starts_at')))}</li>"
                f"<li><b>Owner:</b> {owner}</li>"
                "</ul>"
            )

        return {
            "title": meta.get("title", "New Job Added"),
            "html": html,
        }

    def _job_returned_popup(self, opportunity):
        local_time = datetime.now().strftime("%d %b %Y %H:%M")
        context = {
            "job_name": self._opportunity_name(opportunity),
            "job_number": self._opportunity_number(opportunity),
            "client": self._opportunity_customer(opportunity) or "Unknown",
            "owner": self._opportunity_owner(opportunity) or "Unassigned",
            "returned_at": local_time,
        }
        html = (
            "<div style=\"font-size: 2.0em; text-align: center; padding: 1em;\">"
            "<b>A job has been returned:</b><br>"
            f"Job: {context['job_name']}<br>"
            f"Job Number: {context['job_number']}<br>"
            f"Returned at: {local_time}"
            "</div>"
        )
        return {
            "title": EVENT_META["job_returned"]["title"],
            "html": html,
            "email_context": context,
        }

    def _job_change_popup(self, event_type, job_name, changes):
        if not changes:
            return None

        lines = []
        for change in changes:
            item = change.get("item", {})
            item_name = item.get("name") or "Item"
            quantity = self._format_quantity(item.get("quantity"))
            if change["type"] == "added":
                lines.append(f"<li><b>Added</b>: {item_name} (Qty: {quantity})</li>")
            elif change["type"] == "updated":
                old_quantity = self._format_quantity(change.get("old_quantity"))
                lines.append(f"<li><b>Updated</b>: {item_name} Qty from {old_quantity} to {quantity}</li>")
            elif change["type"] == "removed":
                lines.append(f"<li><b>Removed</b>: {item_name} (Qty: {quantity})</li>")

        if not lines:
            return None

        if event_type == "job_changed_today":
            title = f"Today's Job \"{job_name}\" Has Been Updated"
            html = (
                f"<b>Changes detected in job: {job_name}</b>"
                "<ul style=\"margin-top: 8px;\">"
                f"{''.join(lines)}"
                "</ul>"
            )
            return {"title": title, "html": html}

        if event_type == "job_changed_tomorrow":
            title = f"Tomorrow's Job \"{job_name}\" Has Been Updated"
            html = (
                "<ul style=\"margin-top: 10px;\">"
                f"{''.join(lines)}"
                "</ul>"
            )
            return {"title": title, "html": html}

        html = (
            "<div style=\"font-size: 24px; line-height: 1.5; margin-top: 10px;\">"
            "<div style=\"font-size: 28px;\">A Job Within The Next 7 Days Has Been Updated:</div>"
            f"<div style=\"font-size: 32px; font-weight: bold; margin-bottom: 15px;\">\"{job_name}\"</div>"
            "<ul style=\"margin-top: 10px; padding-left: 25px;\">"
            f"{''.join(lines)}"
            "</ul>"
            "</div>"
        )
        return {"title": "", "html": html}

    def _item_snapshot(self, items, excluded_ids=None, settings=None, include_accessories=True):
        excluded_ids = excluded_ids or set()
        snapshot = {}
        for item in items:
            if not include_accessories and self._item_is_accessory_line(item):
                continue
            if self._item_is_excluded(item, excluded_ids):
                continue
            item_id = item.get("id")
            if item_id in (None, ""):
                continue
            resource_item_id = first_value(item, "item_id", "resource_item_id", ("item", "id"), default="")
            snapshot[str(item_id)] = {
                "id": item_id,
                "item_id": resource_item_id,
                "name": first_value(item, ("item", "name"), "name", "description", default="Item"),
                "quantity": first_value(item, "quantity", "quantity_total", "booked_quantity", default=0),
                "status": first_value(item, "status", "status_id", default=0),
                "prep_departments": self._item_prep_departments(item, settings),
            }
        return snapshot

    def _item_is_accessory_line(self, item):
        item_type = safe_int(first_value(item, "opportunity_item_type", default=-1), -1)
        item_type_name = str(first_value(item, "opportunity_item_type_name", default="")).strip().lower()
        return item_type == 2 or item_type_name == "accessory"

    def _item_prep_departments(self, item, settings=None):
        candidates = []
        field_names = self._routing_field_names(settings or {})
        for container in (
            item,
            item.get("item") if isinstance(item, dict) else {},
            item.get("resource_item") if isinstance(item, dict) else {},
        ):
            if not isinstance(container, dict):
                continue
            for field_name in field_names:
                candidates.extend(self._custom_field_values(container, field_name))

        seen = set()
        departments = []
        for value in candidates:
            text = str(value).strip()
            key = text.lower()
            if text and key not in seen:
                departments.append(text)
                seen.add(key)
        return departments

    def _routing_field_names(self, settings):
        routing = settings.get("alerts", {}).get("department_routing", {}) or {}
        field_names = routing.get("field_names", [])
        if isinstance(field_names, str):
            field_names = [item.strip() for item in field_names.split(",") if item.strip()]
        if not isinstance(field_names, list):
            field_names = []
        values = [str(item).strip() for item in field_names if str(item).strip()]
        return values or ["prep_department"]

    def _custom_field_values(self, container, field_name):
        values = []
        field_key = self._normalise_route_key(field_name)
        for source_key in ("custom_fields", "custom_field_values", "custom_fields_data"):
            source = container.get(source_key)
            if isinstance(source, dict):
                for key, value in source.items():
                    if self._normalise_route_key(key) == field_key:
                        values.extend(self._flatten_custom_value(value))
            elif isinstance(source, list):
                for entry in source:
                    if not isinstance(entry, dict):
                        continue
                    names = [
                        entry.get("name"),
                        entry.get("label"),
                        entry.get("key"),
                        entry.get("slug"),
                        entry.get("identifier"),
                    ]
                    if any(self._normalise_route_key(name) == field_key for name in names if name):
                        values.extend(
                            self._flatten_custom_value(
                                first_value(
                                    entry,
                                    "value",
                                    "display_value",
                                    "values",
                                    "selected_value",
                                    "selected_values",
                                    default="",
                                )
                            )
                        )

        for key, value in container.items():
            if self._normalise_route_key(key) == field_key:
                values.extend(self._flatten_custom_value(value))
        return values

    def _flatten_custom_value(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, list):
            values = []
            for item in value:
                values.extend(self._flatten_custom_value(item))
            return values
        if isinstance(value, dict):
            for key in ("name", "label", "value", "display_value", "text", "id"):
                if value.get(key) not in (None, ""):
                    return self._flatten_custom_value(value.get(key))
            return []
        return [str(value).strip()]

    def _normalise_route_key(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _opportunity_items(self, client, item_cache, opportunity_id):
        key = str(opportunity_id)
        if key not in item_cache:
            try:
                item_cache[key] = client.fetch_opportunity_items(opportunity_id)
            except Exception:
                item_cache[key] = []
        return item_cache[key]

    def _prefetch_opportunity_items(self, client, item_cache, opportunity_ids):
        missing_ids = []
        seen = set()
        for opportunity_id in opportunity_ids:
            key = str(opportunity_id).strip() if opportunity_id not in (None, "") else ""
            if not key or key in seen or key in item_cache:
                continue
            missing_ids.append(opportunity_id)
            seen.add(key)

        if not missing_ids:
            return

        with ThreadPoolExecutor(max_workers=min(client.max_workers, len(missing_ids))) as executor:
            futures = {
                executor.submit(client.fetch_opportunity_items, opportunity_id): str(opportunity_id)
                for opportunity_id in missing_ids
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    item_cache[key] = future.result()
                except Exception:
                    item_cache[key] = []

    def _prefetch_products(self, client, product_cache, product_ids):
        missing_ids = []
        seen = set()
        for product_id in product_ids:
            key = str(product_id).strip() if product_id not in (None, "") else ""
            if not key or key in seen or key in product_cache:
                continue
            missing_ids.append(key)
            seen.add(key)

        if not missing_ids:
            return

        with ThreadPoolExecutor(max_workers=min(client.max_workers, len(missing_ids))) as executor:
            futures = {
                executor.submit(client.fetch_product, product_id): product_id
                for product_id in missing_ids
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    product_cache[key] = future.result()
                except Exception:
                    product_cache[key] = {}

    def _outstanding_totals(self, items):
        booked_out_qty = 0
        checked_in_qty = 0
        outstanding_items = []
        for item in items:
            breakdown = self._outstanding_item_breakdown(item)
            if breakdown["total_items"] <= 0:
                continue

            booked_out_qty += breakdown["booked_out_qty"]
            checked_in_qty += breakdown["checked_in_qty"]
            if breakdown["booked_out_qty"] > 0:
                outstanding_items.append(
                    {
                        "Item": first_value(item, ("item", "name"), "name", "description", default="Item"),
                        "Code": first_value(item, ("item", "code"), "code", default=""),
                        "Outstanding": breakdown["booked_out_qty"],
                        "Checked In": breakdown["checked_in_qty"],
                        "Status": breakdown["status_label"],
                        "Booked Out Detail": breakdown["detail"],
                    }
                )
        return {
            "booked_out_qty": booked_out_qty,
            "checked_in_qty": checked_in_qty,
            "total_items": booked_out_qty + checked_in_qty,
            "outstanding_items": outstanding_items,
        }

    def _outstanding_item_breakdown(self, item):
        line_total = safe_int(first_value(item, "quantity", "quantity_total", "booked_quantity", "total_quantity"), 0)
        status_code = safe_int(first_value(item, "status", "status_id", default=0), 0)
        status_name = str(first_value(item, "status_name", default="")).strip()
        assets = item.get("item_assets") if isinstance(item.get("item_assets"), list) else []

        if assets:
            booked_out_qty = 0
            checked_in_qty = 0
            detail_parts = []
            status_labels = {}

            for asset in assets:
                asset_status = safe_int(first_value(asset, "status", "status_id", default=0), 0)
                if asset_status in CANCELLED_STATUS_CODES:
                    continue

                qty = safe_int(first_value(asset, "quantity", "quantity_total", default=0), 0)
                if qty <= 0:
                    continue

                asset_status_name = str(first_value(asset, "status_name", default="")).strip()
                if asset_status == 20:
                    booked_out_qty += qty
                    status_labels[asset_status_name or "Booked Out"] = True
                    asset_label = first_value(
                        asset,
                        "stock_level_asset_number",
                        "asset_number",
                        "stock_level_id",
                        default=asset_status_name or "Booked Out",
                    )
                    detail_parts.append(f"{asset_label} x{qty}")
                elif asset_status == 30:
                    checked_in_qty += qty
                    status_labels[asset_status_name or "Checked In"] = True

            return {
                "booked_out_qty": booked_out_qty,
                "checked_in_qty": checked_in_qty,
                "total_items": booked_out_qty + checked_in_qty,
                "status_label": " / ".join(status_labels) or status_name or "Outstanding",
                "detail": ", ".join(detail_parts[:12]) + (" ..." if len(detail_parts) > 12 else ""),
            }

        if line_total <= 0 or status_code in CANCELLED_STATUS_CODES:
            return {
                "booked_out_qty": 0,
                "checked_in_qty": 0,
                "total_items": 0,
                "status_label": status_name,
                "detail": "",
            }

        booked_out_qty = line_total if status_code == 20 else 0
        checked_in_qty = line_total if status_code == 30 else 0
        return {
            "booked_out_qty": booked_out_qty,
            "checked_in_qty": checked_in_qty,
            "total_items": booked_out_qty + checked_in_qty,
            "status_label": status_name or str(status_code) or "Outstanding",
            "detail": status_name or "",
        }

    def _prep_totals(self, items, settings):
        excluded_ids = self._excluded_item_ids(settings)

        prepared_total = 0
        total_qty = 0
        booked_out_qty = 0
        unprepped_items = []

        for item in items:
            if self._item_is_excluded(item, excluded_ids):
                continue

            breakdown = self._prep_item_breakdown(item)
            if breakdown["total_qty"] <= 0:
                continue

            total_qty += breakdown["total_qty"]
            prepared_total += breakdown["prepared_qty"]
            booked_out_qty += breakdown["booked_out_qty"]

            if breakdown["remaining_qty"] > 0:
                unprepped_items.append(
                    {
                        "Item": first_value(item, ("item", "name"), "name", "description", default="Item"),
                        "Code": first_value(item, ("item", "code"), "code", default=""),
                        "Prepared": breakdown["prepared_qty"],
                        "Total": breakdown["total_qty"],
                        "Unprepped": breakdown["remaining_qty"],
                        "Status": breakdown["status_label"],
                        "Reserved Detail": breakdown["detail"],
                    }
                )

        booked_out = total_qty > 0 and (booked_out_qty / total_qty) >= 0.5
        return {
            "prepared_qty": prepared_total,
            "total_qty": total_qty,
            "remaining_qty": sum(safe_int(row.get("Unprepped"), 0) for row in unprepped_items),
            "booked_out": booked_out,
            "unprepped_items": unprepped_items,
        }

    def _excluded_item_ids(self, settings):
        return {
            str(item_id).strip()
            for item_id in settings.get("current_rms", {}).get("excluded_item_ids", [])
            if str(item_id).strip()
        }

    def _item_identifier_values(self, item):
        if not isinstance(item, dict):
            return set()
        identifiers = [
            item.get("id"),
            item.get("item_id"),
            item.get("resource_item_id"),
            first_value(item, ("item", "id"), default=""),
            first_value(item, ("resource_item", "id"), default=""),
        ]
        return {str(identifier).strip() for identifier in identifiers if str(identifier).strip()}

    def _item_is_excluded(self, item, excluded_ids):
        return bool(excluded_ids and self._item_identifier_values(item).intersection(excluded_ids))

    def _prep_item_breakdown(self, item):
        line_total = safe_int(first_value(item, "quantity", "quantity_total", "booked_quantity", "total_quantity"), 0)
        status_code = safe_int(first_value(item, "status", "status_id", default=0), 0)
        status_name = str(first_value(item, "status_name", default="")).strip()
        assets = item.get("item_assets") if isinstance(item.get("item_assets"), list) else []

        if assets:
            prepared_qty = 0
            remaining_qty = 0
            booked_out_qty = 0
            active_total = 0
            detail_parts = []
            status_labels = {}

            for asset in assets:
                asset_status = safe_int(first_value(asset, "status", "status_id", default=0), 0)
                asset_status_name = str(first_value(asset, "status_name", default="")).strip()
                qty = safe_int(first_value(asset, "quantity", "quantity_total", default=0), 0)
                if qty <= 0 or asset_status in CANCELLED_STATUS_CODES:
                    continue

                active_total += qty
                if asset_status in PREPARED_STATUS_CODES:
                    prepared_qty += qty
                if asset_status == 20:
                    booked_out_qty += qty
                if asset_status in NOT_PREPARED_STATUS_CODES:
                    remaining_qty += qty
                    status_labels[asset_status_name or str(asset_status)] = True
                    asset_label = first_value(
                        asset,
                        "stock_level_asset_number",
                        "asset_number",
                        "stock_level_id",
                        default=asset_status_name or "Reserved",
                    )
                    detail_parts.append(f"{asset_label} x{qty}")

            return {
                "prepared_qty": prepared_qty,
                "remaining_qty": remaining_qty,
                "total_qty": active_total or line_total,
                "booked_out_qty": booked_out_qty,
                "status_label": " / ".join(status_labels) or status_name or "Not prepared",
                "detail": ", ".join(detail_parts[:12]) + (" ..." if len(detail_parts) > 12 else ""),
            }

        if line_total <= 0 or status_code in CANCELLED_STATUS_CODES:
            return {
                "prepared_qty": 0,
                "remaining_qty": 0,
                "total_qty": 0,
                "booked_out_qty": 0,
                "status_label": status_name,
                "detail": "",
            }

        prepared_qty = line_total if status_code in PREPARED_STATUS_CODES or status_name.lower() == "prepared" else 0
        remaining_qty = line_total if status_code in NOT_PREPARED_STATUS_CODES else 0
        booked_out_qty = line_total if status_code == 20 else 0
        return {
            "prepared_qty": prepared_qty,
            "remaining_qty": remaining_qty,
            "total_qty": line_total,
            "booked_out_qty": booked_out_qty,
            "status_label": status_name or str(status_code) or "Not prepared",
            "detail": status_name or "",
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
            ("owner", "name"),
            ("owned_by", "name"),
            ("member", "name"),
            "owner_name",
            default="",
        )

    def _format_time_range(self, start, end):
        if not start or not end:
            return "No time given"
        return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    def _format_popup_datetime(self, value):
        if not value:
            return "N/A"
        return value.strftime("%d %b %Y %H:%M")

    def _format_date(self, value):
        if not value:
            return "Unknown"
        return value.strftime("%d-%m-%Y")

    def _format_quantity(self, value):
        try:
            number = float(value)
        except Exception:
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}".rstrip("0").rstrip(".")

    def _reset_history_if_new_day(self, settings):
        today = datetime.now().date()
        if self._history_day == today:
            return
        self._history_day = today
        self._history = []
