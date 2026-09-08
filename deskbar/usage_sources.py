from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


CANONICAL_PROVIDERS = {
    "openai": "Codex",
    "claude": "Claude",
    "antigravity": "Antigravity",
    "custom": "Custom",
}
PROVIDER_ALIASES = {"codex": "openai"}
LEGACY_SOURCE_IDS = {
    "claude": "legacy-claude",
    "antigravity": "legacy-antigravity",
    "openai": "legacy-openai",
}
LEGACY_METRICS = {
    "claude": ("session", "weekly", "fable"),
    "antigravity": ("5h", "weekly"),
    "openai": ("weekly",),
}
CREATE_FIELDS = {
    "provider",
    "provider_account_id",
    "display_name",
    "order",
    "visible",
    "enabled",
    "selected_metrics",
    "stale_after_hours",
    "hide_when_stale",
    "archived",
}
UPDATE_FIELDS = {
    "display_name",
    "order",
    "visible",
    "enabled",
    "selected_metrics",
    "stale_after_hours",
    "hide_when_stale",
    "archived",
}
IMMUTABLE_UPDATE_FIELDS = {
    "source_id",
    "provider",
    "provider_account_id",
    "created_at",
    "observation",
    "token_set",
    "_token_sha256",
}
METRIC_FIELDS = {"used_pct", "resets_at", "window_start", "window_end"}
METRIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
TOKEN_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SOURCES = 64
MAX_METRICS = 12
MAX_NAME_LEN = 80
MAX_ID_LEN = 160
DEFAULT_STALE_AFTER_HOURS = 24
MAX_STALE_AFTER_HOURS = 720
MutationResult = tuple[bool, Callable[[list[dict[str, Any]]], Any]]
LegacyFlagSnapshot = dict[str, dict[str, Any]]


class UsageSourceRecoveryRequiredError(RuntimeError):
    """Raised when a runtime rollback cannot restore the usage source registry."""


