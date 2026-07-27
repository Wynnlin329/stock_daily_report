from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any


POLICY_RELATIVE_PATH = Path("data/chatgpt/position-management-policy-v1.json")
FULL_EXIT_EVENT_TYPES = {
    "initial_stop_exit",
    "break_even_exit",
    "trailing_ma_exit",
}
REQUIRED_OUTPUT_FIELDS = {
    "days_since_entry",
    "current_r",
    "max_r_reached",
    "max_close_since_entry",
    "partial_exit_due",
    "partial_exit_ratio",
    "break_even_stop_activated",
    "active_trailing_ma",
    "close_below_trailing_ma",
    "position_stage",
    "exit_model",
    "exit_signal",
    "exit_reason",
    "model_comparison_snapshot",
}


def load_position_management_policy(root: Path | str = ".") -> dict[str, Any]:
    with (Path(root) / POLICY_RELATIVE_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_position_management_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "policy_id",
        "version",
        "schema_version",
        "status",
        "official_model",
        "shadow_models",
        "models",
        "risk_calculation",
        "state_order",
        "event_types",
        "idempotency",
        "immutable_fields",
        "output_fields",
        "validation_rules",
    }
    missing = sorted(required - policy.keys())
    if missing:
        errors.append("missing_sections:" + ",".join(missing))

    models = policy.get("models", {})
    official_model = policy.get("official_model")
    shadow_models = policy.get("shadow_models", [])
    if official_model not in models:
        errors.append("official_model_missing")
    if any(model not in models for model in shadow_models):
        errors.append("shadow_model_missing")
    if official_model in shadow_models:
        errors.append("official_model_cannot_be_shadow")
    if models.get(official_model, {}).get("role") != "official_simulation":
        errors.append("official_model_role_invalid")
    for model in shadow_models:
        if models.get(model, {}).get("role") != "shadow_comparison_only":
            errors.append(f"shadow_model_role_invalid:{model}")

    rules = policy.get("validation_rules", {})
    ratio_min = rules.get("partial_exit_ratio_minimum")
    ratio_max = rules.get("partial_exit_ratio_maximum")
    allowed_mas = set(rules.get("allowed_trailing_moving_averages", []))
    for model_id, model in models.items():
        ratio = model.get("partial_exit", {}).get("ratio")
        if (
            not _is_number(ratio)
            or not _is_number(ratio_min)
            or not _is_number(ratio_max)
            or not ratio_min <= ratio <= ratio_max
        ):
            errors.append(f"partial_exit_ratio_invalid:{model_id}")
        moving_average = model.get("trailing_exit", {}).get("moving_average")
        if moving_average not in allowed_mas:
            errors.append(f"trailing_ma_invalid:{model_id}")
        if model.get("trailing_exit", {}).get("close_confirmation_required") is not True:
            errors.append(f"close_confirmation_required:{model_id}")

    qullamaggie = models.get("qullamaggie_3_5d_shadow", {})
    partial = qullamaggie.get("partial_exit", {})
    if (
        partial.get("trigger_type") != "trading_day_window"
        or partial.get("minimum_day") != 3
        or partial.get("maximum_day") != 5
    ):
        errors.append("qullamaggie_day_window_invalid")

    plus_2r = models.get("plus_2r_v1", {}).get("partial_exit", {})
    if (
        plus_2r.get("trigger_type") != "r_multiple"
        or plus_2r.get("trigger_metric") != "max_r_reached"
        or not _is_number(plus_2r.get("trigger_r"))
    ):
        errors.append("plus_2r_trigger_invalid")

    if set(policy.get("immutable_fields", [])) != {"entry_price", "initial_stop"}:
        errors.append("immutable_fields_invalid")
    risk = policy.get("risk_calculation", {})
    if (
        risk.get("entry_source") != "entry_price"
        or risk.get("stop_source") != "initial_stop"
        or risk.get("trigger_is_entry_forbidden") is not True
    ):
        errors.append("risk_source_invalid")
    if rules.get("real_trading_forbidden") is not True:
        errors.append("real_trading_must_be_forbidden")
    missing_output_fields = REQUIRED_OUTPUT_FIELDS - set(
        policy.get("output_fields", [])
    )
    if missing_output_fields:
        errors.append(
            "missing_output_fields:" + ",".join(sorted(missing_output_fields))
        )
    return errors


