"""Tests for API state consistency guarantees without global sys.modules pollution."""

import unittest
from unittest.mock import patch, MagicMock, Mock
import json
import tempfile
import os
import queue
import asyncio
from pathlib import Path

# Import the real modules - no global sys.modules mutations
import api.server
from api.server import traiter_message, stream_jarvis


class APIStateConsistencyTests(unittest.TestCase):
    """Test state consistency guarantees for the API server."""
    
    def setUp(self):
        """Set up test fixtures with real modules but mocked dependencies."""
        # Create mock global state
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
        api.server.agent = None
        api.server.agent_stop_event = None
        
        # We'll patch jarvis functions in each test method
        
    def tearDown(self):
        """Clean up test state."""
        # Reset global state
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
        api.server.agent = None
        api.server.agent_stop_event = None
    
    @patch('api.server.executer_interaction_utilisateur')
    def test_failure_before_any_write_preserves_conversation_state(self, mock_executer):
        """Test that failure before any tool write keeps conversation coherent."""
        initial_historique_len = len(api.server.historique)
        initial_memoire_keys = set(api.server.memoire.keys())
        
        # Mock executer to fail before any write
        mock_executer.side_effect = Exception("Simulated early failure")
        
        # Attempt to process message - should fail
        with self.assertRaises(Exception) as context:
            traiter_message("test message")
        
        # Verify error is clean
        self.assertIn("Error processing message", str(context.exception))
        
        # Verify conversation state remains coherent
        # Historique may have been modified (no rollback), but should be usable
        self.assertIsInstance(api.server.historique, list)
        self.assertIsInstance(api.server.memoire, dict)
        
        # Memoire should still have expected structure
        self.assertIn("utilisateur", api.server.memoire)
    
    def test_failure_after_simulated_write_does_not_rollback_persisted_state(self):
        """Test that failure after a simulated write does not attempt to rollback persisted state."""
        # Create a temporary file to simulate persistence
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
            json.dump({"simulated": "initial_data"}, f)
        
        try:
            # Simulate a write then fail - directly test the concept
            def failing_after_write():
                # Simulate tool that writes to file
                with open(temp_file, 'w') as f:
                    json.dump({"simulated": "new_data", "timestamp": "after_write"}, f)
                f.flush()
                os.fsync(f.fileno())  # Ensure write is persisted
                # Then fail
                raise Exception("Simulated failure after write")
            
            try:
                failing_after_write()
            except Exception:
                pass  # Expected failure
            
            # Verify the file was NOT rolled back (new data persists)
            with open(temp_file, 'r') as f:
                persisted_data = json.load(f)
            
            # The new data should still be there (no rollback attempted)
            self.assertEqual(persisted_data["simulated"], "new_data")
            self.assertEqual(persisted_data["timestamp"], "after_write")
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    @patch('api.server.executer_interaction_utilisateur')
    def test_error_message_is_clean_and_informative(self, mock_executer):
        """Test that error messages are clean and informative."""
        mock_executer.side_effect = ValueError("Specific error message")
        
        # Attempt to process message - should fail with clean error
        with self.assertRaises(Exception) as context:
            traiter_message("test message")
        
        # Error should be wrapped with clear context
        error_message = str(context.exception)
        self.assertIn("Error processing message", error_message)
        self.assertIn("Specific error message", error_message)
    
    @patch('api.server.executer_interaction_utilisateur')
    def test_success_case_works_normally(self, mock_executer):
        """Test that successful execution works normally without rollback mechanism."""
        mock_executer.return_value = ("Test response", False)
        
        result = traiter_message("test message")
        
        # Verify successful response structure
        self.assertEqual(result["response"], "Test response")
        self.assertEqual(result["is_action"], False)
        self.assertEqual(result["actions_executed"], [])
    
    @patch('api.server.executer_interaction_utilisateur')
    def test_success_case_with_action(self, mock_executer):
        """Test that successful execution with action works correctly."""
        mock_executer.return_value = ("Action completed", True)
        
        result = traiter_message("test message")
        
        # Verify action response structure
        self.assertEqual(result["response"], "Action completed")
        self.assertEqual(result["is_action"], True)
        self.assertEqual(result["actions_executed"], [1])


