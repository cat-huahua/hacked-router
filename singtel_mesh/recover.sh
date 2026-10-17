#!/bin/bash
# Recover Singtel —— 恢复 mesh 的无线信道和节点名
cd "$(dirname "$0")" || exit 1
python3 recover.py "$@"
echo
echo "──────────────────────────────────"
read -n1 -r -p "按任意键关闭窗口..."
echo
