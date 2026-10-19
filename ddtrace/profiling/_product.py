"""Product plugin that lets the profiler react to DEBUG remote config payloads."""

from collections.abc import Sequence
import logging
import typing as t

from ddtrace.internal.logger import get_logger
from ddtrace.internal.native import RemoteConfigProduct
from ddtrace.internal.remoteconfig import Payload
from ddtrace.internal.remoteconfig import RCCallback
from ddtrace.internal.settings.profiling import config as profiling_config


log = get_logger(__name__)
_handler: logging.StreamHandler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
log.addHandler(_handler)
log.propagate = False

requires: list[str] = ["remote-configuration"]

# Config id to payload content, for every DEBUG config currently applied.
debug_configs: dict[str, dict[str, t.Any]] = {}

previous_profiling_remote_configuration: t.Optional[dict[str, t.Any]] = None


def _get_default_config() -> dict[str, t.Any]:
    return {
        "profilers": {
            "stack": False,
            "memory": False,
            "exception": False,
            "lock": False,
        },
        "settings": {},
    }


class ProfilingRCCallback(RCCallback):
    def __call__(self, payloads: Sequence[Payload]) -> None:
        log.debug("[profiling-remote-config] Received %d DEBUG RC payloads %s", len(payloads), payloads)

        for payload in payloads:
            if payload.metadata is None:
                continue

            if payload.content is None:
                debug_configs.pop(payload.metadata.id, None)
            else:
                debug_configs[payload.metadata.id] = payload.content

        profiling_configs = [c for c in debug_configs.values() if "profilers" in c]
        if profiling_configs:
            log.debug("[profiling-remote-config] Profiling-related DEBUG RC configs: %s", profiling_configs)
        else:
            log.debug(
                "[profiling-remote-config] No Profiling-related DEBUG RC configs, falling back to default settings."
            )

        self.handle_profiling_configs(profiling_configs)

    def handle_profiling_configs(self, configs: list[dict[str, t.Any]]) -> None:
        """Merges all the Remote Config files that were sent to the Tracer."""
        global previous_profiling_remote_configuration

        merged_config: dict[str, t.Any] = _get_default_config()

        # This needs to be done from "least specific scope" to "most specific scope"
        for config in configs:
            for key, value in config.get("profilers", {}).items():
                enabled_in_new = value is True
                if enabled_in_new is None:
                    continue

                if enabled_in_new:
                    merged_config["profilers"][key] = value

        if previous_profiling_remote_configuration is None:
            log.debug(
                (
                    "[profiling-remote-config] No previous Profiling-related DEBUG RC configs, starting "
                    "the Profiler with the new settings: %s"
                ),
                merged_config,
            )
            previous_profiling_remote_configuration = merged_config
            _restart_profiler(merged_config["profilers"])
            return

        if previous_profiling_remote_configuration == merged_config:
            log.debug(
                "[profiling-remote-config] No effective changes in the Profiling-related DEBUG RC configs, skipping."
            )
            return

        # Stop the Profiler and restart it
        previous_profiling_remote_configuration = merged_config
        log.debug("[profiling-remote-config] Restarting the Profiler with the new settings: %s", merged_config)
        _restart_profiler(merged_config["profilers"])


def _restart_profiler(profilers: dict[str, bool]) -> None:
    from ddtrace.profiling import bootstrap
    from ddtrace.profiling.profiler import Profiler

    current: t.Optional[Profiler] = getattr(bootstrap, "profiler", None)
    if current is not None:
        current.stop(flush=True)
        del bootstrap.profiler

    if not any(profilers.values()):
        return

    new_profiler = Profiler(
        _stack_collector_enabled=profilers["stack"],
        _memory_collector_enabled=profilers["memory"],
        _lock_collector_enabled=profilers["lock"],
        _exception_profiling_enabled=profilers["exception"],
    )
    bootstrap.profiler = new_profiler
    new_profiler.start()


def post_preload() -> None:
    pass


def enabled() -> bool:
    return profiling_config.enabled


def start() -> None:
    from ddtrace.internal.remoteconfig.worker import remoteconfig_poller

    remoteconfig_poller.register_callback(RemoteConfigProduct.Debug, ProfilingRCCallback())
    remoteconfig_poller.enable_product(RemoteConfigProduct.Debug)


def restart(join: bool = False) -> None:
    pass


def stop(join: bool = False) -> None:
    from ddtrace.internal.remoteconfig.worker import remoteconfig_poller

    remoteconfig_poller.unregister_callback(RemoteConfigProduct.Debug)
    remoteconfig_poller.disable_product(RemoteConfigProduct.Debug)