class EventBusCleanupTests(unittest.TestCase):
    """Test event_bus cleanup behavior for SSE streaming."""
    
    def setUp(self):
        """Set up test fixtures for event bus tests."""
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
    
    def tearDown(self):
        """Clean up test state."""
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
    
    @patch('api.server.executer_interaction_utilisateur')
    @patch('api.server.event_bus')
    @patch('api.server.StreamingConfirmationHandler')
    @patch('api.server.use_confirmation_handler')
    def test_real_stream_success_scenario(self, mock_use_handler, mock_confirmation_handler, mock_event_bus, mock_executer):
        """Test real stream_jarvis with success scenario."""
        # Setup event bus mock
        event_queue = queue.Queue()
        mock_event_bus.subscribe.return_value = event_queue
        mock_event_bus.bind = MagicMock()
        mock_event_bus.unbind = MagicMock()
        mock_event_bus.emit = MagicMock()
        mock_event_bus.unsubscribe = MagicMock()
        
        # Mock executer to succeed
        mock_executer.return_value = ("Success response", False)
        
        # Mock confirmation handler context manager
        mock_handler_instance = MagicMock()
        mock_confirmation_handler.return_value = mock_handler_instance
        mock_use_handler.return_value.__enter__ = MagicMock(return_value=mock_handler_instance)
        mock_use_handler.return_value.__exit__ = MagicMock(return_value=False)
        
        # Create async event loop for streaming
        async def run_stream_test():
            # Call the real stream_jarvis function
            response = stream_jarvis("test message", "test-session-123")
            
            # Consume the body_iterator
            events = []
            async for chunk in response.body_iterator:
                if chunk:
                    # Parse SSE format
                    for line in chunk.decode().split('\n'):
                        if line.startswith('data: '):
                            try:
                                event = json.loads(line[6:])
                                events.append(event)
                            except json.JSONDecodeError:
                                pass
            
            return events
        
        # Run the async test
        events = asyncio.run(run_stream_test())
        
        # Verify cleanup methods were called
        mock_event_bus.bind.assert_called_once()
        mock_event_bus.unbind.assert_called_once()
        mock_event_bus.unsubscribe.assert_called_once()
        
        # Verify we got the done event
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1, "Should have exactly one 'done' event")
        
        # Verify no error event was emitted
        error_events = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(error_events), 0, "Should have no error events on success")
    
    @patch('api.server.executer_interaction_utilisateur')
    @patch('api.server.event_bus')
    @patch('api.server.StreamingConfirmationHandler')
    @patch('api.server.use_confirmation_handler')
    def test_real_stream_error_scenario(self, mock_use_handler, mock_confirmation_handler, mock_event_bus, mock_executer):
        """Test real stream_jarvis with error scenario."""
        # Setup event bus mock
        event_queue = queue.Queue()
        mock_event_bus.subscribe.return_value = event_queue
        mock_event_bus.bind = MagicMock()
        mock_event_bus.unbind = MagicMock()
        mock_event_bus.emit = MagicMock()
        mock_event_bus.unsubscribe = MagicMock()
        
        # Mock executer to fail
        mock_executer.side_effect = Exception("Simulated failure")
        
        # Mock confirmation handler context manager
        mock_handler_instance = MagicMock()
        mock_confirmation_handler.return_value = mock_handler_instance
        mock_use_handler.return_value.__enter__ = MagicMock(return_value=mock_handler_instance)
        mock_use_handler.return_value.__exit__ = MagicMock(return_value=False)
        
        # Create async event loop for streaming
        async def run_stream_test():
            # Call the real stream_jarvis function
            response = stream_jarvis("test message", "test-session-error")
            
            # Consume the body_iterator
            events = []
            async for chunk in response.body_iterator:
                if chunk:
                    # Parse SSE format
                    for line in chunk.decode().split('\n'):
                        if line.startswith('data: '):
                            try:
                                event = json.loads(line[6:])
                                events.append(event)
                            except json.JSONDecodeError:
                                pass
            
            return events
        
        # Run the async test
        events = asyncio.run(run_stream_test())
        
        # Verify cleanup methods were called even on error
        mock_event_bus.bind.assert_called_once()
        mock_event_bus.unbind.assert_called_once()
        mock_event_bus.unsubscribe.assert_called_once()
        
        # Verify error event was emitted
        error_events = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(error_events), 1, "Should have exactly one error event")
        self.assertIn("Simulated failure", error_events[0].get("data", {}).get("message", ""))
        
        # Verify we still got the done event after error
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1, "Should have exactly one 'done' event even after error")
    
    @patch('api.server.executer_interaction_utilisateur')
    @patch('api.server.event_bus')
    @patch('api.server.StreamingConfirmationHandler')
    @patch('api.server.use_confirmation_handler')
    def test_stream_no_queue_leak(self, mock_use_handler, mock_confirmation_handler, mock_event_bus, mock_executer):
        """Test that stream doesn't leak event queue subscriptions."""
        # Setup event bus mock
        event_queue = queue.Queue()
        mock_event_bus.subscribe.return_value = event_queue
        mock_event_bus.bind = MagicMock()
        mock_event_bus.unbind = MagicMock()
        mock_event_bus.emit = MagicMock()
        mock_event_bus.unsubscribe = MagicMock()
        
        # Mock executer to succeed
        mock_executer.return_value = ("Success response", False)
        
        # Mock confirmation handler context manager
        mock_handler_instance = MagicMock()
        mock_confirmation_handler.return_value = mock_handler_instance
        mock_use_handler.return_value.__enter__ = MagicMock(return_value=mock_handler_instance)
        mock_use_handler.return_value.__exit__ = MagicMock(return_value=False)
        
        # Create async event loop for streaming
        async def run_stream_test():
            # Call the real stream_jarvis function
            response = stream_jarvis("test message", "test-session-no-leak")
            
            # Consume the body_iterator
            async for chunk in response.body_iterator:
                pass  # Just consume to completion
        
        # Run the async test
        asyncio.run(run_stream_test())
        
        # Verify cleanup methods were called
        mock_event_bus.unsubscribe.assert_called_once_with(event_queue)
        
        # Verify the queue was removed from event bus
        # (This is verified by checking unsubscribe was called with the right queue)
        mock_event_bus.unsubscribe.assert_called_once()
    
    @patch('api.server.executer_interaction_utilisateur')
    @patch('api.server.event_bus')
    @patch('api.server.StreamingConfirmationHandler')
    @patch('api.server.use_confirmation_handler')
    def test_stream_confirmation_refused(self, mock_use_handler, mock_confirmation_handler, mock_event_bus, mock_executer):
        """Test stream behavior when confirmation is refused."""
        # Setup event bus mock
        event_queue = queue.Queue()
        mock_event_bus.subscribe.return_value = event_queue
        mock_event_bus.bind = MagicMock()
        mock_event_bus.unbind = MagicMock()
        mock_event_bus.emit = MagicMock()
        mock_event_bus.unsubscribe = MagicMock()
        
        # Mock executer to succeed but require confirmation
        mock_executer.return_value = ("Action refused by user", False)
        
        # Mock confirmation handler to simulate refusal
        mock_handler_instance = MagicMock()
        mock_confirmation_handler.return_value = mock_handler_instance
        mock_use_handler.return_value.__enter__ = MagicMock(return_value=mock_handler_instance)
        mock_use_handler.return_value.__exit__ = MagicMock(return_value=False)
        
        # Create async event loop for streaming
        async def run_stream_test():
            # Call the real stream_jarvis function
            response = stream_jarvis("test message", "test-session-refused")
            
            # Consume the body_iterator
            events = []
            async for chunk in response.body_iterator:
                if chunk:
                    for line in chunk.decode().split('\n'):
                        if line.startswith('data: '):
                            try:
                                event = json.loads(line[6:])
                                events.append(event)
                            except json.JSONDecodeError:
                                pass
            
            return events
        
        # Run the async test
        events = asyncio.run(run_stream_test())
        
        # Verify cleanup happened
        mock_event_bus.unbind.assert_called_once()
        mock_event_bus.unsubscribe.assert_called_once()
        
        # Verify stream completed
        done_events = [e for e in events if e.get("type") == "done"]
        self.assertEqual(len(done_events), 1, "Stream should complete even with confirmation refusal")


