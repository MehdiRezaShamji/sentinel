import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app.api.routes import build_demo_state
from app.services.monitor import (
    _run_local_monitoring_cycle,
    handle_sms_response,
    reset_monitoring_state,
    set_emergency_response,
    get_emergency_response,
    start_monitoring,
    stop_monitoring,
    state_lock,
)
import app.services.monitor

class TestSentinelStateMachine(unittest.TestCase):
    def setUp(self):
        os.environ["CHECKIN_TIMEOUT_SECONDS"] = "300"

        # Clear in-memory and DB-persisted chat ID so build_demo_state returns
        # telegram_chat_id=None by default. Individual tests set their own chat ID.
        import app.telegram as tg_module
        tg_module.discovered_chat_id = None
        try:
            from app.services.database import update_worker_telegram_chat_id
            update_worker_telegram_chat_id("W001", None)
        except Exception:
            pass
        
        # Override Telegram message send to prevent external calls during test
        self.sent_sms = []
        def mock_send_telegram_message(to, body):
            self.sent_sms.append({"to": to, "body": body})
            return {"success": True, "demo": True, "body": body}
        
        app.services.monitor.send_telegram_message = mock_send_telegram_message
        
        # Reset state
        state = build_demo_state()
        reset_monitoring_state(state)
        set_emergency_response(False)

    def tearDown(self):
        stop_monitoring()

    def test_risk_detection_and_checkin(self):
        # Initial state: Alex is working with 60 minutes exposure.
        # But environment is empty, so no risk yet.
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 32.0 # Below 35
        }
        reset_monitoring_state(state)
        
        # Run cycle
        res = _run_local_monitoring_cycle(state)
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "working")
        self.assertIsNone(alex["check_in_status"])
        
        # Now raise heat index to 36 (>= 35)
        state["environment"]["heat_index_c"] = 36.0
        # Update global state
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Run cycle: Alex should transition to high_risk, and check_in_status transitions to pending, sending an SMS.
        res = _run_local_monitoring_cycle(state)
        # Update global state
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        self.assertEqual(alex["check_in_status"], "pending")
        self.assertIsNotNone(alex["check_in_sent_at"])
        
        # Check SMS was sent
        self.assertEqual(len(self.sent_sms), 2)  # Alex and Sam both high risk (exposure 60 >= 45)
        alex_sms = next(s for s in self.sent_sms if s["to"] == alex["phone"])
        self.assertIn("Are you safe", alex_sms["body"])

    def test_worker_ok_response(self):
        # Setup worker in awaiting_checkin state
        state = build_demo_state()
        state["environment"] = {"heat_index_c": 36.0}
        
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        
        # Simulate worker replying OK
        self.sent_sms.clear()
        reply_res = handle_sms_response(alex["phone"], "OK")
        self.assertTrue(reply_res["success"])
        
        # Verify worker is back to working status and check-in confirmed
        alex_updated = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_updated["status"], "working")
        self.assertEqual(alex_updated["check_in_status"], "confirmed")
        self.assertEqual(alex_updated["check_in_response"], "OK")
        
        # Verify no incidents created
        self.assertEqual(len(app.services.monitor.monitoring_state["incidents"]), 0)

    def test_worker_timeout_and_buddy_safe(self):
        state = build_demo_state()
        state["environment"] = {"heat_index_c": 36.0}
        
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        
        # Artificially set check-in sent time to 10 minutes ago
        with state_lock:
            alex_ms = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
            alex_ms["check_in_sent_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            
        # Run cycle: should trigger timeout and notify buddy W002 (Jordan)
        self.sent_sms.clear()
        current_state = app.services.monitor.monitoring_state
        res = _run_local_monitoring_cycle(current_state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "unresponsive")
        self.assertEqual(alex["check_in_status"], "timed_out")
        self.assertEqual(alex["buddy_verification_status"], "pending")
        
        # SMS should be sent to Jordan (W002)
        jordan = next(w for w in res["workers"] if w["id"] == "W002")
        self.assertEqual(len(self.sent_sms), 1)
        self.assertEqual(self.sent_sms[0]["to"], jordan["phone"])
        self.assertIn("reply SAFE or NOT SAFE", self.sent_sms[0]["body"])
        
        # Buddy replies SAFE
        self.sent_sms.clear()
        reply_res = handle_sms_response(jordan["phone"], "SAFE")
        self.assertTrue(reply_res["success"])
        
        alex_final = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_final["status"], "working")
        self.assertEqual(alex_final["buddy_verification_status"], "confirmed_safe")
        self.assertEqual(len(app.services.monitor.monitoring_state["incidents"]), 0)

    def test_worker_timeout_and_buddy_not_safe(self):
        state = build_demo_state()
        state["environment"] = {"heat_index_c": 36.0}
        
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        
        # Timeout the check-in
        with state_lock:
            alex_ms = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
            alex_ms["check_in_sent_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            
        # Trigger timeout cycle
        current_state = app.services.monitor.monitoring_state
        res = _run_local_monitoring_cycle(current_state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        jordan = next(w for w in res["workers"] if w["id"] == "W002")
        
        # Buddy replies NOT SAFE, and emergency response toggle is ON
        set_emergency_response(True)
        self.sent_sms.clear()
        reply_res = handle_sms_response(jordan["phone"], "NOT SAFE")
        self.assertTrue(reply_res["success"])
        
        ms_final = app.services.monitor.monitoring_state
        alex_final = next(w for w in ms_final["workers"] if w["id"] == "W001")
        self.assertEqual(alex_final["status"], "supervisor_notified")
        self.assertEqual(alex_final["buddy_verification_status"], "confirmed_not_safe")
        
        # Incident should be created and escalated
        self.assertEqual(len(ms_final["incidents"]), 1)
        inc = ms_final["incidents"][0]
        self.assertEqual(inc["worker_id"], "W001")
        self.assertEqual(inc["status"], "escalated_supervisor")
        
        # Check supervisor SMS was sent and emergency response initiated
        self.assertEqual(len(self.sent_sms), 1)
        self.assertEqual(self.sent_sms[0]["to"], os.getenv("SUPERVISOR_PHONE", "+15550000999"))
        self.assertIn("Buddy verification indicates the worker may need assistance", self.sent_sms[0]["body"])
        
        # Verify emergency action log entry
        self.assertTrue(any("Emergency response initiated" in a for a in ms_final["agent_actions"]))

    def test_monitor_starts_with_no_environment(self):
        # 1. When monitor starts, environment is empty.
        state = build_demo_state()
        self.assertEqual(state["environment"], {})
        
        # 2. Verify worker risk assessment is skipped and workers are not marked high-risk
        res = _run_local_monitoring_cycle(state)
        for worker in res["workers"]:
            self.assertEqual(worker["status"], "working")

    def test_workers_not_marked_high_risk_before_first_success(self):
        state = build_demo_state()
        
        # Simulate a failed initial refresh that populates fallback environment
        state["environment"] = {
            "heat_index_c": 36.8,
            "metadata": {
                "source": "fallback_demo",
                "reason": "API Timeout"
            }
        }
        reset_monitoring_state(state)
        
        # Run cycle: workers should NOT be marked high-risk because it's a demo/fallback environment
        res = _run_local_monitoring_cycle(state)
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "working")
        self.assertIsNone(alex["check_in_status"])

    def test_successful_fortyguard_refresh_enables_risk_evaluation(self):
        state = build_demo_state()
        
        # Set a valid environment (non-fallback source)
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        reset_monitoring_state(state)
        
        # Run cycle: workers (Alex/Sam) should now be assessed and marked high-risk/awaiting_checkin
        res = _run_local_monitoring_cycle(state)
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        self.assertEqual(alex["check_in_status"], "pending")

    def test_later_refresh_failure_preserves_last_known_valid_environment(self):
        # Initialize with a valid environment
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        reset_monitoring_state(state)
        
        # Verify it starts with valid environment
        self.assertEqual(app.services.monitor.monitoring_state["environment"]["heat_index_c"], 36.0)
        
        # Simulate a failed background refresh worker run
        original_get_env = app.services.monitor.get_environmental_data
        try:
            def mock_get_env_error(*args, **kwargs):
                raise Exception("FortyGuard Connection Timeout")
            app.services.monitor.get_environmental_data = mock_get_env_error
            
            # Run the worker synchronously for testing
            app.services.monitor._async_refresh_worker(state)
            
            # The valid environment should be preserved (NOT replaced by fallback or cleared!)
            ms = app.services.monitor.monitoring_state
            self.assertEqual(ms["environment"]["metadata"]["source"], "fortyguard_api")
            self.assertEqual(ms["environment"]["heat_index_c"], 36.0)
            self.assertEqual(ms["current_step"], "environment_refresh_failed")
            
        finally:
            app.services.monitor.get_environmental_data = original_get_env

    def test_local_monitoring_continues_while_fortyguard_processing(self):
        # 1. Set refresh thread active
        app.services.monitor.refresh_thread_active = True
        
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        reset_monitoring_state(state)
        
        # 2. Run monitoring cycle. It should NOT block and should still process local evaluations
        res = _run_local_monitoring_cycle(state)
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin") # Local monitoring ran successfully!
        
        # Reset flag
        app.services.monitor.refresh_thread_active = False

    def test_continuous_high_risk_confirmed_remains_working(self):
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        reset_monitoring_state(state)
            
        # 1. Run local monitoring cycle -> worker becomes awaiting_checkin
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        self.assertEqual(alex["check_in_status"], "pending")

        # 2. Worker replies OK -> state becomes working and check_in_status becomes confirmed
        reply_res = handle_sms_response(alex["phone"], "OK")
        self.assertTrue(reply_res["success"])
        
        # 3. Verify worker state is back to working
        alex_confirmed = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_confirmed["status"], "working")
        self.assertEqual(alex_confirmed["check_in_status"], "confirmed")
        
        # 4. Run several subsequent monitoring cycles. Worker must remain in "working" status
        for _ in range(5):
            res_cycle = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            with state_lock:
                app.services.monitor.monitoring_state = res_cycle
                
            alex_cycle = next(w for w in res_cycle["workers"] if w["id"] == "W001")
            self.assertEqual(alex_cycle["status"], "working", "Worker must not immediately change back to high_risk")
            self.assertEqual(alex_cycle["check_in_status"], "confirmed")

    def test_stuck_refresh_recovery_after_reset(self):
        # 1. Simulate stuck refresh by setting the flag to True
        with app.services.monitor.refresh_lock:
            app.services.monitor.refresh_thread_active = True
            
        # 2. Verify starting a refresh is skipped
        state = build_demo_state()
        self.assertTrue(app.services.monitor.refresh_thread_active)
        
        # 3. Reset monitoring state
        reset_monitoring_state(state)
        
        # 4. Verify that refresh flag is cleared after reset
        with app.services.monitor.refresh_lock:
            self.assertFalse(app.services.monitor.refresh_thread_active)
            
        # 5. Verify a new refresh can be successfully triggered
        due = app.services.monitor._environment_refresh_due(app.services.monitor.monitoring_state)
        self.assertTrue(due)

    def test_worker_safe_response(self):
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        
        # Simulate worker replying SAFE
        self.sent_sms.clear()
        reply_res = handle_sms_response(alex["phone"], "SAFE")
        self.assertTrue(reply_res["success"])
        
        # Verify worker transitions back to working
        alex_updated = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_updated["status"], "working")
        self.assertEqual(alex_updated["check_in_status"], "confirmed")

    def test_worker_not_safe_response(self):
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        
        # Simulate worker replying NOT SAFE
        self.sent_sms.clear()
        set_emergency_response(True)
        reply_res = handle_sms_response(alex["phone"], "NOT SAFE")
        self.assertTrue(reply_res["success"])
        
        # Verify worker transitions to supervisor_notified
        alex_updated = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_updated["status"], "supervisor_notified")
        self.assertEqual(alex_updated["check_in_status"], "not_safe")
        
        # Verify incident created and escalated
        ms = app.services.monitor.monitoring_state
        self.assertEqual(len(ms["incidents"]), 1)
        inc = ms["incidents"][0]
        self.assertEqual(inc["worker_id"], "W001")
        self.assertEqual(inc["status"], "escalated_supervisor")
        
        # Verify supervisor notified
        self.assertEqual(len(self.sent_sms), 1)
        self.assertEqual(self.sent_sms[0]["to"], os.getenv("SUPERVISOR_PHONE", "+15550000999"))
        self.assertIn("reported NOT SAFE", self.sent_sms[0]["body"])
        
        # Verify emergency response log entry
        self.assertTrue(any("Emergency response initiated" in a for a in ms["agent_actions"]))

    def test_duplicate_responses_ignored(self):
        state = build_demo_state()
        state["environment"] = {
            "heat_index_c": 36.0,
            "metadata": {
                "source": "fortyguard_api"
            }
        }
        with state_lock:
            app.services.monitor.monitoring_state = state
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in res["workers"] if w["id"] == "W001")
        
        # First reply OK -> resolved
        handle_sms_response(alex["phone"], "OK")
        
        # Verify confirmed
        alex_confirmed = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex_confirmed["status"], "working")
        
        # Duplicate response
        reply_dup = handle_sms_response(alex["phone"], "OK")
        self.assertFalse(reply_dup["success"])
        self.assertEqual(reply_dup["message"], "Sentinel: Phone number not recognized or no pending safety check-ins found.")
        
        # Make sure no incidents were created
        self.assertEqual(len(app.services.monitor.monitoring_state["incidents"]), 0)

    def test_timeout_mode_production(self):
        # 1. Force DEMO_MODE=false or absent
        if "DEMO_MODE" in os.environ:
            del os.environ["DEMO_MODE"]
            
        # 2. Build demo state
        state = build_demo_state()
        alex = next(w for w in state["workers"] if w["id"] == "W001")
        # Production timeout must be 300 seconds
        self.assertEqual(alex["check_in_timeout_seconds"], 300)

    def test_timeout_mode_demo(self):
        # 1. Force DEMO_MODE=true
        os.environ["DEMO_MODE"] = "true"
        try:
            state = build_demo_state()
            alex = next(w for w in state["workers"] if w["id"] == "W001")
            # Demo timeout must be 20 seconds
            self.assertEqual(alex["check_in_timeout_seconds"], 20)
            
            # 2. Trigger check-in
            state["environment"] = {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}}
            reset_monitoring_state(state)
            
            res = _run_local_monitoring_cycle(state)
            with state_lock:
                app.services.monitor.monitoring_state = res
                
            alex = next(w for w in res["workers"] if w["id"] == "W001")
            self.assertEqual(alex["status"], "awaiting_checkin")
            self.assertEqual(alex["check_in_status"], "pending")
            
            # Artificially set check_in_sent_at to 21 seconds ago
            with state_lock:
                alex_ms = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
                alex_ms["check_in_sent_at"] = (datetime.now(timezone.utc) - timedelta(seconds=21)).isoformat()
                
            # Run cycle: should trigger timeout to unresponsive and notify buddy W002 (Jordan)
            self.sent_sms.clear()
            res2 = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            with state_lock:
                app.services.monitor.monitoring_state = res2
                
            alex = next(w for w in res2["workers"] if w["id"] == "W001")
            self.assertEqual(alex["status"], "unresponsive")
            self.assertEqual(alex["check_in_status"], "timed_out")
            self.assertEqual(alex["buddy_verification_status"], "pending")
            
            # Ensure buddy notification was sent exactly once (1 SMS)
            self.assertEqual(len(self.sent_sms), 1)
            self.assertEqual(self.sent_sms[0]["to"], "+15550000002") # Jordan's phone
            
            # Duplicate cycle: check that no duplicate buddy notification occurs
            self.sent_sms.clear()
            res3 = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            self.assertEqual(len(self.sent_sms), 0)
            
        finally:
            # Clear DEMO_MODE env var
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]

    def test_worker_data_persists_after_reset(self):
        # 1. Update a worker's phone in the DB
        from app.services.database import update_worker_phone
        update_worker_phone("W001", "+19999999999")
        
        # 2. Reset scenario state
        state = build_demo_state()
        reset_monitoring_state(state)
        
        # 3. Verify that the updated phone number is loaded from the DB and is NOT destroyed/overwritten
        alex = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex["phone"], "+19999999999")
        
        # Restore default for subsequent tests
        update_worker_phone("W001", "+15550000001")

    def test_demo_mode_maps_configured_phone(self):
        import app.telegram as tg_module
        original_discovered = tg_module.discovered_chat_id
        tg_module.discovered_chat_id = "987654"
        
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "+919324023132"
        try:
            state = build_demo_state()
            alex = next(w for w in state["workers"] if w["id"] == "W001")
            # build_demo_state sets telegram_chat_id (not phone) from the discovered chat ID
            self.assertEqual(alex["telegram_chat_id"], "987654")
            # phone must remain the worker's actual phone number, unchanged
            self.assertEqual(alex["phone"], "+15550000001")
        finally:
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_telegram_duplicate_response_ignored(self):
        import app.telegram as tg_module
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        original_discovered = tg_module.discovered_chat_id
        
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        tg_module.discovered_chat_id = "987654"
        
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "987654"
        try:
            state = build_demo_state()
            state["environment"] = {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}}
            reset_monitoring_state(state)
            
            # Trigger check-in
            res = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            with state_lock:
                app.services.monitor.monitoring_state = res
                
            # Mock get_telegram_updates to return SAFE first
            import requests
            original_get = requests.get
            
            def mock_get_first(url, params=None, timeout=10):
                class MockResponse:
                    status_code = 200
                    def json(self):
                        return {
                            "ok": True,
                            "result": [
                                {
                                    "update_id": 20001,
                                    "message": {
                                        "message_id": 10,
                                        "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                        "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                        "date": 1600000005,
                                        "text": "SAFE"
                                    }
                                }
                            ]
                        }
                return MockResponse()
                
            requests.get = mock_get_first
            
            # Process first - should succeed and transition worker
            processed = tg_module.process_telegram_replies()
            self.assertEqual(len(processed), 1)
            self.assertTrue(processed[0]["result"]["success"])
            
            # Mock get_telegram_updates to return SAFE again (duplicate)
            def mock_get_second(url, params=None, timeout=10):
                class MockResponse:
                    status_code = 200
                    def json(self):
                        return {
                            "ok": True,
                            "result": [
                                {
                                    "update_id": 20002,
                                    "message": {
                                        "message_id": 11,
                                        "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                        "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                        "date": 1600000010,
                                        "text": "SAFE"
                                    }
                                }
                            ]
                        }
                return MockResponse()
                
            requests.get = mock_get_second
            
            # Process second - should return success=False
            processed2 = tg_module.process_telegram_replies()
            self.assertEqual(len(processed2), 1)
            self.assertFalse(processed2[0]["result"]["success"])
            self.assertIn("not recognized", processed2[0]["result"]["message"])
            
        finally:
            requests.get = original_get
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_telegram_not_safe_triggers_workflow(self):
        import app.telegram as tg_module
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        original_discovered = tg_module.discovered_chat_id
        
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        tg_module.discovered_chat_id = "987654"
        
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "987654"
        try:
            state = build_demo_state()
            state["environment"] = {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}}
            reset_monitoring_state(state)
            
            # Trigger check-in
            res = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            with state_lock:
                app.services.monitor.monitoring_state = res
                
            # Mock get_telegram_updates to return NOT SAFE reply
            import requests
            original_get = requests.get
            
            def mock_get(url, params=None, timeout=10):
                class MockResponse:
                    status_code = 200
                    def json(self):
                        return {
                            "ok": True,
                            "result": [
                                {
                                    "update_id": 30001,
                                    "message": {
                                        "message_id": 20,
                                        "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                        "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                        "date": 1600000005,
                                        "text": "NOT SAFE"
                                    }
                                }
                            ]
                        }
                return MockResponse()
                
            requests.get = mock_get
            
            processed = tg_module.process_telegram_replies()
            self.assertEqual(len(processed), 1)
            self.assertEqual(processed[0]["text"], "NOT SAFE")
            self.assertTrue(processed[0]["result"]["success"])
            
            # Verify incident created
            ms = app.services.monitor.monitoring_state
            self.assertEqual(len(ms["incidents"]), 1)
            self.assertEqual(ms["incidents"][0]["status"], "escalated_supervisor")
            
        finally:
            requests.get = original_get
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_telegram_message_construction(self):
        from app.telegram import send_telegram_message
        
        # Mock env token
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        
        import app.telegram as tg_module
        tg_module.TELEGRAM_BOT_TOKEN = "123456:mock_token"
        
        import requests
        original_post = requests.post
        captured_requests = []
        
        def mock_post(url, json, timeout):
            captured_requests.append({"url": url, "json": json})
            class MockResponse:
                status_code = 200
                def json(self):
                    return {"ok": True, "result": {"message_id": 999}}
            return MockResponse()
            
        requests.post = mock_post
        
        try:
            res = send_telegram_message("987654321", "Hello from Sentinel!")
            self.assertTrue(res["success"])
            self.assertEqual(len(captured_requests), 1)
            self.assertEqual(captured_requests[0]["url"], "https://api.telegram.org/bot123456:mock_token/sendMessage")
            self.assertEqual(captured_requests[0]["json"]["chat_id"], "987654321")
            self.assertEqual(captured_requests[0]["json"]["text"], "Hello from Sentinel!")
        finally:
            requests.post = original_post
            tg_module.TELEGRAM_BOT_TOKEN = original_token
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)

    def test_telegram_start_chat_id_discovery(self):
        import app.telegram as tg_module
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        original_discovered = tg_module.discovered_chat_id
        
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        tg_module.discovered_chat_id = None
        
        import requests
        original_get = requests.get
        
        def mock_get(url, params=None, timeout=10):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 10001,
                                "message": {
                                    "message_id": 1,
                                    "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                    "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                    "date": 1600000000,
                                    "text": "/start"
                                }
                            }
                        ]
                    }
            return MockResponse()
            
        requests.get = mock_get
        
        try:
            updates = tg_module.get_telegram_updates()
            self.assertEqual(len(updates), 1)
            self.assertEqual(tg_module.discovered_chat_id, "987654")
        finally:
            requests.get = original_get
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            tg_module.discovered_chat_id = original_discovered

    def test_telegram_safe_response_routing(self):
        import app.telegram as tg_module
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        original_discovered = tg_module.discovered_chat_id
        
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        tg_module.discovered_chat_id = "987654"
        
        # 1. Build state where W001 has phone mapped to "987654"
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "987654"
        
        state = build_demo_state()
        state["environment"] = {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}}
        reset_monitoring_state(state)
        
        # Trigger check-in to put Alex W001 into awaiting_checkin
        res = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        # telegram_chat_id (not phone) is set to the discovered chat ID
        self.assertEqual(alex["telegram_chat_id"], "987654")
        
        # Mock get_telegram_updates to return SAFE reply from chat_id "987654"
        import requests
        original_get = requests.get
        
        def mock_get(url, params=None, timeout=10):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 10002,
                                "message": {
                                    "message_id": 2,
                                    "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                    "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                    "date": 1600000005,
                                    "text": "SAFE"
                                }
                            }
                        ]
                    }
            return MockResponse()
            
        requests.get = mock_get
        
        try:
            processed = tg_module.process_telegram_replies()
            self.assertEqual(len(processed), 1)
            self.assertEqual(processed[0]["chat_id"], "987654")
            self.assertEqual(processed[0]["text"], "SAFE")
            self.assertTrue(processed[0]["result"]["success"])
            
            # Verify worker W001 is back to working
            alex_updated = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
            self.assertEqual(alex_updated["status"], "working")
            self.assertEqual(alex_updated["check_in_status"], "confirmed")
            
        finally:
            requests.get = original_get
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_telegram_autonomous_replies_routing(self):
        import app.telegram as tg_module
        original_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        original_discovered = tg_module.discovered_chat_id
        
        os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock_token"
        tg_module.discovered_chat_id = "987654"
        
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "987654"
        
        # Initialize state
        state = build_demo_state()
        state["environment"] = {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}}
        reset_monitoring_state(state)
        
        # Trigger check-in
        res = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
        with state_lock:
            app.services.monitor.monitoring_state = res
            
        alex = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(alex["status"], "awaiting_checkin")
        self.assertEqual(alex["check_in_status"], "pending")
        
        # Mock requests.get to return "OK"
        import requests
        original_get = requests.get
        
        def mock_get(url, params=None, timeout=10):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "ok": True,
                        "result": [
                            {
                                "update_id": 40001,
                                "message": {
                                    "message_id": 40,
                                    "from": {"id": 987654, "is_bot": False, "first_name": "Test"},
                                    "chat": {"id": 987654, "first_name": "Test", "type": "private"},
                                    "date": 1600000005,
                                    "text": "OK"
                                }
                            }
                        ]
                    }
            return MockResponse()
            
        requests.get = mock_get
        
        try:
            # We call process_telegram_replies directly to simulate background cycle processing
            processed = tg_module.process_telegram_replies()
            self.assertEqual(len(processed), 1)
            self.assertEqual(processed[0]["text"], "OK")
            self.assertTrue(processed[0]["result"]["success"])
            
            # Now run the local monitoring cycle: since check-in was confirmed, the worker should be "working"
            res2 = _run_local_monitoring_cycle(app.services.monitor.monitoring_state)
            with state_lock:
                app.services.monitor.monitoring_state = res2
                
            alex_updated = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
            self.assertEqual(alex_updated["status"], "working")
            self.assertEqual(alex_updated["check_in_status"], "confirmed")
            
        finally:
            requests.get = original_get
            if original_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = original_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_lifecycle_start_stop_start(self):
        import threading
        # start
        res1 = start_monitoring(build_demo_state())
        self.assertTrue(res1["active"])
        self.assertTrue(app.services.monitor.monitoring_active)
        self.assertIsNotNone(app.services.monitor.monitoring_thread)
        t1 = app.services.monitor.monitoring_thread
        
        # stop
        res2 = stop_monitoring()
        self.assertFalse(res2["active"])
        self.assertFalse(app.services.monitor.monitoring_active)
        self.assertFalse(t1.is_alive())
        
        # start again
        res3 = start_monitoring(build_demo_state())
        self.assertTrue(res3["active"])
        self.assertTrue(app.services.monitor.monitoring_active)
        self.assertIsNotNone(app.services.monitor.monitoring_thread)
        t2 = app.services.monitor.monitoring_thread
        self.assertNotEqual(t1, t2)
        
        stop_monitoring()

    def test_lifecycle_start_reset_start(self):
        start_monitoring(build_demo_state())
        t1 = app.services.monitor.monitoring_thread
        
        # reset
        reset_monitoring_state(build_demo_state())
        self.assertFalse(app.services.monitor.monitoring_active)
        self.assertFalse(t1.is_alive())
        self.assertIsNone(app.services.monitor.monitoring_thread)
        
        # start
        start_monitoring(build_demo_state())
        self.assertTrue(app.services.monitor.monitoring_active)
        t2 = app.services.monitor.monitoring_thread
        self.assertTrue(t2.is_alive())
        
        stop_monitoring()

    def test_lifecycle_start_stop_stop(self):
        start_monitoring(build_demo_state())
        stop_monitoring()
        stop_monitoring() # Should be safe and idempotent
        self.assertFalse(app.services.monitor.monitoring_active)
        self.assertIsNone(app.services.monitor.monitoring_thread)

    def test_lifecycle_start_start(self):
        start_monitoring(build_demo_state())
        t1 = app.services.monitor.monitoring_thread
        
        # second start should be idempotent and not create a new thread
        start_monitoring(build_demo_state())
        t2 = app.services.monitor.monitoring_thread
        self.assertEqual(t1, t2)
        
        stop_monitoring()

    def test_lifecycle_reset_while_active(self):
        start_monitoring(build_demo_state())
        t1 = app.services.monitor.monitoring_thread
        self.assertTrue(t1.is_alive())
        
        # reset monitoring while active
        reset_monitoring_state(build_demo_state())
        self.assertFalse(t1.is_alive())
        self.assertFalse(app.services.monitor.monitoring_active)
        self.assertIsNone(app.services.monitor.monitoring_thread)

    def test_lifecycle_rapid_stop_start(self):
        import threading
        start_monitoring(build_demo_state())
        for _ in range(5):
            stop_monitoring()
            start_monitoring(build_demo_state())
            
        t = app.services.monitor.monitoring_thread
        self.assertTrue(t.is_alive())
        self.assertTrue(app.services.monitor.monitoring_active)
        
        # Verify only one monitoring thread is actually running in background
        active_monitors = [th for th in threading.enumerate() if th.name == "sentinel-monitor"]
        self.assertEqual(len(active_monitors), 1)
        
        stop_monitoring()

    def test_lifecycle_rapid_reset_start(self):
        import threading
        start_monitoring(build_demo_state())
        for _ in range(5):
            reset_monitoring_state(build_demo_state())
            start_monitoring(build_demo_state())
            
        t = app.services.monitor.monitoring_thread
        self.assertTrue(t.is_alive())
        self.assertTrue(app.services.monitor.monitoring_active)
        
        active_monitors = [th for th in threading.enumerate() if th.name == "sentinel-monitor"]
        self.assertEqual(len(active_monitors), 1)
        
        stop_monitoring()

    def test_lifecycle_thread_count_integrity(self):
        import threading
        start_monitoring(build_demo_state())
        active_monitors = [th for th in threading.enumerate() if th.name == "sentinel-monitor"]
        self.assertEqual(len(active_monitors), 1)
        
        start_monitoring(build_demo_state())
        active_monitors = [th for th in threading.enumerate() if th.name == "sentinel-monitor"]
        self.assertEqual(len(active_monitors), 1)
        
        stop_monitoring()
        active_monitors = [th for th in threading.enumerate() if th.name == "sentinel-monitor"]
        self.assertEqual(len(active_monitors), 0)



    # -----------------------------------------------------------------------
    # Telegram routing regression tests
    # -----------------------------------------------------------------------

    def _make_high_risk_state_with_chat_id(self, alex_telegram_chat_id=None):
        state = {
            "latitude": 40.7128, "longitude": -74.0060, "temperature": 32.5,
            "environment": {"heat_index_c": 36.0, "metadata": {"source": "fortyguard_api"}},
            "workers": [
                {"id": "W001", "name": "Alex", "latitude": 40.7128, "longitude": -74.0060,
                 "task": "Road maintenance", "exposure_minutes": 60, "status": "working",
                 "buddy_id": "W002", "phone": "+15550000001", "telegram_chat_id": alex_telegram_chat_id,
                 "check_in_status": None, "check_in_sent_at": None, "check_in_timeout_seconds": 300,
                 "buddy_verification_status": None, "buddy_notified_at": None},
                {"id": "W002", "name": "Jordan", "latitude": 40.7128, "longitude": -74.0060,
                 "task": "Equipment inspection", "exposure_minutes": 30, "status": "working",
                 "buddy_id": "W001", "phone": "+15550000002", "telegram_chat_id": None,
                 "check_in_status": None, "check_in_sent_at": None, "check_in_timeout_seconds": 300,
                 "buddy_verification_status": None, "buddy_notified_at": None},
            ],
            "incidents": [], "agent_actions": [], "current_step": "starting",
            "pending_actions": [], "monitoring_active": True, "emergency_response_enabled": False,
        }
        with state_lock:
            app.services.monitor.monitoring_state = state
        return state

    def test_telegram_routing_alex_uses_real_chat_id(self):
        REAL = "1187511245"
        state = self._make_high_risk_state_with_chat_id(alex_telegram_chat_id=REAL)
        res = _run_local_monitoring_cycle(state)
        self.assertEqual(next(w for w in res["workers"] if w["id"] == "W001")["status"], "awaiting_checkin")
        self.assertTrue(any(m["to"] == REAL for m in self.sent_sms), f"Expected msg to {REAL}: {self.sent_sms}")
        self.assertFalse(any(m["to"] == "+15550000001" for m in self.sent_sms), "Must not use phone when chat_id set")

    def test_telegram_routing_alex_without_chat_id_uses_phone(self):
        state = self._make_high_risk_state_with_chat_id(alex_telegram_chat_id=None)
        _run_local_monitoring_cycle(state)
        self.assertTrue(any(m["to"] == "+15550000001" for m in self.sent_sms))

    def test_telegram_routing_jordan_stays_simulated(self):
        import requests as req_module
        orig = req_module.post
        try:
            def bad(*a, **k): raise AssertionError("Jordan must not hit Telegram API")
            req_module.post = bad
            from app.telegram import send_telegram_message
            r = send_telegram_message("+15550000002", "alert")
            self.assertTrue(r["demo"])
        finally:
            req_module.post = orig

    def test_telegram_routing_numeric_id_not_simulated(self):
        import os, requests as req_module
        orig_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        orig_post = req_module.post
        calls = []
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
            class R:
                status_code = 200
                def json(self): return {"result": {"message_id": 1}}
            def capture(*a, **k):
                calls.append(1)
                return R()
            req_module.post = capture
            from app.telegram import send_telegram_message
            r = send_telegram_message("1187511245", "check-in")
            self.assertFalse(r.get("demo"))
            self.assertEqual(len(calls), 1)
        finally:
            if orig_token:
                os.environ["TELEGRAM_BOT_TOKEN"] = orig_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            req_module.post = orig_post

    def test_telegram_routing_safe_reply_confirms_alex(self):
        REAL = "1187511245"
        state = self._make_high_risk_state_with_chat_id(alex_telegram_chat_id=REAL)
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        self.assertTrue(handle_sms_response(REAL, "SAFE")["success"])
        with state_lock:
            w = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertEqual(w["status"], "working")
        self.assertEqual(w["check_in_status"], "confirmed")

    def test_telegram_routing_phone_reply_does_not_confirm_when_chat_id_set(self):
        REAL = "1187511245"
        state = self._make_high_risk_state_with_chat_id(alex_telegram_chat_id=REAL)
        res = _run_local_monitoring_cycle(state)
        with state_lock:
            app.services.monitor.monitoring_state = res
        handle_sms_response("+15550000001", "SAFE")
        with state_lock:
            w = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
        self.assertNotEqual(w["status"], "working")

    def test_telegram_routing_timeout_escalates_to_jordan(self):
        REAL = "1187511245"
        self._make_high_risk_state_with_chat_id(alex_telegram_chat_id=REAL)
        with state_lock:
            alex = next(w for w in app.services.monitor.monitoring_state["workers"] if w["id"] == "W001")
            alex.update({"status": "awaiting_checkin", "check_in_status": "pending",
                         "check_in_sent_at": (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat(),
                         "check_in_timeout_seconds": 300})
        self.sent_sms.clear()
        with state_lock:
            cur = app.services.monitor.monitoring_state
        _run_local_monitoring_cycle(cur)
        self.assertTrue(any(m["to"] == "+15550000002" for m in self.sent_sms),
                        f"Jordan must get buddy alert: {self.sent_sms}")

    def test_demo_reset_does_not_inherit_stale_telegram_state(self):
        # Regression: a previous live session persisted an invalid phone-formatted
        # value ("+919324023132") into the DB telegram_chat_id column, and
        # DEMO_PHONE_NUMBER held the same phone. build_demo_state() must never
        # configure Alex's Telegram identity from either source — only a real
        # discovered chat ID.
        from app.services.database import update_worker_telegram_chat_id
        import app.telegram as tg_module
        original_discovered = tg_module.discovered_chat_id
        tg_module.discovered_chat_id = None
        os.environ["DEMO_MODE"] = "true"
        os.environ["DEMO_PHONE_NUMBER"] = "+919324023132"
        update_worker_telegram_chat_id("W001", "+919324023132")
        try:
            state = build_demo_state()
            alex = next(w for w in state["workers"] if w["id"] == "W001")
            self.assertIsNone(alex["telegram_chat_id"])
            self.assertEqual(alex["phone"], "+15550000001")

            # Jordan and Sam must remain simulated demo recipients
            jordan = next(w for w in state["workers"] if w["id"] == "W002")
            sam = next(w for w in state["workers"] if w["id"] == "W003")
            self.assertIsNone(jordan["telegram_chat_id"])
            self.assertIsNone(sam["telegram_chat_id"])
            self.assertEqual(jordan["phone"], "+15550000002")
            self.assertEqual(sam["phone"], "+15550000003")
        finally:
            update_worker_telegram_chat_id("W001", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]
            if "DEMO_PHONE_NUMBER" in os.environ:
                del os.environ["DEMO_PHONE_NUMBER"]

    def test_demo_state_uses_valid_persisted_chat_id(self):
        # The real discovered chat ID persisted in the DB from a previous live
        # session must still be used for Alex's live Telegram check-in.
        from app.services.database import update_worker_telegram_chat_id
        import app.telegram as tg_module
        original_discovered = tg_module.discovered_chat_id
        tg_module.discovered_chat_id = None
        os.environ["DEMO_MODE"] = "true"
        update_worker_telegram_chat_id("W001", "1187511245")
        try:
            state = build_demo_state()
            alex = next(w for w in state["workers"] if w["id"] == "W001")
            self.assertEqual(alex["telegram_chat_id"], "1187511245")
            self.assertEqual(alex["phone"], "+15550000001")
        finally:
            update_worker_telegram_chat_id("W001", None)
            tg_module.discovered_chat_id = original_discovered
            if "DEMO_MODE" in os.environ:
                del os.environ["DEMO_MODE"]


if __name__ == '__main__':
    unittest.main()
