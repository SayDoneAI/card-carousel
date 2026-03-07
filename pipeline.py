"""
图文卡片口播视频 — 生成管线
用法:
  python pipeline.py config.yaml              # 全量执行
  python pipeline.py config.yaml --step tts   # 只跑 TTS
  python pipeline.py config.yaml --step illustrations  # 只生成插画
  python pipeline.py config.yaml --step render # 只渲染 Manim
  python pipeline.py config.yaml --step voice  # 合并音频到视频
  python pipeline.py config.yaml --step concat # 拼接最终视频

流程: tts → illustrations → render → voice → concat
"""

import argparse
import sys

from core.config import load_config
from core.orchestrator import run_pipeline, STEP_ORDER


def main():
    parser = argparse.ArgumentParser(
        description="图文卡片口播视频生成管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python pipeline.py config.yaml\n"
               "  python pipeline.py config.yaml --step tts\n"
               "  python pipeline.py config.yaml --step illustrations\n"
               "  python pipeline.py config.yaml --step render\n",
    )
    parser.add_argument("config", help="YAML 配置文件路径")
    parser.add_argument("--step", choices=STEP_ORDER, default=None,
                        help="只执行指定步骤")
    parser.add_argument("--speed", type=float, default=None,
                        help="播放倍率 (默认 1.0)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.speed is not None:
        if args.speed < 0.5 or args.speed > 100:
            print(f"错误: --speed 必须在 0.5-100.0 之间，当前值: {args.speed}")
            sys.exit(1)
        cfg["output"]["speed"] = args.speed
    run_pipeline(cfg, step=args.step)


if __name__ == "__main__":
    main()