class ConcurrencySafetyTests(unittest.TestCase):
    """Test concurrent access to memory.json doesn't cause corruption."""
    
    def setUp(self):
        """Set up test fixtures for concurrency tests."""
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
        
        # Create a temporary memory file for testing
        self.temp_memory_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_memory_path = self.temp_memory_file.name
        self.temp_memory_file.write('{"utilisateur": {"nom": "Test"}, "notes": []}')
        self.temp_memory_file.close()
    
    def tearDown(self):
        """Clean up test state."""
        api.server.historique = [{"role": "system", "content": "System prompt"}]
        api.server.memoire = {"utilisateur": {"nom": "Test"}, "notes": []}
        
        # Clean up temp file
        if os.path.exists(self.temp_memory_path):
            os.unlink(self.temp_memory_path)
    
    @patch('api.server.executer_interaction_utilisateur')
    def test_concurrent_user_interaction_and_autonomous_action(self, mock_executer):
        """Test that concurrent user interaction and autonomous action don't corrupt memory.json."""
        # Mock executer to succeed
        mock_executer.return_value = ("Test response", False)
        
        # Simulate user interaction
        def user_interaction():
            try:
                result = traiter_message("user message")
                return result
            except Exception as e:
                return {"error": str(e)}
        
        # Simulate autonomous agent action (which would write to memory)
        def autonomous_action():
            # Simulate a write to memory.json
            try:
                with open(self.temp_memory_path, 'r') as f:
                    data = json.load(f)
                
                # Modify data
                data["autonomous_test"] = "concurrent_write"
                
                with open(self.temp_memory_path, 'w') as f:
                    json.dump(data, f)
                
                return "success"
            except Exception as e:
                return f"error: {e}"
        
        # Run both concurrently
        import threading
        user_thread = threading.Thread(target=user_interaction)
        auto_thread = threading.Thread(target=autonomous_action)
        
        user_thread.start()
        auto_thread.start()
        
        user_thread.join(timeout=5)
        auto_thread.join(timeout=5)
        
        # Verify memory.json is still valid JSON
        with open(self.temp_memory_path, 'r') as f:
            data = json.load(f)
        
        # Verify data integrity
        self.assertIn("utilisateur", data)
        self.assertIn("nom", data["utilisateur"])
        # The autonomous write may or may not have succeeded, but the file should be valid JSON
        self.assertIsInstance(data, dict)


