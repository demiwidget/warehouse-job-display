from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from time import monotonic, sleep

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSPECTION_CACHE_FILE = PROJECT_ROOT / "manager_data" / "inspection_metrics.json"
CACHE_SCHEMA_VERSION = 3
SERIALISED_STOCK_CATEGORY = 50
FAILED_RETRY_MINUTES = 5


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def add_inspection_interval(start_date, schedule_type, interval):
    interval = max(1, safe_int(interval, 1))
    schedule_type = safe_int(schedule_type, 0)
    if schedule_type == 1:
        return start_date + timedelta(weeks=interval)
    if schedule_type == 2:
        month_index = (start_date.month - 1) + interval
        year = start_date.year + (month_index // 12)
        month = (month_index % 12) + 1
        day = min(start_date.day, monthrange(year, month)[1])
        return start_date.replace(year=year, month=month, day=day)
    if schedule_type == 3:
        year = start_date.year + interval
        day = min(start_date.day, monthrange(year, start_date.month)[1])
        return start_date.replace(year=year, day=day)
    return start_date + timedelta(days=interval)


def inspection_lookback_days(inspections):
    longest = 1
    for inspection in inspections.values():
        interval = max(1, safe_int(inspection.get("schedule_interval"), 1))
        schedule_type = safe_int(inspection.get("schedule_type"), 0)
        multipliers = {0: 1, 1: 7, 2: 32, 3: 367}
        longest = max(longest, interval * multipliers.get(schedule_type, 1))
    return longest + 14


def build_inspection_payload(state, config, today=None):
    today = today or date.today()
    horizon = today + timedelta(days=max(0, safe_int(config.get("due_within_days"), 0)))
    inspections = {
        str(key): value
        for key, value in (state.get("inspections", {}) or {}).items()
        if isinstance(value, dict) and value.get("active", True)
    }
    latest_results = state.get("latest_results", {}) or {}
    mappings = {
        str(key).strip(): str(value).strip()
        for key, value in (config.get("department_mappings", {}) or {}).items()
        if str(key).strip() and str(value).strip()
    }
    excluded = {
        str(value).strip()
        for value in config.get("excluded_department_ids", []) or []
        if str(value).strip()
    }
    counts = {department_id: 0 for department_id in mappings if department_id not in excluded}
    unassigned_count = 0

    groups = state.get("groups", []) or []
    if groups:
        group_by_product = {}
        compliant = {}
        for group in groups:
            department_id = str(group.get("department_id") or "").strip() or "Unassigned"
            inspection_id = str(group.get("inspection_id") or "")
            group_key = f"{department_id}:{inspection_id}"
            compliant[group_key] = 0
            for product_id in group.get("product_ids", []) or []:
                group_by_product[(str(product_id), inspection_id)] = group_key

        for result in latest_results.values():
            inspection_id = str(result.get("inspection_id") or "")
            inspection = inspections.get(inspection_id)
            group_key = group_by_product.get((str(result.get("product_id") or ""), inspection_id))
            if not inspection or not group_key:
                continue
            inspected_at = parse_datetime(result.get("inspection_at"))
            if not inspected_at or result.get("passed") is not True:
                continue
            next_due = add_inspection_interval(
                inspected_at.date(),
                inspection.get("schedule_type"),
                inspection.get("schedule_interval"),
            )
            if next_due > horizon:
                compliant[group_key] = compliant.get(group_key, 0) + 1

        for group in groups:
            department_id = str(group.get("department_id") or "").strip() or "Unassigned"
            if department_id in excluded:
                continue
            inspection_id = str(group.get("inspection_id") or "")
            group_key = f"{department_id}:{inspection_id}"
            due = max(0, safe_int(group.get("total_assets"), 0) - compliant.get(group_key, 0))
            counts[department_id] = counts.get(department_id, 0) + due
            if department_id == "Unassigned":
                unassigned_count += due
    else:
        # Retain support for caches created before grouped inspection counting.
        for asset in state.get("assets", []) or []:
            department_id = str(asset.get("department_id") or "").strip() or "Unassigned"
            if department_id in excluded:
                continue
            for inspection_id in asset.get("inspection_ids", []) or []:
                inspection_id = str(inspection_id)
                inspection = inspections.get(inspection_id)
                if not inspection:
                    continue
                result = latest_results.get(f"{asset.get('stock_level_id')}:{inspection_id}")
                due = not result
                if result:
                    inspected_at = parse_datetime(result.get("inspection_at"))
                    if not inspected_at or result.get("passed") is not True:
                        due = True
                    else:
                        next_due = add_inspection_interval(
                            inspected_at.date(),
                            inspection.get("schedule_type"),
                            inspection.get("schedule_interval"),
                        )
                        due = next_due <= horizon
                if due:
                    counts[department_id] = counts.get(department_id, 0) + 1
                    if department_id == "Unassigned":
                        unassigned_count += 1

    rows = []
    for department_id, count in counts.items():
        if department_id == "Unassigned" and not config.get("show_unassigned", True):
            continue
        rows.append(
            {
                "Tag": department_id,
                "Department": mappings.get(department_id) or (
                    "Unassigned" if department_id == "Unassigned" else f"Department {department_id}"
                ),
                "Inspections": count,
            }
        )
    rows.sort(key=lambda row: str(row.get("Department", "")).lower())

    total = sum(safe_int(row.get("Inspections"), 0) for row in rows)
    updated_at = str(state.get("results_synced_at") or state.get("catalog_refreshed_at") or "")
    status = "Current"
    if updated_at:
        parsed = parse_datetime(updated_at)
        if parsed:
            status = f"Updated {parsed.strftime('%H:%M')}"
    return {
        "title": "Inspections",
        "summary": {
            "Total": total,
            "Departments": len(rows),
            "Unassigned": unassigned_count,
            "Status": status,
            "Last Updated": updated_at,
        },
        "rows": rows,
    }


class InspectionMetrics:
    def __init__(self, cache_file=INSPECTION_CACHE_FILE):
        self.cache_file = Path(cache_file)
        self.lock = Lock()
        self.worker = None
        self.state = self._load_state()
        self.progress = {}
        self.last_request_at = 0.0

    @staticmethod
    def empty_payload(status="Calculating inspection counts in the background"):
        return {
            "title": "Inspections",
            "summary": {
                "Total": 0,
                "Departments": 0,
                "Unassigned": 0,
                "Status": status,
                "Last Updated": "",
            },
            "rows": [],
        }

    def _load_state(self):
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.cache_file.parent,
                prefix=f".{self.cache_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(state, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(self.cache_file)
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _config(settings):
        return settings.get("current_rms", {}).get("inspections", {}) or {}

    @staticmethod
    def _source_fingerprint(client, config):
        source = {
            "cache_schema": CACHE_SCHEMA_VERSION,
            "api_base": client.api_base,
            "subdomain": client.subdomain,
            "department_field": str(config.get("department_field") or "prep_department").strip(),
        }
        return sha256(json.dumps(source, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _age_minutes(value):
        parsed = parse_datetime(value)
        if not parsed:
            return math.inf
        return max(0.0, (datetime.now() - parsed).total_seconds() / 60.0)

    def _set_progress(self, stage, current=0, total=0, detail=""):
        progress = {
            "stage": str(stage or "Calculating inspection counts"),
            "current": max(0, safe_int(current, 0)),
            "total": max(0, safe_int(total, 0)),
            "detail": str(detail or "").strip(),
        }
        with self.lock:
            self.progress = progress

    @staticmethod
    def _progress_status(progress):
        stage = str(progress.get("stage") or "Calculating inspection counts")
        current = safe_int(progress.get("current"), 0)
        total = safe_int(progress.get("total"), 0)
        detail = str(progress.get("detail") or "").strip()
        if total > 0:
            status = f"{stage}: {min(current, total)}/{total}"
        else:
            status = stage
        return f"{status} ({detail})" if detail else status

    def payload(self, client, settings):
        config = self._config(settings)
        if not config.get("enabled", True):
            return self.empty_payload("Disabled in PC Manager")

        fingerprint = self._source_fingerprint(client, config)
        with self.lock:
            state = deepcopy(self.state)
            progress = deepcopy(self.progress)
            worker_running = bool(self.worker and self.worker.is_alive())

        source_changed = state.get("source_fingerprint") != fingerprint
        full_refresh = source_changed or not state.get("catalog_refreshed_at") or (
            self._age_minutes(state.get("catalog_refreshed_at"))
            >= max(1, safe_int(config.get("catalog_refresh_hours"), 24)) * 60
        )
        results_stale = (
            self._age_minutes(state.get("results_synced_at"))
            >= max(1, safe_int(config.get("refresh_minutes"), 15))
        )
        retry_due = not state.get("last_error") or (
            self._age_minutes(state.get("last_attempt_at")) >= FAILED_RETRY_MINUTES
        )
        if (full_refresh or results_stale) and not worker_running and retry_due:
            worker = Thread(
                target=self._refresh_worker,
                args=(client, deepcopy(config), fingerprint, full_refresh),
                daemon=True,
                name="inspection-metrics-refresh",
            )
            with self.lock:
                self.worker = worker
            worker.start()
            worker_running = True

        if source_changed:
            if state.get("last_error") and not worker_running:
                payload = self.empty_payload("Inspection update failed; retrying automatically")
                payload["summary"]["Error"] = str(state.get("last_error"))
                return payload
            status = self._progress_status(progress) if progress else "Starting inspection calculation"
            return self.empty_payload(status)

        payload = build_inspection_payload(state, config)
        if worker_running:
            payload["summary"]["Status"] = self._progress_status(progress)
        if state.get("last_error"):
            payload["summary"]["Status"] = "Update failed; showing cached counts"
            payload["summary"]["Error"] = str(state.get("last_error"))
        return payload

    def _refresh_worker(self, client, config, fingerprint, full_refresh):
        attempted_at = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self.state["last_attempt_at"] = attempted_at
        self._set_progress("Starting inspection calculation")
        try:
            with self.lock:
                state = deepcopy(self.state)
            if state.get("source_fingerprint") != fingerprint:
                state = {}
                full_refresh = True
            if full_refresh:
                state = self._full_refresh(client, config, fingerprint)
            else:
                state = self._incremental_results_refresh(client, config, state)
            state["last_error"] = ""
            state["last_attempt_at"] = attempted_at
            state["payload"] = build_inspection_payload(state, config)
            self._save_state(state)
            with self.lock:
                self.state = state
            self._set_progress("Inspection counts ready", 1, 1)
        except Exception as error:
            with self.lock:
                state = deepcopy(self.state)
                state["last_error"] = str(error)
                state["last_attempt_at"] = attempted_at
                self.state = state
            self._set_progress("Inspection update failed", detail=str(error))
            try:
                self._save_state(state)
            except Exception:
                pass

    def _request_json(self, client, path, params, config):
        gap = max(0.2, min(10.0, float(config.get("request_gap_seconds", 1.5) or 1.5)))
        elapsed = monotonic() - self.last_request_at
        if elapsed < gap:
            sleep(gap - elapsed)

        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(
                    f"{client.api_base}/{path.lstrip('/')}",
                    headers=client.headers(),
                    params=params,
                    timeout=30,
                )
                self.last_request_at = monotonic()
                if response.status_code == 429:
                    reset = safe_int(response.headers.get("X-RateLimit-Reset"), 0)
                    wait_seconds = max(5, min(65, reset - int(datetime.now().timestamp()))) if reset else 15
                    sleep(wait_seconds)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt < 2:
                    sleep(3 * (attempt + 1))
        raise RuntimeError(f"Current RMS {path} request failed: {last_error}")

    def _fetch_pages(
        self,
        client,
        path,
        query,
        config,
        max_pages=1000,
        progress_label="",
        row_handler=None,
    ):
        rows = []
        fetched = 0
        collection_name = path.strip("/").split("/")[-1]
        for page in range(1, max_pages + 1):
            params = [("page", page), ("per_page", 100), *list(query)]
            payload = self._request_json(client, path, params, config)
            page_rows = payload.get(collection_name, []) or []
            fetched += len(page_rows)
            if row_handler:
                row_handler(page_rows)
            else:
                rows.extend(page_rows)
            meta = payload.get("meta", {}) or {}
            total = safe_int(meta.get("total_row_count"), fetched)
            total_pages = max(1, math.ceil(total / 100))
            if progress_label:
                self._set_progress(progress_label, page, total_pages, f"{min(fetched, total)} of {total}")
            if fetched >= total or not page_rows:
                return rows
        raise RuntimeError(f"Current RMS {collection_name} scan exceeded {max_pages} pages")

    def _count_rows(self, client, path, query, config):
        payload = self._request_json(
            client,
            path,
            [("page", 1), ("per_page", 1), *list(query)],
            config,
        )
        return safe_int((payload.get("meta", {}) or {}).get("total_row_count"), 0)

    def _full_refresh(self, client, config, fingerprint):
        started_at = datetime.now()
        inspections = self._fetch_pages(
            client,
            "inspections",
            [],
            config,
            max_pages=10,
            progress_label="Reading inspection types",
        )
        inspection_map = {
            str(item.get("id")): {
                "name": str(item.get("name") or ""),
                "active": bool(item.get("active", True)),
                "schedule_type": safe_int(item.get("schedule_type"), 0),
                "schedule_interval": max(1, safe_int(item.get("schedule_interval"), 1)),
            }
            for item in inspections
            if item.get("id") not in (None, "")
        }
        active_ids = {key for key, value in inspection_map.items() if value.get("active")}
        if not active_ids:
            return {
                "schema_version": CACHE_SCHEMA_VERSION,
                "source_fingerprint": fingerprint,
                "catalog_refreshed_at": started_at.isoformat(timespec="seconds"),
                "results_synced_at": started_at.isoformat(timespec="seconds"),
                "inspections": inspection_map,
                "groups": [],
                "latest_results": {},
            }

        products = self._fetch_pages(
            client,
            "products",
            [("q[stock_method_eq]", 2)],
            config,
            max_pages=max(1, safe_int(config.get("max_catalog_pages"), 100)),
            progress_label="Reading inspection products",
        )
        department_field = str(config.get("department_field") or "prep_department").strip()
        products_by_id = {}
        for product in products:
            assigned = [
                str(value)
                for value in product.get("assigned_inspection_ids", []) or []
                if str(value) in active_ids
            ]
            if not assigned or product.get("active") is False:
                continue
            product_fields = product.get("custom_fields", {}) or {}
            group_fields = (product.get("product_group") or {}).get("custom_fields", {}) or {}
            department_id = str(
                product_fields.get(department_field) or group_fields.get(department_field) or ""
            ).strip() or "Unassigned"
            products_by_id[str(product.get("id"))] = {
                "department_id": department_id,
                "inspection_ids": assigned,
            }

        grouped_products = {}
        for product_id, product in products_by_id.items():
            for inspection_id in product["inspection_ids"]:
                key = (product["department_id"], inspection_id)
                grouped_products.setdefault(key, []).append(product_id)

        groups = []
        product_batch_size = max(1, min(60, safe_int(config.get("product_batch_size"), 40)))
        total_count_batches = sum(
            math.ceil(len(product_ids) / product_batch_size)
            for product_ids in grouped_products.values()
        )
        completed_batches = 0
        for (department_id, inspection_id), product_ids in sorted(grouped_products.items()):
            total_assets = 0
            product_ids = sorted(set(product_ids))
            for offset in range(0, len(product_ids), product_batch_size):
                batch = product_ids[offset : offset + product_batch_size]
                query = [
                    ("q[stock_category_eq]", SERIALISED_STOCK_CATEGORY),
                    ("q[quantity_held_gt]", 0),
                    ("q[container_stock_level_id_null]", 1),
                    *[("q[item_id_in][]", product_id) for product_id in batch],
                ]
                total_assets += self._count_rows(client, "stock_levels", query, config)
                completed_batches += 1
                self._set_progress(
                    "Counting serialised assets",
                    completed_batches,
                    total_count_batches,
                    f"{department_id} / inspection {inspection_id}",
                )
            groups.append(
                {
                    "department_id": department_id,
                    "inspection_id": inspection_id,
                    "product_ids": product_ids,
                    "total_assets": total_assets,
                }
            )

        latest_results = self._baseline_grouped_results(
            client,
            config,
            products_by_id,
            inspection_map,
        )
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "source_fingerprint": fingerprint,
            "catalog_refreshed_at": started_at.isoformat(timespec="seconds"),
            "results_synced_at": datetime.now().isoformat(timespec="seconds"),
            "inspections": inspection_map,
            "groups": groups,
            "latest_results": latest_results,
        }

    def _baseline_grouped_results(self, client, config, products_by_id, inspections):
        latest = {}
        active_inspections = [
            (inspection_id, inspection)
            for inspection_id, inspection in inspections.items()
            if inspection.get("active", True)
        ]
        for index, (inspection_id, inspection) in enumerate(active_inspections, start=1):
            cutoff = (
                date.today()
                - timedelta(days=inspection_lookback_days({inspection_id: inspection}))
            ).isoformat()
            query = [
                ("q[inspection_id_eq]", inspection_id),
                ("q[inspection_at_gteq]", cutoff),
                ("q[stock_level_quantity_held_gt]", 0),
                ("q[stock_level_container_stock_level_id_null]", 1),
                ("q[s]", "inspection_at asc"),
            ]
            self._fetch_pages(
                client,
                "inspection_results",
                query,
                config,
                progress_label=(
                    f"Reading results {index}/{len(active_inspections)}: "
                    f"{inspection.get('name') or inspection_id}"
                ),
                row_handler=lambda page_rows, target_id=inspection_id: self._merge_grouped_results(
                    latest,
                    page_rows,
                    products_by_id,
                    {target_id},
                ),
            )
        return latest

    def _incremental_results_refresh(self, client, config, state):
        started_at = datetime.now()
        previous_sync = parse_datetime(state.get("results_synced_at"))
        if not previous_sync:
            return self._full_refresh(client, config, state.get("source_fingerprint", ""))
        since = (previous_sync - timedelta(minutes=5)).isoformat(timespec="seconds")
        query = [("q[updated_at_gteq]", since), ("q[s]", "updated_at asc")]
        rows = self._fetch_pages(
            client,
            "inspection_results",
            query,
            config,
            progress_label="Reading changed inspection results",
        )
        products_by_id = self._products_from_groups(state.get("groups", []) or [])
        inspection_ids = set((state.get("inspections", {}) or {}).keys())
        latest = dict(state.get("latest_results", {}) or {})
        self._merge_grouped_results(latest, rows, products_by_id, inspection_ids)
        state["latest_results"] = latest
        state["results_synced_at"] = started_at.isoformat(timespec="seconds")
        return state

    @staticmethod
    def _products_from_groups(groups):
        products = {}
        for group in groups:
            inspection_id = str(group.get("inspection_id") or "")
            department_id = str(group.get("department_id") or "").strip() or "Unassigned"
            for product_id in group.get("product_ids", []) or []:
                product = products.setdefault(
                    str(product_id),
                    {"department_id": department_id, "inspection_ids": []},
                )
                if inspection_id and inspection_id not in product["inspection_ids"]:
                    product["inspection_ids"].append(inspection_id)
        return products

    @staticmethod
    def _merge_grouped_results(latest, rows, products_by_id, inspection_ids):
        for result in rows:
            inspection_id = str(result.get("inspection_id") or "")
            stock_level = result.get("stock_level") or {}
            stock_id = str(result.get("stock_level_id") or stock_level.get("id") or "")
            product_id = str(stock_level.get("item_id") or "")
            product = products_by_id.get(product_id)
            if (
                not stock_id
                or inspection_id not in inspection_ids
                or not product
                or inspection_id not in product.get("inspection_ids", [])
                or safe_int(stock_level.get("stock_category"), 0) != SERIALISED_STOCK_CATEGORY
                or safe_int(stock_level.get("quantity_held"), 0) <= 0
                or stock_level.get("container_stock_level_id") not in (None, "")
            ):
                continue
            key = f"{stock_id}:{inspection_id}"
            current = latest.get(key, {})
            current_at = parse_datetime(current.get("inspection_at")) or datetime.min
            result_at = parse_datetime(result.get("inspection_at")) or datetime.min
            if result_at >= current_at:
                latest[key] = {
                    "id": str(result.get("id") or ""),
                    "stock_level_id": stock_id,
                    "product_id": product_id,
                    "inspection_id": inspection_id,
                    "inspection_at": str(result.get("inspection_at") or ""),
                    "passed": result.get("passed"),
                }

    @staticmethod
    def _merge_latest_results(latest, rows, stock_ids, inspection_ids):
        for result in rows:
            stock_id = str(result.get("stock_level_id") or "")
            inspection_id = str(result.get("inspection_id") or "")
            if stock_id not in stock_ids or inspection_id not in inspection_ids:
                continue
            key = f"{stock_id}:{inspection_id}"
            current = latest.get(key, {})
            current_at = parse_datetime(current.get("inspection_at")) or datetime.min
            result_at = parse_datetime(result.get("inspection_at")) or datetime.min
            if result_at >= current_at:
                latest[key] = {
                    "id": str(result.get("id") or ""),
                    "inspection_at": str(result.get("inspection_at") or ""),
                    "passed": result.get("passed"),
                }
