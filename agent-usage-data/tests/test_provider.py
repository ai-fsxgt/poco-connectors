import base64
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
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

DATASET = {
    "totals": {"start_date": "2026-10-01", "end_date": "2026-10-07", "runs": 3},
    "previous_totals": {"start_date": "2026-09-24", "end_date": "2026-09-30", "runs": 1},
    "days": [],
    "users": [{"user_id": "fixture-user"}],
    "work_items": [{"item_id": "fixture-item"}],
}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.role = "admin"
        self.login_error = False
        self.dataset_error = None
        transport = httpx.MockTransport(self._handle_request)
        real_client = httpx.Client
        client_patch = patch.object(
            provider.httpx,
            "Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _handle_request(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/api/v1/auth/login":
            if self.login_error:
                return httpx.Response(
                    400, json={"code": 400, "message": "fixture invalid password"}
                )
            data = {"access_token": "fixture-token"}
        elif path == "/api/v1/auth/me":
            data = {
                "id": "fixture-admin",
                "username": "test-admin",
                "full_name": "测试管理员",
                "role": self.role,
            }
        else:
            self.assertEqual(path, "/api/v1/admin/usage-report/dataset")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture-token")
            if self.dataset_error == "timeout":
                raise httpx.ReadTimeout("fixture timeout")
            if self.dataset_error == "network":
                raise httpx.ConnectError("fixture connection failure")
            if self.dataset_error == "non_json":
                return httpx.Response(502, text="fixture bad gateway")
            if isinstance(self.dataset_error, int):
                return httpx.Response(
                    self.dataset_error,
                    json={"code": self.dataset_error, "message": "fixture error"},
                )
            data = DATASET
        return httpx.Response(200, json={"code": 0, "data": data})

    def _request(self, operation, context):
        request = {"protocol_version": 1, "operation": operation, "context": context}
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

    def _dataset_calls(self):
        return [c for c in self.calls if c.url.path.endswith("/usage-report/dataset")]

    def _assert_error(self, response, code):
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code)
        self.assertFalse(response["error"]["retryable"])

    def test_dates_only_sends_no_filters(self):
        response = self._invoke()
        self.assertTrue(response["ok"], response)
        overview, resource = response["result"]["content"]
        dataset = json.loads(gzip.decompress(base64.b64decode(resource["data"])))
        self.assertEqual(dataset["filters"], {})
        self.assertEqual(json.loads(overview["text"])["filters"], {})
        self.assertEqual(
            dict(self._dataset_calls()[0].url.params),
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-07",
                "timezone": "Asia/Shanghai",
            },
        )

    def test_filters_are_forwarded_and_recorded(self):
        response = self._invoke(kind="scheduled", status="failed", source="im", q=" 周报 ")
        self.assertTrue(response["ok"], response)
        expected = {"kind": "scheduled", "status": "failed", "source": "im", "q": "周报"}
        params = dict(self._dataset_calls()[0].url.params)
        self.assertEqual({key: params[key] for key in expected}, expected)
        overview, resource = response["result"]["content"]
        dataset = json.loads(gzip.decompress(base64.b64decode(resource["data"])))
        self.assertEqual(dataset["filters"], expected)
        self.assertEqual(json.loads(overview["text"])["filters"], expected)

    def test_invalid_arguments_do_not_call_upstream(self):
        cases = [
            {"start_date": "2026-02-30"},
            {"kind": "workflow"},
            {"kind": ""},
            {"status": "done"},
            {"source": "web"},
            {"source": None},
            {"q": "   "},
            {"q": 1},
            {"q": "x" * 201},
            {"unexpected": True},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self._assert_error(self._invoke(**arguments), "bad_request")
        for arguments in ({}, {"start_date": "2026-10-01"}, [], None):
            context = self._context()
            context["arguments"] = arguments
            self._assert_error(self._request("tool_invoke", context), "bad_request")
        self.assertEqual(self.calls, [])

    def test_remote_errors_are_reported(self):
        for failure, code in (
            (400, "bad_request"),
            (422, "external_error"),
            (503, "unavailable"),
            ("non_json", "unavailable"),
            ("timeout", "unavailable"),
            ("network", "unavailable"),
        ):
            with self.subTest(failure=failure):
                self.dataset_error = failure
                self._assert_error(self._invoke(), code)

    def test_non_admin_and_invalid_password_are_rejected(self):
        self.role = "user"
        self._assert_error(self._invoke(), "action_forbidden")
        self.login_error = True
        self._assert_error(self._invoke(), "authorization_required")
        self.assertEqual(self._dataset_calls(), [])

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
        tool = json.loads(process.stdout)["result"]["tools"][0]
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text())
        rule = manifest["tool_policy"]["rules"][0]
        self.assertEqual(tool["key"], rule["tool"])
        self.assertEqual(tool["effect"], rule["effect"])
        self.assertEqual(tool["retry_policy"], rule["retry"])
        schema = tool["input_schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["start_date", "end_date"])
        self.assertEqual(
            set(schema["properties"]),
            {"start_date", "end_date", "kind", "status", "source", "q"},
        )


if __name__ == "__main__":
    unittest.main()
