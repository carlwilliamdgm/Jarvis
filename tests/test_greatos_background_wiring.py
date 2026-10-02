import queue
import unittest
import asyncio
import threading
from unittest.mock import patch, MagicMock

from jarvis.agent import EventBus
import jarvis.agent as agent_module
import interface_morphique.server as server_module


class TestGreatOSBackgroundWiring(unittest.TestCase):
    def test_broadcast_reaches_all_subscribers_without_thread_binding(self):
        bus = EventBus()
        first = bus.subscribe()
        second = bus.subscribe()
        try:
            bus.emit_broadcast("alerte_proactive", {"type": "cpu"})
            self.assertEqual(first.get_nowait()["type"], "alerte_proactive")
            self.assertEqual(second.get_nowait()["data"]["type"], "cpu")
        finally:
            bus.unsubscribe(first)
            bus.unsubscribe(second)

    def test_normal_events_remain_scoped_to_bound_subscriber(self):
        bus = EventBus()
        first = bus.subscribe()
        second = bus.subscribe()
        try:
            bus.bind(first)
            bus.emit("tool_started", {"outil": "lire"})
            self.assertEqual(first.get_nowait()["type"], "tool_started")
            with self.assertRaises(queue.Empty):
                second.get_nowait()
        finally:
            bus.unbind()
            bus.unsubscribe(first)
            bus.unsubscribe(second)

    def test_background_subscriber_gets_active_alerts_and_resolution_clears_cache(self):
        bus = EventBus()
        alert = {"type": "cpu", "message": "CPU élevé"}
        bus.emit_broadcast("alerte_proactive", alert)
        subscriber = bus.subscribe_broadcast()
        try:
            self.assertEqual(subscriber.get_nowait()["data"], alert)
            bus.emit_broadcast("alerte_proactive_resolue", {"type": "cpu", "mountpoint": ""})
            later_subscriber = bus.subscribe_broadcast()
            try:
                with self.assertRaises(queue.Empty):
                    later_subscriber.get_nowait()
            finally:
                bus.unsubscribe(later_subscriber)
        finally:
            bus.unsubscribe(subscriber)

    def test_proactive_daemon_start_is_idempotent(self):
        class FakeDaemon:
            def __init__(self, _bus, _interval):
                self.started = False

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started

            def arreter(self):
                self.started = False

            def join(self, timeout=None):
                return None

        original = agent_module._proactive_daemon
        try:
            agent_module._proactive_daemon = None
            with patch.object(agent_module, "DaemonProactif", side_effect=FakeDaemon) as factory:
                first = agent_module.demarrer_daemon_proactif(EventBus())
                second = agent_module.demarrer_daemon_proactif(EventBus())
                self.assertIs(first, second)
                factory.assert_called_once()
            agent_module.arreter_daemon_proactif()
        finally:
            agent_module._proactive_daemon = original

    def test_server_lifespan_starts_and_stops_background_services(self):
        class FakeWorker:
            def __init__(self, *args, **kwargs):
                self.started = False
                self.stopped = False

            def start(self):
                self.started = True

            def arreter(self):
                self.stopped = True

            def join(self, timeout=None):
                return None

        daemon = FakeWorker()
        scheduler = FakeWorker()
        stop_event = threading.Event()

        def start_daemon(_bus):
            daemon.start()
            return daemon

        async def exercise_lifespan():
            with (
                patch.object(server_module, "initialiser", return_value={}),
                patch.object(server_module, "get_llm_client", return_value=object()),
                patch.object(server_module, "demarrer_agent_autonome", return_value=(object(), stop_event, None)),
                patch.object(server_module, "demarrer_daemon_proactif", side_effect=start_daemon) as start_daemon_mock,
                patch.object(server_module, "arreter_daemon_proactif", side_effect=daemon.arreter),
                patch.object(server_module, "ConsolidationScheduler", return_value=scheduler),
                patch.object(server_module, "construire_prompt_action", return_value="prompt"),
                patch.object(server_module, "demarrer_overlay_vocal"),
                patch.object(server_module, "demarrer_ecoute_vocale"),
                patch.object(server_module, "demarrer_ecoute_clap"),
                patch.object(server_module, "_demarrer_cpu_sampler"),
                patch("interface_morphique.browser_overlay.start_browser_overlay", create=True),
            ):
                async with server_module.lifespan(server_module.app):
                    self.assertTrue(daemon.started)
                    self.assertTrue(scheduler.started)
                    start_daemon_mock.assert_called_once_with(server_module.event_bus)
                self.assertTrue(daemon.stopped)
                self.assertTrue(scheduler.stopped)
                self.assertTrue(stop_event.is_set())

        asyncio.run(exercise_lifespan())
