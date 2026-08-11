from __future__ import annotations

def main() -> int:
    from workflow_code_skeleton.app.entrypoint import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
"""启动语句
cd "D:\MINE\grade_3_spring\进步\火山杯新版\idea_to_scripts"
powershell -ExecutionPolicy Bypass -File ".\scripts\run_windows.ps1"
"""