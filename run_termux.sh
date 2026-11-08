#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# AALC (AhabAssistantLimbusCompany) — Android Termux 极客一键启动脚本
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 1. 将 scripts/ 注入 PATH，使 scripts/adb 成为全局 adb 桥接层
export PATH="$PROJECT_DIR/scripts:$PATH"

# 2. 检测 Shizuku 环境
RISH_BIN="${HOME}/rish"
if [ ! -f "$RISH_BIN" ]; then
    RISH_BIN="/data/data/com.termux/files/home/rish"
fi

if [ ! -f "$RISH_BIN" ]; then
    echo "❌ 错误: 未在 ~/rish 检测到 Shizuku 可执行程序！"
    echo "💡 解决方式: 请打开 Shizuku App，导出 rish 到 Termux 主目录 (~/rish) 并赋予权限。"
    exit 1
fi

echo "🔍 检查 Shizuku 特权授权..."
if ! bash "$RISH_BIN" -c "id" >/dev/null 2>&1; then
    echo "❌ 错误: Shizuku 未授权或服务未启动！请在 Shizuku 应用中启动服务并授权 Termux。"
    exit 1
fi
echo "✅ Shizuku 授权正常 (uid=2000 shell)"

# 3. 校验并展示系统 ADB 欺骗桥接
echo "🔌 激活本地 Shizuku ADB 欺骗桥接层..."
adb devices
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    exec python3 agent/main.py --help
fi

TASK="${1:-full_script}"
if [[ "$TASK" == --task* ]]; then
    TASK="$2"
    shift 2
elif [ $# -gt 0 ]; then
    shift 1
fi

echo "🚀 开始在 1920x1080 独立后台虚拟副屏启动 AALC 任务: [$TASK]..."
echo "💡 提示: 游戏在后台副屏独立运行，不影响前台使用。按 Ctrl+C 可停止脚本并自动清理副屏守护。"

exec python3 agent/main.py --cli --task "$TASK" "$@"
