import threading
import time
import unittest

from core.confirmations import ConfirmationManager


class ConfirmationManagerTests(unittest.TestCase):
    def test_confirmation_is_resolved_by_its_own_session(self):
        manager = ConfirmationManager()
        events = []
        result = []

        def wait_for_confirmation():
            result.append(
                manager.wait_for_decision(
                    session_id="session-a",
                    description="supprimer un fichier",
                    emit=lambda event_type, data: events.append((event_type, data)),
                    timeout_seconds=2,
                )
            )

        worker = threading.Thread(target=wait_for_confirmation)
        worker.start()
        for _ in range(20):
            if events:
                break
            time.sleep(0.01)

        self.assertEqual("confirmation_required", events[0][0])
        action_id = events[0][1]["action_id"]
        self.assertEqual("wrong_session", manager.resolve("session-b", action_id, True))
        self.assertEqual("resolved", manager.resolve("session-a", action_id, True))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual([True], result)

    def test_refusal_unblocks_the_waiting_action(self):
        manager = ConfirmationManager()
        events = []
        result = []

        worker = threading.Thread(
            target=lambda: result.append(
                manager.wait_for_decision(
                    session_id="session-a",
                    description="supprimer un fichier",
                    emit=lambda event_type, data: events.append((event_type, data)),
                    timeout_seconds=2,
                )
            )
        )
        worker.start()
        for _ in range(20):
            if events:
                break
            time.sleep(0.01)

        action_id = events[0][1]["action_id"]
        self.assertEqual("resolved", manager.resolve("session-a", action_id, False))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual([False], result)


if __name__ == "__main__":
    unittest.main()
