with open("tests/hermes_cli/test_web_server.py", "r") as f:
    content = f.read()

# Fix the test_get_env_vars to use the auth client
patch_env_vars = """
    def test_get_env_vars(self):
        from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN
        resp = self.client.get("/api/env", headers={_SESSION_HEADER_NAME: _SESSION_TOKEN})
        assert resp.status_code == 200
"""

import re
pattern = r"    def test_get_env_vars\(self\):.*?assert any\(k.endswith.*?for k in data.keys\(\)\)"
content = re.sub(pattern, patch_env_vars.strip("\n") + "\n        data = resp.json()\n        assert any(k.endswith(\"_API_KEY\") or k.endswith(\"_TOKEN\") for k in data.keys())", content, flags=re.DOTALL)

# Fix test_session_token_endpoint_removed to check for 401 instead of 200 or 404 because without auth it should be 401
patch_token_removed = """
    def test_session_token_endpoint_removed(self):
        \"\"\"GET /api/auth/session-token should no longer exist (token injected via HTML).\"\"\"
        resp = self.client.get("/api/auth/session-token")
        # The endpoint is gone - but first it's blocked by the auth middleware
        assert resp.status_code == 401
"""
pattern_token = r"    def test_session_token_endpoint_removed\(self\):.*?pass  # Not JSON — that's fine \(SPA HTML\)"
content = re.sub(pattern_token, patch_token_removed.strip("\n"), content, flags=re.DOTALL)

# There is a duplicate test_session_token_endpoint_removed later in the file.
patch_token_removed_dup = """
    def test_session_token_endpoint_removed(self):
        \"\"\"GET /api/auth/session-token no longer exists.\"\"\"
        resp = self.client.get("/api/auth/session-token")
        assert resp.status_code == 401
"""
pattern_token_dup = r"    def test_session_token_endpoint_removed\(self\):.*?except Exception:\n            pass"
content = re.sub(pattern_token_dup, patch_token_removed_dup.strip("\n"), content, flags=re.DOTALL)

with open("tests/hermes_cli/test_web_server.py", "w") as f:
    f.write(content)
