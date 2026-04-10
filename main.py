from __future__ import annotations

def main() -> int:
    from workflow_code_skeleton.app.main import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