class UsageSourceStore:
    """Persistent registry for AI usage sources and their latest observations."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self.load_error: str | None = None
        self._sources: list[dict[str, Any]] = []
        if self.path is not None:
            self._load_initial()

    def list_sources(self, include_archived: bool = False) -> list[dict[str, Any]]:
        if not isinstance(include_archived, bool):
            raise ValueError("include_archived must be a bool")
        with self._lock:
            if self.load_error:
                raise ValueError("usage sources store unavailable")
            now = _utcnow()
            ordered = sorted(
                self._sources,
                key=lambda item: (item["order"], item["created_at"]),
            )
            sources = [
                _public_source(source, now)
                for source in ordered
                if include_archived or not source["archived"]
            ]
            return sources

    def create_source(self, data: dict[str, Any]) -> dict[str, Any]:
        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            source = _build_source(data, staged)
            staged.append(source)
            source_id = source["source_id"]
            return (
                True,
                lambda sources: _public_source(_find_source(sources, source_id), _utcnow()),
            )

        return self._mutate(mutate)

    def update_source(self, source_id: str, data: dict[str, Any]) -> dict[str, Any]:
        _validate_source_id_input(source_id)
        if not isinstance(data, dict):
            raise ValueError("source update must be an object")
        immutable = IMMUTABLE_UPDATE_FIELDS.intersection(data)
        if immutable:
            raise ValueError("source identity field is immutable")
        unknown = set(data) - UPDATE_FIELDS
        if unknown:
            raise ValueError("unknown source update field")

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            source = _find_source(staged, source_id)
            patched = copy.deepcopy(source)
            _apply_mutable_fields(patched, data)
            patched["updated_at"] = _iso(_utcnow())
            index = staged.index(source)
            staged[index] = patched
            return (
                True,
                lambda sources: _public_source(_find_source(sources, source_id), _utcnow()),
            )

        return self._mutate(mutate)

    def reorder_sources(self, source_ids: list[str]) -> list[dict[str, Any]]:
        desired_ids = _validate_reorder_source_ids(source_ids)

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            active_ids = {
                source["source_id"]
                for source in staged
                if not source["archived"]
            }
            if set(desired_ids) != active_ids:
                raise ValueError("source_ids must exactly match active usage sources")

            changed = False
            source_by_id = {source["source_id"]: source for source in staged}
            for order, source_id in enumerate(desired_ids):
                source = source_by_id[source_id]
                if source["order"] != order:
                    source["order"] = order
                    changed = True

            return changed, _active_sources_result

        return self._mutate(mutate)

    def observe(self, source_id: str, data: dict[str, Any]) -> dict[str, Any]:
        _validate_source_id_input(source_id)

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            source = _find_source(staged, source_id)
            _ensure_observable(source)
            now = _utcnow()
            observation, observed_dt = _validate_observation_payload(
                data,
                expected_account_id=source["provider_account_id"],
                now=now,
                received_at=_iso(now),
            )
            existing_dt = _existing_observed_at(source)
            if existing_dt is not None and observed_dt <= existing_dt:
                return (
                    False,
                    lambda sources: {
                        "accepted": False,
                        "source": _public_source(_find_source(sources, source_id), _utcnow()),
                    },
                )
            source["observation"] = observation
            source["updated_at"] = _iso(now)
            return (
                True,
                lambda sources: {
                    "accepted": True,
                    "source": _public_source(_find_source(sources, source_id), _utcnow()),
                },
            )

        return self._mutate(mutate)

    def rotate_token(self, source_id: str) -> dict[str, Any]:
        _validate_source_id_input(source_id)
        plaintext = secrets.token_urlsafe(32)
        digest = _hash_token(plaintext)

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            source = _find_source(staged, source_id)
            if source["archived"]:
                raise ValueError("archived source cannot rotate token")
            source["_token_sha256"] = digest
            source["updated_at"] = _iso(_utcnow())
            return (
                True,
                lambda sources: {
                    "source_id": source_id,
                    "token": plaintext,
                    "source": _public_source(_find_source(sources, source_id), _utcnow()),
                },
            )

        return self._mutate(mutate)

    def verify_token(self, source_id: str, token: str) -> bool:
        _validate_source_id_input(source_id)
        if not isinstance(token, str) or token == "":
            return False
        with self._lock:
            source = _find_source(self._sources, source_id)
            expected = source.get("_token_sha256") or ("0" * 64)
            actual = _hash_token(token)
            matched = hmac.compare_digest(actual, expected)
            return bool(
                matched
                and source["enabled"]
                and not source["archived"]
                and source.get("_token_sha256")
            )

    def ingest_legacy(
        self,
        payload: dict[str, Any],
        enabled_providers: list[str] | tuple[str, ...],
        *,
        sync_enabled: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("legacy payload must be an object")
        if not isinstance(sync_enabled, bool):
            raise ValueError("sync_enabled must be a bool")
        enabled = _normalize_enabled_providers(enabled_providers)
        observations = _extract_legacy_observations(payload)

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            changed = False
            accepted_source_ids: list[str] = []
            now = _utcnow()

            if sync_enabled:
                changed = _sync_legacy_enabled_in_place(staged, enabled, now) or changed

            for item in observations:
                source, source_created = _resolve_legacy_source(staged, item, enabled, now)
                changed = changed or source_created
                if source is None:
                    continue
                if source["archived"] or not source["enabled"]:
                    continue
                existing_dt = _existing_observed_at(source)
                if existing_dt is not None and item["observed_dt"] <= existing_dt:
                    continue
                source["observation"] = {
                    "provider_account_id": item["provider_account_id"],
                    "observed_at": item["observed_at"],
                    "received_at": _iso(now),
                    "metrics": copy.deepcopy(item["metrics"]),
                }
                source["updated_at"] = _iso(now)
                changed = True
                accepted_source_ids.append(source["source_id"])
                if item["provider"] == "openai" and item["provider_account_id"]:
                    changed = _hide_empty_openai_legacy_source(staged, now) or changed

            return (
                changed,
                lambda sources: {
                    "accepted_source_ids": accepted_source_ids,
                    "sources": [
                        _public_source(_find_source(sources, source_id), _utcnow())
                        for source_id in accepted_source_ids
                    ],
                },
            )

        return self._mutate(mutate)

    def sync_legacy_enabled(
        self,
        enabled_providers: list[str] | tuple[str, ...],
        *,
        changed_providers: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
    ) -> None:
        enabled = _normalize_enabled_providers(enabled_providers)
        providers = _normalize_provider_scope(changed_providers)

        def mutate(staged: list[dict[str, Any]]) -> MutationResult:
            changed = _sync_legacy_enabled_in_place(
                staged,
                enabled,
                _utcnow(),
                sync_visible=True,
                providers=providers,
            )
            return changed, lambda _sources: {}

        self._mutate(mutate)

    @contextmanager
    def legacy_enabled_transaction(
        self,
        enabled_providers: list[str] | tuple[str, ...],
        *,
        changed_providers: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
    ):
        enabled = _normalize_enabled_providers(enabled_providers)
        providers = _normalize_provider_scope(changed_providers)
        with self._lock:
            if self.path is None:
                rollback = self._sync_legacy_enabled_locked(self._sources, enabled, providers)
                try:
                    yield
                except BaseException:
                    self._rollback_legacy_enabled_locked(rollback)
                    raise
                return

            with self._file_lock():
                if self.load_error:
                    raise ValueError(
                        "usage sources store failed to load; refusing to overwrite persisted file"
                    )
                try:
                    current = _read_sources_from_path(self.path)
                except Exception as exc:  # noqa: BLE001 - do not overwrite a newly corrupted file.
                    self.load_error = f"usage sources load failed: {exc}"
                    raise ValueError(
                        "usage sources store failed to load; refusing to overwrite persisted file"
                    ) from exc

                rollback = self._sync_legacy_enabled_locked(current, enabled, providers)
                try:
                    yield
                except BaseException:
                    self._rollback_legacy_enabled_locked(rollback)
                    raise

    def _sync_legacy_enabled_locked(
        self,
        current: list[dict[str, Any]],
        enabled: set[str],
        providers: set[str] | None,
    ) -> LegacyFlagSnapshot | None:
        if self.load_error:
            raise ValueError("usage sources store unavailable")
        if providers is not None and not providers:
            self._sources = copy.deepcopy(current)
            return None

        rollback = _capture_legacy_flags(current, providers)
        staged = copy.deepcopy(current)
        changed = _sync_legacy_enabled_in_place(
            staged,
            enabled,
            _utcnow(),
            sync_visible=True,
            providers=providers,
        )
        if not changed:
            self._sources = copy.deepcopy(current)
            return None
        _validate_state(staged)
        if self.path is not None:
            _atomic_write_json(self.path, {"schema_version": 1, "sources": staged})
        self._sources = staged
        return rollback

    def _rollback_legacy_enabled_locked(self, rollback: LegacyFlagSnapshot | None) -> None:
        if not rollback:
            return
        staged = copy.deepcopy(self._sources)
        changed = _restore_legacy_flags_in_place(staged, rollback)
        if not changed:
            return
        _validate_state(staged)
        try:
            if self.path is not None:
                _atomic_write_json(self.path, {"schema_version": 1, "sources": staged})
            self._sources = staged
        except Exception as exc:  # noqa: BLE001 - public state records recovery is required.
            self.load_error = "usage sources rollback failed; manual recovery required"
            raise UsageSourceRecoveryRequiredError("usage sources recovery required") from exc

    def _load_initial(self) -> None:
        try:
            self._sources = _read_sources_from_path(self.path)
        except Exception as exc:  # noqa: BLE001 - load_error is the public report channel.
            self.load_error = f"usage sources load failed: {exc}"
            self._sources = []

    def _mutate(
        self,
        mutator: Callable[[list[dict[str, Any]]], MutationResult],
    ) -> Any:
        with self._lock:
            if self.path is None:
                if self.load_error:
                    raise ValueError("usage sources store unavailable")
                staged = copy.deepcopy(self._sources)
                changed, result_factory = mutator(staged)
                if changed:
                    _validate_state(staged)
                    self._sources = staged
                return result_factory(self._sources)

            with self._file_lock():
                if self.load_error:
                    raise ValueError(
                        "usage sources store failed to load; refusing to overwrite persisted file"
                    )
                try:
                    current = _read_sources_from_path(self.path)
                except Exception as exc:  # noqa: BLE001 - do not overwrite a newly corrupted file.
                    self.load_error = f"usage sources load failed: {exc}"
                    raise ValueError(
                        "usage sources store failed to load; refusing to overwrite persisted file"
                    ) from exc

                staged = copy.deepcopy(current)
                changed, result_factory = mutator(staged)
                if changed:
                    _validate_state(staged)
                    _atomic_write_json(self.path, {"schema_version": 1, "sources": staged})
                    self._sources = staged
                else:
                    self._sources = current
                return result_factory(self._sources)

    @contextmanager
    def _file_lock(self):
        assert self.path is not None
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        handle = None
        try:
            os.chmod(lock_path, 0o600)
            handle = os.fdopen(fd, "r+")
            fd = None
            with handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            if fd is not None:
                os.close(fd)


def _build_source(
    data: dict[str, Any],
    existing_sources: list[dict[str, Any]],
    *,
    source_id: str | None = None,
    legacy: bool = False,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("source data must be an object")
    unknown = set(data) - CREATE_FIELDS
    if unknown:
        raise ValueError("unknown source field")
    if len(existing_sources) >= MAX_SOURCES:
        raise ValueError("maximum usage source count exceeded")
    if "provider" not in data:
        raise ValueError("source provider is required")

    provider = _normalize_provider(data["provider"])
    provider_account_id = _validate_optional_id(
        data.get("provider_account_id"),
        "provider_account_id",
    )
    _ensure_unique_provider_account(existing_sources, provider, provider_account_id)

    generated_id = source_id or f"src_{uuid.uuid4().hex}"
    if _find_source_or_none(existing_sources, generated_id) is not None:
        raise ValueError("source_id already exists")
    _validate_source_id_value(generated_id)

    created_at = _iso(_utcnow())
    display_name = data.get("display_name")
    if display_name is None:
        display_name = _default_display_name(provider, provider_account_id, legacy=legacy)
    source = {
        "source_id": generated_id,
        "provider": provider,
        "provider_account_id": provider_account_id,
        "display_name": _validate_display_name(display_name),
        "order": _validate_order(data.get("order", _next_order(existing_sources))),
        "visible": _validate_bool(data.get("visible", True), "visible"),
        "enabled": _validate_bool(data.get("enabled", True), "enabled"),
        "selected_metrics": _validate_selected_metrics(data.get("selected_metrics", [])),
        "stale_after_hours": _validate_stale_after_hours(
            data.get("stale_after_hours", DEFAULT_STALE_AFTER_HOURS)
        ),
        "hide_when_stale": _validate_bool(data.get("hide_when_stale", True), "hide_when_stale"),
        "archived": _validate_bool(data.get("archived", False), "archived"),
        "observation": None,
        "created_at": created_at,
        "updated_at": created_at,
        "_token_sha256": None,
    }
    return source


def _apply_mutable_fields(source: dict[str, Any], data: dict[str, Any]) -> None:
    for field, value in data.items():
        if field == "display_name":
            source[field] = _validate_display_name(value)
        elif field == "order":
            source[field] = _validate_order(value)
        elif field in {"visible", "enabled", "hide_when_stale", "archived"}:
            source[field] = _validate_bool(value, field)
        elif field == "selected_metrics":
            source[field] = _validate_selected_metrics(value)
        elif field == "stale_after_hours":
            source[field] = _validate_stale_after_hours(value)


def _public_source(source: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "provider": source["provider"],
        "provider_account_id": source["provider_account_id"],
        "display_name": source["display_name"],
        "order": source["order"],
        "visible": source["visible"],
        "enabled": source["enabled"],
        "selected_metrics": list(source["selected_metrics"]),
        "stale_after_hours": source["stale_after_hours"],
        "hide_when_stale": source["hide_when_stale"],
        "archived": source["archived"],
        "observation": copy.deepcopy(source["observation"]),
        "created_at": source["created_at"],
        "updated_at": source["updated_at"],
        "token_set": bool(source.get("_token_sha256")),
        "status": _derive_status(source, now),
    }


def _derive_status(source: dict[str, Any], now: datetime) -> str:
    if not source["enabled"]:
        return "disabled"
    observation = source.get("observation")
    if observation is None:
        return "pending_observation"
    observed_at = _parse_aware_iso(observation["observed_at"], "observed_at")
    if now - observed_at > timedelta(hours=source["stale_after_hours"]):
        return "stale"
    return "ok"


def _validate_observation_payload(
    data: dict[str, Any],
    *,
    expected_account_id: str | None,
    now: datetime,
    received_at: str,
) -> tuple[dict[str, Any], datetime]:
    if not isinstance(data, dict):
        raise ValueError("observation must be an object")
    if set(data) - {"provider_account_id", "observed_at", "metrics"}:
        raise ValueError("unknown observation field")

    provider_account_id = _validate_optional_id(
        data.get("provider_account_id"),
        "provider_account_id",
    )
    if provider_account_id != expected_account_id:
        raise ValueError("observation account does not match source")
    observed_dt = _parse_aware_iso(data.get("observed_at"), "observed_at")
    if observed_dt > now + timedelta(seconds=120):
        raise ValueError("observation timestamp is too far in the future")
    metrics = _validate_metrics(data.get("metrics"))
    observation = {
        "provider_account_id": provider_account_id,
        "observed_at": _iso(observed_dt),
        "received_at": received_at,
        "metrics": metrics,
    }
    return observation, observed_dt


def _validate_metrics(metrics: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("observation metrics must be a non-empty object")
    validated: dict[str, dict[str, Any]] = {}
    for name, payload in metrics.items():
        _validate_metric_name(name)
        if not isinstance(payload, dict):
            raise ValueError("metric payload must be an object")
        unknown = set(payload) - METRIC_FIELDS
        if unknown:
            raise ValueError("unknown metric field")
        if "used_pct" not in payload:
            raise ValueError("metric used_pct is required")
        metric = {"used_pct": _validate_used_pct(payload["used_pct"])}
        if "resets_at" in payload:
            metric["resets_at"] = _iso(_parse_aware_iso(payload["resets_at"], "resets_at"))
        has_start = "window_start" in payload
        has_end = "window_end" in payload
        if has_start != has_end:
            raise ValueError("metric window_start and window_end must be supplied together")
        if has_start and has_end:
            start = _parse_aware_iso(payload["window_start"], "window_start")
            end = _parse_aware_iso(payload["window_end"], "window_end")
            if start >= end:
                raise ValueError("metric window_start must be before window_end")
            if end - start > timedelta(days=366):
                raise ValueError("metric window duration is too large")
            metric["window_start"] = _iso(start)
            metric["window_end"] = _iso(end)
        validated[name] = metric
    return validated


def _validate_used_pct(value: Any) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("metric used_pct must be a finite number")
    if value < 0 or value > 100:
        raise ValueError("metric used_pct must be between 0 and 100")
    return value


def _extract_legacy_observations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    openai_account_id = None
    if "oa_account_id" in payload and payload["oa_account_id"] is not None:
        openai_account_id = _validate_optional_id(payload["oa_account_id"], "oa_account_id")
        if openai_account_id is None:
            raise ValueError("oa_account_id must not be empty")

    for provider, metric_names in LEGACY_METRICS.items():
        metrics: dict[str, dict[str, Any]] = {}
        provider_block = payload.get(provider)
        if provider_block is not None and not isinstance(provider_block, dict):
            raise ValueError(f"legacy {provider} payload must be an object")

        for metric_name in metric_names:
            value = _legacy_metric_value(payload, provider, provider_block, metric_name)
            if value is _Missing or value is None:
                continue
            metrics[metric_name] = _legacy_metric_payload(value)

        if not metrics:
            continue
        observed_at = _legacy_observed_at(payload, provider, provider_block)
        observed_dt = _parse_aware_iso(observed_at, f"{provider} fetched_at")
        if observed_dt > _utcnow() + timedelta(seconds=120):
            raise ValueError("legacy observation timestamp is too far in the future")
        observations.append(
            {
                "provider": provider,
                "provider_account_id": openai_account_id if provider == "openai" else None,
                "observed_at": _iso(observed_dt),
                "observed_dt": observed_dt,
                "metrics": _validate_metrics(metrics),
            }
        )
    return observations


def _legacy_metric_value(
    payload: dict[str, Any],
    provider: str,
    provider_block: dict[str, Any] | None,
    metric_name: str,
) -> Any:
    if provider_block is not None and metric_name in provider_block:
        return provider_block[metric_name]
    flat_keys = (
        f"{provider}_{metric_name}",
        f"{provider}_{metric_name}_used_pct",
    )
    for key in flat_keys:
        if key in payload:
            return payload[key]
    return _Missing


def _legacy_metric_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        unknown = set(value) - METRIC_FIELDS
        if unknown:
            raise ValueError("unknown legacy metric field")
        if "used_pct" not in value:
            raise ValueError("legacy metric used_pct is required")
        return copy.deepcopy(value)
    return {"used_pct": value}


def _legacy_observed_at(
    payload: dict[str, Any],
    provider: str,
    provider_block: dict[str, Any] | None,
) -> Any:
    if provider_block is not None:
        for key in ("fetched_at", "observed_at"):
            if key in provider_block:
                return provider_block[key]
    for key in (f"{provider}_fetched_at", f"{provider}_observed_at", "fetched_at", "observed_at"):
        if key in payload:
            return payload[key]
    raise ValueError(f"legacy {provider} fetched_at is required")


def _resolve_legacy_source(
    staged: list[dict[str, Any]],
    item: dict[str, Any],
    enabled: set[str],
    now: datetime,
) -> tuple[dict[str, Any] | None, bool]:
    provider = item["provider"]
    account_id = item["provider_account_id"]
    if provider == "openai" and account_id:
        return _resolve_openai_account_source(staged, account_id, now)
    return _resolve_legacy_anonymous_source(staged, provider, enabled, now)


def _sync_legacy_enabled_in_place(
    staged: list[dict[str, Any]],
    enabled: set[str],
    now: datetime,
    *,
    sync_visible: bool = False,
    providers: set[str] | None = None,
) -> bool:
    changed = False
    provider_items = (
        LEGACY_SOURCE_IDS.items()
        if providers is None
        else ((provider, LEGACY_SOURCE_IDS[provider]) for provider in LEGACY_SOURCE_IDS if provider in providers)
    )
    for provider, legacy_id in provider_items:
        existing = _find_source_or_none(staged, legacy_id)
        if existing is None or existing["archived"]:
            continue
        source_changed = False
        target_enabled = provider in enabled
        if existing["enabled"] != target_enabled:
            existing["enabled"] = target_enabled
            source_changed = True
        if sync_visible and existing["visible"] != target_enabled:
            existing["visible"] = target_enabled
            source_changed = True
        if source_changed:
            existing["updated_at"] = _iso(now)
            changed = True
    return changed


def _capture_legacy_flags(
    sources: list[dict[str, Any]],
    providers: set[str] | None,
) -> LegacyFlagSnapshot:
    snapshot: LegacyFlagSnapshot = {}
    provider_items = (
        LEGACY_SOURCE_IDS.items()
        if providers is None
        else ((provider, LEGACY_SOURCE_IDS[provider]) for provider in LEGACY_SOURCE_IDS if provider in providers)
    )
    for _provider, source_id in provider_items:
        source = _find_source_or_none(sources, source_id)
        if source is None:
            continue
        snapshot[source_id] = {
            "enabled": source["enabled"],
            "visible": source["visible"],
            "updated_at": source["updated_at"],
        }
    return snapshot


def _restore_legacy_flags_in_place(
    staged: list[dict[str, Any]],
    snapshot: LegacyFlagSnapshot,
) -> bool:
    changed = False
    for source_id, fields in snapshot.items():
        source = _find_source_or_none(staged, source_id)
        if source is None:
            continue
        for field, value in fields.items():
            if source[field] != value:
                source[field] = value
                changed = True
    return changed


def _normalize_provider_scope(
    providers: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None,
) -> set[str] | None:
    if providers is None:
        return None
    if not isinstance(providers, (list, tuple, set, frozenset)):
        raise ValueError("changed_providers must be a list")
    return {_normalize_provider(provider) for provider in providers}


def _resolve_openai_account_source(
    staged: list[dict[str, Any]],
    account_id: str,
    now: datetime,
) -> tuple[dict[str, Any] | None, bool]:
    existing = _find_by_provider_account(staged, "openai", account_id)
    if existing is not None:
        return existing, False

    source_id = _deterministic_openai_source_id(account_id)
    tombstone = _find_source_or_none(staged, source_id)
    if tombstone is not None:
        return (None, False) if tombstone["archived"] else (tombstone, False)

    source = _build_source(
        {
            "provider": "openai",
            "provider_account_id": account_id,
            "display_name": _default_display_name("openai", account_id),
            "enabled": True,
            "visible": True,
        },
        staged,
        source_id=source_id,
        legacy=True,
    )
    source["created_at"] = _iso(now)
    source["updated_at"] = source["created_at"]
    staged.append(source)
    return source, True


def _resolve_legacy_anonymous_source(
    staged: list[dict[str, Any]],
    provider: str,
    enabled: set[str],
    now: datetime,
) -> tuple[dict[str, Any] | None, bool]:
    source_id = LEGACY_SOURCE_IDS[provider]
    existing = _find_source_or_none(staged, source_id)
    if existing is not None:
        return (None, False) if existing["archived"] else (existing, False)

    source = _build_source(
        {
            "provider": provider,
            "display_name": _default_display_name(provider, None, legacy=True),
            "enabled": provider in enabled,
            "visible": provider in enabled,
        },
        staged,
        source_id=source_id,
        legacy=True,
    )
    source["created_at"] = _iso(now)
    source["updated_at"] = source["created_at"]
    staged.append(source)
    return source, True


def _hide_empty_openai_legacy_source(staged: list[dict[str, Any]], now: datetime) -> bool:
    source = _find_source_or_none(staged, LEGACY_SOURCE_IDS["openai"])
    if (
        source is None
        or source["archived"]
        or source["observation"] is not None
        or not source["visible"]
    ):
        return False
    source["visible"] = False
    source["updated_at"] = _iso(now)
    return True


def _normalize_enabled_providers(enabled_providers: list[str] | tuple[str, ...]) -> set[str]:
    if not isinstance(enabled_providers, (list, tuple)):
        raise ValueError("enabled_providers must be a list")
    return {_normalize_provider(provider) for provider in enabled_providers}


def _normalize_provider(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("provider must be a string")
    provider = PROVIDER_ALIASES.get(value, value)
    if provider not in CANONICAL_PROVIDERS:
        raise ValueError("unknown provider")
    return provider


def _default_display_name(
    provider: str,
    provider_account_id: str | None,
    *,
    legacy: bool = False,
) -> str:
    base = CANONICAL_PROVIDERS[provider]
    if legacy and provider_account_id is None:
        return f"Legacy {base}"
    return base


def _validate_display_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("display_name must be a string")
    name = value.strip()
    if not name:
        raise ValueError("display_name must not be empty")
    if len(name) > MAX_NAME_LEN:
        raise ValueError("display_name is too long")
    return name


def _validate_optional_id(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_ID_LEN:
        raise ValueError(f"{field} is too long")
    return normalized


def _validate_source_id_input(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid source_id")
    if len(value) > MAX_ID_LEN:
        raise ValueError("invalid source_id")


def _validate_source_id_value(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LEN:
        raise ValueError("invalid source_id")


def _validate_reorder_source_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("source_ids must be a list")
    seen: set[str] = set()
    source_ids: list[str] = []
    for source_id in value:
        _validate_source_id_input(source_id)
        if source_id in seen:
            raise ValueError("source_ids must be unique")
        seen.add(source_id)
        source_ids.append(source_id)
    return source_ids


def _validate_order(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("order must be a non-negative integer")
    return value


def _validate_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a bool")
    return value


def _validate_selected_metrics(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("selected_metrics must be a list")
    if len(value) > MAX_METRICS:
        raise ValueError("too many selected metrics")
    seen: set[str] = set()
    metrics: list[str] = []
    for metric in value:
        _validate_metric_name(metric)
        if metric not in seen:
            seen.add(metric)
            metrics.append(metric)
    return metrics


def _validate_metric_name(name: Any) -> None:
    if not isinstance(name, str) or not METRIC_RE.fullmatch(name):
        raise ValueError("invalid metric name")


def _validate_stale_after_hours(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("stale_after_hours must be an integer")
    if value < 1 or value > MAX_STALE_AFTER_HOURS:
        raise ValueError("stale_after_hours is out of range")
    return value


def _parse_aware_iso(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _existing_observed_at(source: dict[str, Any]) -> datetime | None:
    observation = source.get("observation")
    if observation is None:
        return None
    return _parse_aware_iso(observation["observed_at"], "observed_at")


def _ensure_observable(source: dict[str, Any]) -> None:
    if source["archived"]:
        raise ValueError("archived source does not accept observations")
    if not source["enabled"]:
        raise ValueError("disabled source does not accept observations")


def _ensure_unique_provider_account(
    sources: list[dict[str, Any]],
    provider: str,
    provider_account_id: str | None,
) -> None:
    if provider_account_id is None:
        return
    for source in sources:
        if source["provider"] == provider and source["provider_account_id"] == provider_account_id:
            raise ValueError("provider_account_id already exists for provider")


def _find_by_provider_account(
    sources: list[dict[str, Any]],
    provider: str,
    provider_account_id: str,
) -> dict[str, Any] | None:
    for source in sources:
        if source["provider"] == provider and source["provider_account_id"] == provider_account_id:
            return source
    return None


def _find_source(sources: list[dict[str, Any]], source_id: str) -> dict[str, Any]:
    source = _find_source_or_none(sources, source_id)
    if source is None:
        raise KeyError("unknown source_id")
    return source


def _find_source_or_none(sources: list[dict[str, Any]], source_id: str) -> dict[str, Any] | None:
    for source in sources:
        if source["source_id"] == source_id:
            return source
    return None


def _active_sources_result(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = _utcnow()
    return [
        _public_source(source, now)
        for source in sorted(
            sources,
            key=lambda item: (item["order"], item["created_at"]),
        )
        if not source["archived"]
    ]


def _next_order(sources: list[dict[str, Any]]) -> int:
    if not sources:
        return 0
    return max(source["order"] for source in sources) + 1


def _deterministic_openai_source_id(provider_account_id: str) -> str:
    digest = hashlib.sha256(provider_account_id.encode("utf-8")).hexdigest()[:16]
    return f"legacy-openai-acct-{digest}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _read_sources_from_path(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("unsupported usage source store format")
    sources = raw.get("sources")
    if not isinstance(sources, list):
        raise ValueError("usage source store sources must be a list")
    staged = copy.deepcopy(sources)
    _validate_state(staged)
    return staged


def _validate_state(sources: list[dict[str, Any]]) -> None:
    if len(sources) > MAX_SOURCES:
        raise ValueError("maximum usage source count exceeded")
    seen_ids: set[str] = set()
    seen_accounts: set[tuple[str, str]] = set()
    for source in sources:
        _validate_persisted_source(source)
        source_id = source["source_id"]
        if source_id in seen_ids:
            raise ValueError("duplicate source_id")
        seen_ids.add(source_id)
        account_id = source["provider_account_id"]
        if account_id is not None:
            account_key = (source["provider"], account_id)
            if account_key in seen_accounts:
                raise ValueError("duplicate provider_account_id")
            seen_accounts.add(account_key)


def _validate_persisted_source(source: dict[str, Any]) -> None:
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    required = {
        "source_id",
        "provider",
        "provider_account_id",
        "display_name",
        "order",
        "visible",
        "enabled",
        "selected_metrics",
        "stale_after_hours",
        "hide_when_stale",
        "archived",
        "observation",
        "created_at",
        "updated_at",
        "_token_sha256",
    }
    if set(source) != required:
        raise ValueError("source store contains unexpected fields")
    _validate_source_id_value(source["source_id"])
    source["provider"] = _normalize_provider(source["provider"])
    source["provider_account_id"] = _validate_optional_id(
        source["provider_account_id"], "provider_account_id"
    )
    source["display_name"] = _validate_display_name(source["display_name"])
    source["order"] = _validate_order(source["order"])
    source["visible"] = _validate_bool(source["visible"], "visible")
    source["enabled"] = _validate_bool(source["enabled"], "enabled")
    source["selected_metrics"] = _validate_selected_metrics(source["selected_metrics"])
    source["stale_after_hours"] = _validate_stale_after_hours(source["stale_after_hours"])
    source["hide_when_stale"] = _validate_bool(source["hide_when_stale"], "hide_when_stale")
    source["archived"] = _validate_bool(source["archived"], "archived")
    _parse_aware_iso(source["created_at"], "created_at")
    _parse_aware_iso(source["updated_at"], "updated_at")
    token_hash = source.get("_token_sha256")
    if token_hash is not None and (
        not isinstance(token_hash, str) or TOKEN_DIGEST_RE.fullmatch(token_hash) is None
    ):
        raise ValueError("invalid token digest")
    if source["observation"] is not None:
        _validate_loaded_observation(source["observation"], source["provider_account_id"])


def _validate_loaded_observation(observation: Any, expected_account_id: str | None) -> None:
    if not isinstance(observation, dict):
        raise ValueError("observation must be an object")
    if set(observation) != {"provider_account_id", "observed_at", "received_at", "metrics"}:
        raise ValueError("observation contains unexpected fields")
    account_id = _validate_optional_id(observation["provider_account_id"], "provider_account_id")
    if account_id != expected_account_id:
        raise ValueError("observation account does not match source")
    _parse_aware_iso(observation["observed_at"], "observed_at")
    _parse_aware_iso(observation["received_at"], "received_at")
    observation["metrics"] = _validate_metrics(observation["metrics"])


def _atomic_write_json(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class _MissingType:
    pass


_Missing = _MissingType()


__all__ = ["UsageSourceRecoveryRequiredError", "UsageSourceStore"]
