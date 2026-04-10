from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models.inputs import WorkflowInput
from .orchestrators.runner import run_configured_workflow
from .server import create_app, default_workflow_spec_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行剧本生成工作流")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="执行一次 CLI 工作流")
    run_parser.add_argument("--input", required=True, help="输入 JSON 文件路径")
    run_parser.add_argument(
        "--workflow-spec",
        default=default_workflow_spec_path(),
        help="工作流 JSON 规格文件路径",
    )
    run_parser.add_argument("--output", help="可选：将最终输出写入该文件")
    run_parser.add_argument("--debug-state", help="可选：将完整运行状态保存为 JSON")

    serve_parser = subparsers.add_parser("serve", help="启动网页服务")
    serve_parser.add_argument(
        "--workflow-spec",
        default=default_workflow_spec_path(),
        help="工作流 JSON 规格文件路径",
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="绑定地址")
    serve_parser.add_argument("--port", type=int, default=5000, help="监听端口")
    serve_parser.add_argument(
        "--debug",
        action="store_true",
        help="是否开启 Flask debug 模式",
    )

    return parser


def _run_cli(args) -> int:
    workflow_input = WorkflowInput.from_json_file(args.input)
    state = run_configured_workflow(
        workflow_input,
        workflow_spec_path=args.workflow_spec,
    )

    output_text = state.final_output_text or state.halted_message or ""
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
    else:
        print(output_text)

    if args.debug_state:
        Path(args.debug_state).write_text(
            json.dumps(state.as_debug_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


def _serve_web(args) -> int:
    url = f"http://{args.host}:{args.port}"
    print(f"剧本生成网页服务已启动：{url}", flush=True)
    print("按 Ctrl+C 可以停止服务。", flush=True)
    app = create_app(workflow_spec_path=args.workflow_spec)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # PyCharm 直接运行 main.py 时通常不会传参数；默认启动网页服务。
    if not argv:
        argv = ["serve"]

    # 兼容旧调用：直接传 --input 时默认走 run；其他裸参数默认按网页服务理解。
    elif argv[0] not in {"run", "serve", "-h", "--help"}:
        has_cli_input = any(item == "--input" or item.startswith("--input=") for item in argv)
        argv = ["run" if has_cli_input else "serve", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve_web(args)
    if args.command == "run":
        return _run_cli(args)

    return _serve_web(args)


if __name__ == "__main__":
    raise SystemExit(main())
