from workflow_code_skeleton.app.server import create_app

app = create_app()
for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
    s = str(rule)
    if "framework-to-script" in s:
        print(rule.methods, s, "->", rule.endpoint)
