import base64
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx


PACKAGE_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = PACKAGE_DIR / "provider" / "main.py"
SPEC = importlib.util.spec_from_file_location("usage_data_provider", ENTRYPOINT)
provider = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider)


def _conversation(index, username="00123", kind="chat"):
    return {
        "session_id": f"fixture-session-{index}",
        "session_title": f"测试会话 {index}",
        "kind": kind,
        "user_id": f"fixture-user-{username}",
        "username": username,
        "full_name": "测试用户",
        "status": "completed",
        "model_name": "fixture-model",
        "message_count": 2,
        "artifact_count": 1,
        "total_cost_usd": index / 10,
        "total_input_tokens": index * 100,
        "total_output_tokens": index * 10,
        "total_tokens": index * 110,
        "created_at": "2026-10-01T00:00:00+08:00",
        "updated_at": "2026-10-07T23:59:59.999999+08:00",
    }


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            _conversation(1),
            _conversation(2, "00456", "scheduled"),
            _conversation(3, "00789", "scheduled"),
            _conversation(4, "00789"),
            _conversation(5, "123"),
            _conversation(6, None, "embed"),
            _conversation(7, "00999", "external_api"),
            _conversation(8, "00999", "workflow"),
        ]
        self.calls = []
        self.page_size = 2
        self.role = "admin"
        self.login_error = False
        self.list_error = None
        self.empty_offset = None
        self.failed_offset = None
        self.transport = httpx.MockTransport(self._handle_request)
        real_client = httpx.Client
        client_patch = patch.object(
            provider.httpx,
            "Client",
            side_effect=lambda **kwargs: real_client(
                transport=self.transport, **kwargs
            ),
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _handle_request(self, request):
        self.calls.append(request)
        if request.url.path == "/api/v1/auth/login":
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                json.loads(request.content),
                {"username": "test-admin", "password": "test-password"},
            )
            if self.login_error:
                return httpx.Response(
                    400, json={"code": 400, "message": "fixture invalid password"}
                )
            data = {"access_token": "fixture-token"}
        else:
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                request.headers["Authorization"], "Bearer fixture-token"
            )
            if request.url.path == "/api/v1/auth/me":
                data = {
                    "id": "fixture-admin",
                    "username": "test-admin",
                    "full_name": "测试管理员",
                    "role": self.role,
                }
            else:
                self.assertEqual(request.url.path, "/api/v1/admin/conversations")
                offset = int(request.url.params["offset"])
                if self.list_error == "timeout":
                    raise httpx.ReadTimeout("fixture timeout")
                if self.list_error == "network":
                    raise httpx.ConnectError("fixture connection failure")
                if self.list_error == "non_json":
                    return httpx.Response(502, text="fixture bad gateway")
                if isinstance(self.list_error, int) or offset == self.failed_offset:
                    status = self.list_error or 503
                    return httpx.Response(
                        status, json={"code": status, "message": "fixture error"}
                    )
                items = self.items
                if "kind" in request.url.params:
                    kind = request.url.params["kind"]
                    items = [item for item in items if item["kind"] == kind]
                limit = min(int(request.url.params["limit"]), self.page_size)
                data = {
                    "items": items[offset:offset + limit],
                    "total": len(items),
                    "users": [{"user_id": "unfiltered-user"}],
                    "available_kinds": ["chat", "scheduled"],
                }
                if offset == self.empty_offset:
                    data["items"] = []
        return httpx.Response(200, json={"code": 0, "data": data})

    def _request(self, operation, context):
        request = {
            "protocol_version": 1,
            "operation": operation,
            "context": context,
        }
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode()))
        self.addCleanup(stdin.close)
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
            provider.main()
        return json.loads(stdout.getvalue())

    def _context(self):
        return {
            "configuration": {"public": {"api_base_url": "https://fixture/api/v1"}},
            "credentials": {"username": "test-admin", "password": "test-password"},
            "tool_name": "get_usage_dataset",
        }

    def _invoke(self, **arguments):
        context = self._context()
        context["arguments"] = {
            "start_date": "2026-10-01",
            "end_date": "2026-10-07",
            **arguments,
        }
        return self._request("tool_invoke", context)

    def _dataset(self, response):
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["result"]["is_error"])
        overview, resource = response["result"]["content"]
        self.assertEqual(resource["mime_type"], "application/gzip")
        dataset = json.loads(gzip.decompress(base64.b64decode(resource["data"])))
        self.assertEqual(json.loads(overview["text"])["totals"], dataset["totals"])
        return dataset

    def _assert_error(self, response, code):
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code)
        self.assertFalse(response["error"]["retryable"])

    def _list_calls(self):
        return [call for call in self.calls if call.url.path.endswith("/conversations")]

    def test_collects_all_pages_and_summarizes_selected_conversations(self):
        dataset = self._dataset(self._invoke())
        self.assertEqual(dataset["items"], self.items)
        totals = dataset["totals"]
        self.assertEqual(totals["total_conversations"], 8)
        self.assertEqual(totals["active_users"], 6)
        self.assertAlmostEqual(totals["total_cost_usd"], 3.6)
        self.assertEqual(totals["total_input_tokens"], 3600)
        self.assertEqual(totals["total_output_tokens"], 360)
        self.assertEqual(totals["total_tokens"], 3960)
        self.assertEqual(dataset["cost_basis"], "session_lifetime")
        self.assertEqual(dataset["timezone"], "Asia/Shanghai")
        self.assertEqual(
            [call.url.params["offset"] for call in self._list_calls()],
            ["0", "2", "4", "6"],
        )
        self.assertNotIn("users", dataset)

    def test_time_window_includes_complete_beijing_days(self):
        self._dataset(self._invoke())
        for call in self._list_calls():
            self.assertEqual(call.url.params["time_field"], "updated_at")
            self.assertEqual(
                call.url.params["start_time"], "2026-10-01T00:00:00+08:00"
            )
            self.assertEqual(
                call.url.params["end_time"], "2026-10-07T23:59:59.999999+08:00"
            )
            self.assertEqual(call.url.params["limit"], "200")
            self.assertNotIn("kind", call.url.params)

    def test_can_filter_by_creation_time(self):
        dataset = self._dataset(self._invoke(time_field="created_at"))
        self.assertEqual(dataset["filters"]["time_field"], "created_at")
        self.assertTrue(all(
            call.url.params["time_field"] == "created_at"
            for call in self._list_calls()
        ))

    def test_kind_is_forwarded_using_backend_values(self):
        for kind in ("chat", "scheduled", "external_api", "embed", "workflow"):
            with self.subTest(kind=kind):
                self.calls.clear()
                dataset = self._dataset(self._invoke(kind=kind))
                expected = [item for item in self.items if item["kind"] == kind]
                self.assertEqual(dataset["items"], expected)
                self.assertEqual(dataset["filters"]["kind"], kind)
                self.assertTrue(all(
                    call.url.params["kind"] == kind for call in self._list_calls()
                ))

    def test_excludes_multiple_exact_employee_numbers(self):
        dataset = self._dataset(self._invoke(
            exclude_employee_numbers=" 00123, 00456,00123 "
        ))
        self.assertEqual(
            dataset["items"], [item for item in self.items if item["session_id"]
                               not in {"fixture-session-1", "fixture-session-2"}]
        )
        self.assertEqual(
            dataset["filters"]["exclude_employee_numbers"], ["00123", "00456"]
        )
        self.assertEqual(dataset["totals"]["total_conversations"], 6)
        self.assertEqual(dataset["totals"]["active_users"], 4)
        self.assertAlmostEqual(dataset["totals"]["total_cost_usd"], 3.3)
        self.assertTrue(all(
            "exclude_employee_numbers" not in call.url.params
            for call in self._list_calls()
        ))

    def test_combines_kind_and_employee_exclusions(self):
        dataset = self._dataset(self._invoke(
            kind="scheduled", exclude_employee_numbers="00456"
        ))
        self.assertEqual(dataset["items"], [self.items[2]])
        self.assertEqual(dataset["totals"]["total_conversations"], 1)
        self.assertEqual(dataset["totals"]["active_users"], 1)
        self.assertEqual(dataset["totals"]["total_input_tokens"], 300)
        self.assertAlmostEqual(dataset["totals"]["total_cost_usd"], 0.3)

    def test_excluded_full_page_does_not_stop_pagination(self):
        self.page_size = 200
        self.items = [_conversation(index) for index in range(200)]
        self.items.append(_conversation(201, "00456"))
        dataset = self._dataset(self._invoke(exclude_employee_numbers="00123"))
        self.assertEqual(dataset["items"], [self.items[-1]])
        self.assertEqual(len(self._list_calls()), 2)
        self.assertEqual(self._list_calls()[1].url.params["offset"], "200")

    def test_empty_selection_has_zero_totals(self):
        for items in ([], self.items):
            with self.subTest(items=len(items)):
                self.items = items
                dataset = self._dataset(self._invoke(kind="unknown-kind"))
                self.assertEqual(dataset["items"], [])
                self.assertTrue(all(value == 0 for value in dataset["totals"].values()))

    def test_all_employees_excluded_has_zero_totals(self):
        self.items = self.items[:2]
        dataset = self._dataset(self._invoke(
            exclude_employee_numbers="00123,00456"
        ))
        self.assertEqual(dataset["items"], [])
        self.assertTrue(all(value == 0 for value in dataset["totals"].values()))

    def test_invalid_arguments_do_not_call_upstream(self):
        cases = [
            {"start_date": "20261001"},
            {"start_date": "2026-02-30"},
            {"start_date": None},
            {"start_date": "2026-10-08"},
            {"end_date": "2026-11-01"},
            {"kind": " "},
            {"kind": None},
            {"kind": 1},
            {"time_field": "scheduled_at"},
            {"time_field": []},
            {"exclude_employee_numbers": ["00123"]},
            {"exclude_employee_numbers": None},
            {"unexpected": True},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self._assert_error(self._invoke(**arguments), "bad_request")
        self.assertEqual(self.calls, [])

    def test_missing_arguments_and_unknown_tool_are_rejected(self):
        for arguments in ({}, {"start_date": "2026-10-01"}, [], None):
            context = self._context()
            context["arguments"] = arguments
            self._assert_error(self._request("tool_invoke", context), "bad_request")
        self._assert_error(
            self._request("tool_invoke", {"tool_name": "unknown"}), "bad_request"
        )
        self.assertEqual(self.calls, [])

    def test_empty_page_before_total_is_an_error(self):
        self.empty_offset = 2
        response = self._invoke()
        self._assert_error(response, "unavailable")
        self.assertIn("未能获取完整数据", response["error"]["message"])

    def test_later_page_failure_does_not_return_partial_data(self):
        self.failed_offset = 2
        self._assert_error(self._invoke(), "unavailable")
        self.assertEqual(len(self._list_calls()), 2)

    def test_remote_errors_are_reported(self):
        for failure, code in (
            (400, "external_error"),
            (401, "external_error"),
            (503, "unavailable"),
            ("non_json", "unavailable"),
            ("timeout", "unavailable"),
            ("network", "unavailable"),
        ):
            with self.subTest(failure=failure):
                self.list_error = failure
                self._assert_error(self._invoke(), code)

    def test_non_admin_and_invalid_password_are_rejected(self):
        self.role = "user"
        self._assert_error(self._invoke(), "action_forbidden")
        self.login_error = True
        self._assert_error(self._invoke(), "authorization_required")
        self.assertEqual(self._list_calls(), [])

    def test_authorization_and_configuration_contract_is_preserved(self):
        context = self._context()
        self.assertTrue(self._request("configuration_validate", context)["ok"])
        response = self._request("authorization_identity", context)
        self.assertEqual(
            response["result"]["identity"], context["configuration"]["public"]
        )
        context["submission"] = {
            "type": "credentials", "values": context["credentials"]
        }
        response = self._request("authorization_complete", context)
        self.assertEqual(
            response["result"]["credential"]["values"], context["credentials"]
        )
        self.assertEqual(response["result"]["external_account_id"], "fixture-admin")
        self._assert_error(
            self._request("configuration_validate", {}), "bad_request"
        )
        self._assert_error(self._request("tools_discover", {}), "authorization_required")

    def test_response_size_limit_is_enforced(self):
        item = _conversation(1)
        item["session_title"] = base64.b64encode(
            random.Random(42).randbytes(1100000)
        ).decode()
        self.items = [item]
        response = self._invoke()
        self._assert_error(response, "bad_request")
        self.assertIn("1 MiB", response["error"]["message"])

    def test_discovery_via_subprocess_matches_manifest_policy(self):
        request = {
            "protocol_version": 1,
            "operation": "tools_discover",
            "context": self._context(),
        }
        process = subprocess.run(
            [sys.executable, "-B", str(ENTRYPOINT)],
            input=json.dumps(request), capture_output=True, text=True, check=True,
        )
        self.assertEqual(process.stderr, "")
        response = json.loads(process.stdout)
        tool = response["result"]["tools"][0]
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text())
        rule = manifest["tool_policy"]["rules"][0]
        self.assertEqual(tool["key"], rule["tool"])
        self.assertEqual(tool["effect"], rule["effect"])
        self.assertEqual(tool["retry_policy"], rule["retry"])
        self.assertEqual(tool["confirmation"], "not_required")
        schema = tool["input_schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["start_date", "end_date"])
        for key in ("start_date", "end_date"):
            self.assertTrue(re.fullmatch(schema["properties"][key]["pattern"], "2026-10-01"))


if __name__ == "__main__":
    unittest.main()
