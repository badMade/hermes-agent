import re

with open("tests/hermes_cli/test_web_server.py", "r") as f:
    content = f.read()

# Fix the duplicate dummy routes
content = content.replace(
    '''        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        @app.get("/api/plugins/test-plugin/dummy-route")
        def dummy_route():
            return {"status": "ok"}
''',
    '''        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
'''
)

# Put it back correctly
content = content.replace(
    '        self.client = TestClient(app)\n        self.auth_client = TestClient(app)',
    '''        # Ensure the test route is only added once
        if not any(route.path == "/api/plugins/test-plugin/dummy-route" for route in getattr(app, "routes", [])):
            @app.get("/api/plugins/test-plugin/dummy-route")
            def dummy_route():
                return {"status": "ok"}

        self.client = TestClient(app)
        self.auth_client = TestClient(app)'''
)

with open("tests/hermes_cli/test_web_server.py", "w") as f:
    f.write(content)
