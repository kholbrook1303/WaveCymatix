import logging
import time

log = logging.getLogger()


class PerformancePolicy:
    """Mode-agnostic performance policy evaluator for all visual modes."""

    def __init__(self, config):
        self.config = config
        self.performance = getattr(config, "performance", {})
        self._states = {}

    def _get_cfg(self, mode, key, default):
        mode_key = f"{mode}.{key}" if mode else key
        if mode_key in self.performance:
            return self.performance.get(mode_key)
        return self.performance.get(key, default)

    def _get_state(self, mode):
        state = self._states.get(mode)
        if state is None:
            state = {
                "ignore_until": 0.0,
                "baseline_samples": [],
                "deviation_accumulator": 0.0,
                "long_frame_accumulator": 0.0,
                "ema_frame_time": None,
                "last_frame_time": 0.0,
                "last_swap_time": 0.0,
                "last_baseline": None,
                "last_state": "INIT",
                "last_unstable_at": 0.0,
                "last_event_log_at": 0.0,
                "last_fps_action_at": 0.0,
                "unstable_count": 0,
                "last_action": "none",
                "last_action_reason": "none",
                "last_suppressed_reason": "none",
                "last_mode_label": "N/A",
                "last_perf_status": "INIT",
                "last_fps_status": "INIT",
            }
            self._states[mode] = state
        return state

    def _reset_detector_state(self, state):
        state["baseline_samples"].clear()
        state["deviation_accumulator"] = 0.0
        state["long_frame_accumulator"] = 0.0
        state["ema_frame_time"] = None
        state["last_baseline"] = None

    def on_visual_transition(self, mode, is_hard=False):
        state = self._get_state(mode)
        now = time.time()

        settle_soft = float(self._get_cfg(mode, "settle_time_soft", 2.5))
        settle_hard = float(self._get_cfg(mode, "settle_time_hard", 1.5))
        settle = settle_hard if is_hard else settle_soft

        state["ignore_until"] = now + settle
        state["last_state"] = "SETTLING"
        self._reset_detector_state(state)

    def evaluate(self, mode, mode_label, frame_wall_time, swap_time, locked):
        state = self._get_state(mode)
        state["last_frame_time"] = frame_wall_time
        state["last_swap_time"] = swap_time
        state["last_mode_label"] = mode_label or "N/A"

        enabled = bool(self._get_cfg(mode, "enabled", True))
        fps_policy_enabled = bool(self._get_cfg(mode, "fps_policy_enabled", False))
        perf_detection_enabled = bool(self._get_cfg(mode, "perf_detection_enabled", False))

        target_fps = float(self._get_cfg(mode, "fps_target", 30.0))
        tolerance = float(self._get_cfg(mode, "tolerance", 0.8))
        threshold_fps = target_fps * tolerance

        current_fps = (1.0 / frame_wall_time) if frame_wall_time > 0 else 0.0
        below_threshold = current_fps < threshold_fps

        action = "none"
        action_reason = "none"
        status_reason = "none"
        suppressed_reason = "none"
        perf_status = "DISABLED"
        now = time.time()

        if not enabled:
            state["last_state"] = "DISABLED"
            state["last_perf_status"] = "DISABLED"
            state["last_fps_status"] = "DISABLED"
            state["last_action"] = action
            state["last_action_reason"] = action_reason
            state["last_suppressed_reason"] = "policy_disabled"
            return self.get_snapshot(mode)

        if frame_wall_time <= 0.0:
            fps_status = "WARMUP"
        elif below_threshold:
            fps_status = "UNSTABLE"
        else:
            fps_status = "STABLE"

        if now < state["ignore_until"]:
            perf_status = "SETTLING"
        else:
            baseline_window = int(self._get_cfg(mode, "baseline_window", 180))
            min_samples = int(self._get_cfg(mode, "min_samples", 45))
            deviation_threshold = float(self._get_cfg(mode, "deviation_threshold", 2.2))
            long_frame_threshold = float(self._get_cfg(mode, "long_frame_threshold", 0.085))
            swap_stall_threshold = float(self._get_cfg(mode, "swap_stall_threshold", 0.018))
            swap_weight = float(self._get_cfg(mode, "swap_weight", 0.85))
            trigger_deviation_time = float(self._get_cfg(mode, "trigger_deviation_time", 0.12))
            trigger_long_frame_time = float(self._get_cfg(mode, "trigger_long_frame_time", 0.14))
            trigger_cooldown = float(self._get_cfg(mode, "trigger_cooldown", 4.0))
            decay_deviation = float(self._get_cfg(mode, "decay_deviation", 0.93))
            decay_long_frame = float(self._get_cfg(mode, "decay_long_frame", 0.90))
            baseline_alpha = float(self._get_cfg(mode, "baseline_alpha", 0.04))

            samples = state["baseline_samples"]
            samples.append(frame_wall_time)
            if len(samples) > baseline_window:
                samples.pop(0)

            if len(samples) < min_samples:
                state["last_baseline"] = (sum(samples) / len(samples)) if samples else None
                perf_status = "WARMUP"
            else:
                baseline = sum(samples) / len(samples)
                if state["ema_frame_time"] is None:
                    state["ema_frame_time"] = baseline
                else:
                    state["ema_frame_time"] = (
                        (state["ema_frame_time"] * (1.0 - baseline_alpha))
                        + (frame_wall_time * baseline_alpha)
                    )

                baseline_ref = state["ema_frame_time"]
                state["last_baseline"] = baseline_ref

                deviation_limit = baseline_ref * deviation_threshold
                deviation_excess = max(0.0, frame_wall_time - deviation_limit)

                long_frame_excess = max(0.0, frame_wall_time - long_frame_threshold)
                swap_stall_excess = max(0.0, swap_time - swap_stall_threshold)
                weighted_swap_excess = swap_stall_excess * swap_weight

                state["deviation_accumulator"] = (
                    state["deviation_accumulator"] * decay_deviation
                    + deviation_excess
                )
                state["long_frame_accumulator"] = (
                    state["long_frame_accumulator"] * decay_long_frame
                    + long_frame_excess
                    + weighted_swap_excess
                )

                if (
                    state["deviation_accumulator"] > trigger_deviation_time
                    or state["long_frame_accumulator"] > trigger_long_frame_time
                ):
                    if now - state["last_unstable_at"] >= trigger_cooldown:
                        state["last_unstable_at"] = now
                        state["unstable_count"] += 1
                        perf_status = "UNSTABLE"
                        state["deviation_accumulator"] *= 0.25
                        state["long_frame_accumulator"] *= 0.25
                    else:
                        perf_status = "COOLDOWN"
                else:
                    perf_status = "STABLE"

        if perf_status == "UNSTABLE":
            status_reason = "perf_unstable"
        elif fps_status == "UNSTABLE":
            status_reason = "fps_below_tolerance"
        elif perf_status in ("SETTLING", "WARMUP", "COOLDOWN"):
            status_reason = perf_status.lower()
        else:
            status_reason = fps_status.lower()

        if perf_status == "UNSTABLE" and perf_detection_enabled:
            if not locked:
                action = self.performance.get("perf_policy_action", "advance_visual")
                action_reason = "perf_unstable"
            else:
                suppressed_reason = "visual_locked"

        if action == "none" and fps_status == "UNSTABLE":
            fps_action_cooldown = float(self._get_cfg(mode, "fps_action_cooldown", 2.5))
            if fps_policy_enabled:
                if perf_status == "UNSTABLE":
                    suppressed_reason = "perf_unstable"
                elif locked:
                    suppressed_reason = "visual_locked"
                elif now - state["last_fps_action_at"] < fps_action_cooldown:
                    suppressed_reason = "fps_cooldown"
                else:
                    action = self.performance.get("perf_policy_action", "advance_visual")
                    action_reason = "fps_below_tolerance"
                    state["last_fps_action_at"] = now

        if action == "none" and suppressed_reason == "none":
            suppressed_reason = status_reason

        if action != "none":
            self.on_visual_transition(mode, is_hard=False)
        else:
            if perf_status == "UNSTABLE" or fps_status == "UNSTABLE":
                state["last_state"] = "UNSTABLE"
            elif perf_status in ("SETTLING", "WARMUP", "COOLDOWN"):
                state["last_state"] = perf_status
            else:
                state["last_state"] = "STABLE"

        state["last_action"] = action
        state["last_action_reason"] = action_reason
        state["last_suppressed_reason"] = suppressed_reason
        state["last_perf_status"] = perf_status
        state["last_fps_status"] = fps_status

        return self.get_snapshot(mode, current_fps=current_fps, threshold_fps=threshold_fps)

    def get_snapshot(self, mode, current_fps=None, threshold_fps=None):
        state = self._get_state(mode)

        if current_fps is None:
            frame_time = state["last_frame_time"]
            current_fps = (1.0 / frame_time) if frame_time > 0 else 0.0

        if threshold_fps is None:
            target_fps = float(self._get_cfg(mode, "fps_target", 30.0))
            tolerance = float(self._get_cfg(mode, "tolerance", 0.8))
            threshold_fps = target_fps * tolerance

        return {
            "mode": mode,
            "label": state["last_mode_label"],
            "enabled": bool(self._get_cfg(mode, "enabled", True)),
            "fps_policy_enabled": bool(self._get_cfg(mode, "fps_policy_enabled", False)),
            "perf_detection_enabled": bool(self._get_cfg(mode, "perf_detection_enabled", False)),
            "fps_target": float(self._get_cfg(mode, "fps_target", 30.0)),
            "tolerance": float(self._get_cfg(mode, "tolerance", 0.8)),
            "threshold_fps": float(threshold_fps),
            "current_fps": float(current_fps),
            "baseline_window": int(self._get_cfg(mode, "baseline_window", 180)),
            "min_samples": int(self._get_cfg(mode, "min_samples", 45)),
            "deviation_threshold": float(self._get_cfg(mode, "deviation_threshold", 2.2)),
            "long_frame_threshold": float(self._get_cfg(mode, "long_frame_threshold", 0.085)),
            "swap_stall_threshold": float(self._get_cfg(mode, "swap_stall_threshold", 0.018)),
            "swap_weight": float(self._get_cfg(mode, "swap_weight", 0.85)),
            "trigger_deviation_time": float(self._get_cfg(mode, "trigger_deviation_time", 0.12)),
            "trigger_long_frame_time": float(self._get_cfg(mode, "trigger_long_frame_time", 0.14)),
            "trigger_cooldown": float(self._get_cfg(mode, "trigger_cooldown", 4.0)),
            "baseline_alpha": float(self._get_cfg(mode, "baseline_alpha", 0.04)),
            "fps_action_cooldown": float(self._get_cfg(mode, "fps_action_cooldown", 2.5)),
            "settle_time_soft": float(self._get_cfg(mode, "settle_time_soft", 2.5)),
            "settle_time_hard": float(self._get_cfg(mode, "settle_time_hard", 1.5)),
            "state": state["last_state"],
            "fps_status": state.get("last_fps_status", "INIT"),
            "perf_status": state.get("last_perf_status", "INIT"),
            "frame_time": state["last_frame_time"],
            "swap_time": state["last_swap_time"],
            "baseline": state["last_baseline"],
            "deviation_accumulator": state["deviation_accumulator"],
            "long_frame_accumulator": state["long_frame_accumulator"],
            "unstable_count": state["unstable_count"],
            "last_action": state["last_action"],
            "last_action_reason": state["last_action_reason"],
            "last_suppressed_reason": state["last_suppressed_reason"],
        }