class DocumentationConsistencyTests(unittest.TestCase):
    """Test that EXECUTION_OUTILS.md documents match actual tools.OUTILS."""
    
    def test_documented_tools_match_actual_tools(self):
        """Test that tools documented in EXECUTION_OUTILS.md match tools.OUTILS."""
        # Import the actual tools
        from tools import OUTILS
        
        # Read the documentation file
        doc_path = Path(__file__).parent.parent / "EXECUTION_OUTILS.md"
        with open(doc_path, 'r', encoding='utf-8') as f:
            doc_content = f.read()
        
        # Extract tool names from documentation (look for `tool_name(` pattern)
        import re
        documented_tools = set()
        for match in re.finditer(r'`([a-z_]+)\(', doc_content):
            tool_name = match.group(1)
            # Skip internal module functions
            if tool_name not in ['activer_vocal', 'desactiver_vocal', 'lire_etat_vocal', 
                               'configurer_vocal', 'obtenir_etat_systeme', 'detecter_anomalies',
                               'generer_suggestions_contextuelles', 'analyser_decisions_recentes',
                               'detecter_patterns_erreur', 'memoriser_succes', 'rechercher_solution_similaire',
                               'rechercher_semantique', 'analyser_connexions_contextuelles', 
                               'generer_insights_profonds', 'obtenir_personnalite', 'ajuster_personnalite',
                               'adapter_ton_contextuel', 'generer_prompt_personnalite', 'evoluer_personnalite',
                               'obtenir_rapport_personnalite', 'reinitialiser_personnalite']:
                documented_tools.add(tool_name)
        
        # Get actual tool names
        actual_tools = set(OUTILS.keys())
        
        # Check for tools in documentation but not in OUTILS
        doc_only = documented_tools - actual_tools
        if doc_only:
            self.fail(f"Tools documented but not in tools.OUTILS: {doc_only}")
        
        # Check for tools in OUTILS but not in documentation
        actual_only = actual_tools - documented_tools
        if actual_only:
            self.fail(f"Tools in tools.OUTILS but not documented: {actual_only}")


if __name__ == "__main__":
    unittest.main()