def evaluate_position_management(
    position: dict[str, Any],
    price_history: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_position_management_policy()
    policy_errors = validate_position_management_policy(active_policy)
    if policy_errors:
        raise ValueError("invalid position management policy: " + ",".join(policy_errors))

    entry_price = position.get("entry_price")
    initial_stop = position.get("initial_stop")
    trigger_reference = position.get("trigger_reference")
    symbol = str(position.get("symbol") or "")
    bars = _normalized_bars(price_history, position.get("entry_date"))
    metrics, metric_errors = _position_metrics(
        position,
        bars,
        entry_price,
        initial_stop,
    )
    previous_models = (
        (previous_snapshot or {})
        .get("model_comparison_snapshot", {})
        .get("models", {})
    )
    completed_event_ids = set(position.get("completed_event_ids") or [])

    model_results: dict[str, dict[str, Any]] = {}
    for model_id, model_policy in active_policy["models"].items():
        model_results[model_id] = _evaluate_model(
            symbol=symbol,
            position=position,
            metrics=metrics,
            metric_errors=metric_errors,
            model_id=model_id,
            model_policy=model_policy,
            previous_model=previous_models.get(model_id, {}),
            completed_event_ids=completed_event_ids,
        )

    official_model = active_policy["official_model"]
    official = model_results[official_model]
    shadow_models = active_policy["shadow_models"]
    comparison = {
        "official_model": official_model,
        "shadow_models": shadow_models,
        "official_output_drives_simulation": True,
        "shadow_output_drives_simulation": False,
        "models": model_results,
        "differences": {
            model_id: _model_difference(official, model_results[model_id])
            for model_id in shadow_models
        },
    }
    return {
        "schema_version": active_policy["schema_version"],
        "policy_id": active_policy["policy_id"],
        "policy_version": active_policy["version"],
        "simulation_only": True,
        "real_trade_execution": False,
        "symbol": symbol,
        "entry_date": position.get("entry_date"),
        "entry_price": entry_price,
        "initial_stop": initial_stop,
        "trigger_reference": trigger_reference,
        "immutable_field_check": {
            "entry_price_preserved": entry_price == position.get("entry_price"),
            "initial_stop_preserved": initial_stop == position.get("initial_stop"),
            "trigger_used_as_entry": False,
        },
        **{field: official.get(field) for field in active_policy["output_fields"] if field != "model_comparison_snapshot"},
        "model_comparison_snapshot": comparison,
    }


def _evaluate_model(
    *,
    symbol: str,
    position: dict[str, Any],
    metrics: dict[str, Any],
    metric_errors: list[str],
    model_id: str,
    model_policy: dict[str, Any],
    previous_model: dict[str, Any],
    completed_event_ids: set[str],
) -> dict[str, Any]:
    previous_emitted = set(previous_model.get("emitted_event_ids") or [])
    previous_completed = set(previous_model.get("completed_event_ids") or [])
    model_completed = {
        event_id
        for event_id in completed_event_ids
        if _event_model_from_id(event_id) == model_id
    }
    completed = model_completed | previous_completed
    pending = [
        dict(event)
        for event in previous_model.get("pending_events") or []
        if event.get("event_id") not in completed
    ]
    partial_was_completed = bool(previous_model.get("partial_exit_completed"))
    partial_completed = partial_was_completed or any(
        _event_type_from_id(event_id) == "partial_exit" for event_id in completed
    )
    partial_just_completed = partial_completed and not partial_was_completed
    full_exit_completed = bool(previous_model.get("full_exit_completed")) or any(
        _event_type_from_id(event_id) in FULL_EXIT_EVENT_TYPES
        for event_id in completed
    )
    break_even_active = bool(
        partial_completed
        and model_policy["break_even_stop"]["activate_after_partial_exit"]
    )
    trailing_ma = (
        model_policy["trailing_exit"]["moving_average"] if partial_completed else None
    )
    current_bar = metrics.get("current_bar") or {}
    close = current_bar.get("close")
    trailing_value = current_bar.get(trailing_ma) if trailing_ma else None
    close_below_trailing = (
        bool(close < trailing_value)
        if trailing_ma and _is_number(close) and _is_number(trailing_value)
        else None
    )

    base = {
        "model_id": model_id,
        "role": model_policy["role"],
        "days_since_entry": metrics.get("days_since_entry"),
        "current_r": metrics.get("current_r"),
        "max_r_reached": metrics.get("max_r_reached"),
        "max_close_since_entry": metrics.get("max_close_since_entry"),
        "partial_exit_due": False,
        "partial_exit_ratio": (
            model_policy["partial_exit"]["ratio"] if partial_completed else None
        ),
        "partial_exit_completed": partial_completed,
        "break_even_stop_activated": break_even_active,
        "active_trailing_ma": trailing_ma,
        "close_below_trailing_ma": close_below_trailing,
        "position_stage": "holding_pre_partial",
        "exit_model": model_id,
        "exit_signal": "none",
        "exit_reason": None,
        "pending_events": pending,
        "events_to_create": [],
        "emitted_event_ids": sorted(previous_emitted),
        "completed_event_ids": sorted(completed),
        "full_exit_completed": full_exit_completed,
        "data_errors": list(metric_errors),
        "parameters": {
            "partial_exit": model_policy["partial_exit"],
            "break_even_stop": model_policy["break_even_stop"],
            "trailing_exit": model_policy["trailing_exit"],
        },
        "evaluated_market_date": current_bar.get("date"),
    }

    position_status = str(position.get("position_status") or "open")
    if position_status == "pending" or position.get("entry_price") is None:
        return {
            **base,
            "position_stage": "not_entered",
            "exit_signal": "none",
            "exit_reason": "entry_not_confirmed",
            "active_trailing_ma": None,
            "break_even_stop_activated": False,
            "close_below_trailing_ma": False,
        }
    if metric_errors:
        return {
            **base,
            "position_stage": "invalid_data",
            "exit_reason": "invalid_position_or_price_history",
        }
    if position_status == "closed" or full_exit_completed:
        return {
            **base,
            "position_stage": "fully_exited",
            "exit_signal": "fully_exited",
            "exit_reason": "full_exit_already_completed",
            "pending_events": [],
        }

    pending_full_exit = next(
        (
            event
            for event in pending
            if event.get("event_type") in FULL_EXIT_EVENT_TYPES
        ),
        None,
    )
    if pending_full_exit:
        return _with_pending_event(base, pending_full_exit, previous_emitted)

    entry_price = float(position["entry_price"])
    initial_stop = float(position["initial_stop"])
    current_date = str(current_bar["date"])
    if close <= initial_stop:
        return _signal_event(
            base,
            symbol,
            model_id,
            "initial_stop_exit",
            current_date,
            "stop_exit",
            "stopped_out",
            "close_at_or_below_initial_stop",
            previous_emitted,
            model_policy["role"] == "official_simulation",
        )
    if break_even_active and close <= entry_price:
        return _signal_event(
            base,
            symbol,
            model_id,
            "break_even_exit",
            current_date,
            "stop_exit",
            "stopped_out",
            "close_at_or_below_break_even_stop",
            previous_emitted,
            model_policy["role"] == "official_simulation",
        )
    if close_below_trailing:
        return _signal_event(
            base,
            symbol,
            model_id,
            "trailing_ma_exit",
            current_date,
            "trailing_exit",
            "stopped_out",
            f"close_below_{trailing_ma}",
            previous_emitted,
            model_policy["role"] == "official_simulation",
        )

    pending_partial = next(
        (event for event in pending if event.get("event_type") == "partial_exit"),
        None,
    )
    if pending_partial:
        result = _with_pending_event(base, pending_partial, previous_emitted)
        result["partial_exit_due"] = True
        result["partial_exit_ratio"] = model_policy["partial_exit"]["ratio"]
        return result

    if not partial_completed and _partial_exit_is_due(model_policy, metrics):
        return _signal_event(
            {
                **base,
                "partial_exit_due": True,
                "partial_exit_ratio": model_policy["partial_exit"]["ratio"],
            },
            symbol,
            model_id,
            "partial_exit",
            current_date,
            "partial_exit",
            "partial_exit_due",
            _partial_exit_reason(model_policy),
            previous_emitted,
            model_policy["role"] == "official_simulation",
        )
    if partial_completed:
        same_day_partial_completion_rerun = (
            previous_model.get("position_stage") == "partially_reduced"
            and previous_model.get("evaluated_market_date") == current_bar.get("date")
        )
        if partial_just_completed or same_day_partial_completion_rerun:
            stage = "partially_reduced"
        elif _is_number(trailing_value):
            stage = "trailing_active"
        else:
            stage = "break_even_active"
        return {
            **base,
            "position_stage": stage,
            "exit_reason": "partial_exit_completed",
        }
    return base


def _position_metrics(
    position: dict[str, Any],
    bars: list[dict[str, Any]],
    entry_price: Any,
    initial_stop: Any,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if str(position.get("position_status") or "open") == "pending" or entry_price is None:
        return {
            "days_since_entry": None,
            "current_r": None,
            "max_r_reached": None,
            "max_close_since_entry": None,
            "current_bar": bars[-1] if bars else None,
        }, errors
    if not _is_number(entry_price):
        errors.append("entry_price_invalid")
    if not _is_number(initial_stop):
        errors.append("initial_stop_invalid")
    if _is_number(entry_price) and _is_number(initial_stop) and initial_stop >= entry_price:
        errors.append("initial_stop_must_be_below_entry_price")
    if not bars:
        errors.append("price_history_missing_since_entry")
    if errors:
        return {
            "days_since_entry": None,
            "current_r": None,
            "max_r_reached": None,
            "max_close_since_entry": None,
            "current_bar": bars[-1] if bars else None,
        }, errors

    risk = float(entry_price) - float(initial_stop)
    closes = [float(bar["close"]) for bar in bars]
    current_close = closes[-1]
    max_close = max(closes)
    return {
        "days_since_entry": len(bars) - 1,
        "current_r": round((current_close - float(entry_price)) / risk, 4),
        "max_r_reached": round((max_close - float(entry_price)) / risk, 4),
        "max_close_since_entry": max_close,
        "current_bar": bars[-1],
    }, errors


def _normalized_bars(
    price_history: list[dict[str, Any]], entry_date: Any
) -> list[dict[str, Any]]:
    if not entry_date:
        return []
    try:
        entry_day = date.fromisoformat(str(entry_date))
    except ValueError:
        return []
    unique: dict[str, dict[str, Any]] = {}
    for raw in price_history:
        try:
            bar_day = date.fromisoformat(str(raw.get("date")))
        except ValueError:
            continue
        if bar_day < entry_day or not _is_number(raw.get("close")):
            continue
        item = {
            "date": bar_day.isoformat(),
            "close": float(raw["close"]),
            "ma10": float(raw["ma10"]) if _is_number(raw.get("ma10")) else None,
            "ma20": float(raw["ma20"]) if _is_number(raw.get("ma20")) else None,
        }
        unique[item["date"]] = item
    return [unique[key] for key in sorted(unique)]


def _partial_exit_is_due(
    model_policy: dict[str, Any], metrics: dict[str, Any]
) -> bool:
    partial = model_policy["partial_exit"]
    if partial["trigger_type"] == "r_multiple":
        return metrics[partial["trigger_metric"]] >= partial["trigger_r"]
    return (
        partial["minimum_day"]
        <= metrics["days_since_entry"]
        <= partial["maximum_day"]
    )


def _partial_exit_reason(model_policy: dict[str, Any]) -> str:
    partial = model_policy["partial_exit"]
    if partial["trigger_type"] == "r_multiple":
        return f"current_r_reached_{partial['trigger_r']}R"
    return (
        f"days_since_entry_in_{partial['minimum_day']}_to_"
        f"{partial['maximum_day']}_trading_day_window"
    )


def _signal_event(
    base: dict[str, Any],
    symbol: str,
    model_id: str,
    event_type: str,
    signal_date: str,
    exit_signal: str,
    position_stage: str,
    exit_reason: str,
    previous_emitted: set[str],
    event_creation_allowed: bool,
) -> dict[str, Any]:
    event_id = _event_id(symbol, model_id, event_type, signal_date)
    event = {
        "event_id": event_id,
        "event_type": event_type,
        "signal_date": signal_date,
        "simulation_only": True,
    }
    events_to_create = (
        [event]
        if event_creation_allowed and event_id not in previous_emitted
        else []
    )
    return {
        **base,
        "position_stage": position_stage,
        "exit_signal": exit_signal,
        "exit_reason": exit_reason,
        "pending_events": [event],
        "events_to_create": events_to_create,
        "emitted_event_ids": sorted(previous_emitted | {event_id}),
    }


def _with_pending_event(
    base: dict[str, Any],
    event: dict[str, Any],
    previous_emitted: set[str],
) -> dict[str, Any]:
    event_type = str(event["event_type"])
    if event_type == "partial_exit":
        signal, stage = "partial_exit", "partial_exit_due"
    elif event_type == "trailing_ma_exit":
        signal, stage = "trailing_exit", "stopped_out"
    else:
        signal, stage = "stop_exit", "stopped_out"
    return {
        **base,
        "position_stage": stage,
        "exit_signal": signal,
        "exit_reason": f"pending_{event_type}",
        "pending_events": [event],
        "events_to_create": [],
        "emitted_event_ids": sorted(
            previous_emitted | {str(event["event_id"])}
        ),
    }


def _event_id(
    symbol: str, model_id: str, event_type: str, signal_date: str
) -> str:
    return f"{symbol}:{model_id}:{event_type}:{signal_date}"


def _event_type_from_id(event_id: str) -> str:
    parts = event_id.split(":")
    return parts[2] if len(parts) >= 4 else ""


def _event_model_from_id(event_id: str) -> str:
    parts = event_id.split(":")
    return parts[1] if len(parts) >= 4 else ""


def _model_difference(
    official: dict[str, Any], shadow: dict[str, Any]
) -> dict[str, Any]:
    return {
        "position_stage": {
            "official": official["position_stage"],
            "shadow": shadow["position_stage"],
            "different": official["position_stage"] != shadow["position_stage"],
        },
        "exit_signal": {
            "official": official["exit_signal"],
            "shadow": shadow["exit_signal"],
            "different": official["exit_signal"] != shadow["exit_signal"],
        },
        "partial_exit_due": {
            "official": official["partial_exit_due"],
            "shadow": shadow["partial_exit_due"],
            "different": official["partial_exit_due"] != shadow["partial_exit_due"],
        },
    }


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
