#!/bin/sh
# 将不同 Nginx 基础镜像的 PID 文件统一放到非 root 用户可写目录。
set -eu

config_path="${1:-/etc/nginx/nginx.conf}"
temporary_path="${config_path}.tmp.$$"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

# 不使用 sed -i，兼容 Alpine BusyBox sed 与 macOS/BSD sed 的不同参数语义。
sed -E 's#^[[:space:]]*pid[[:space:]]+[^;]+;#pid /tmp/nginx.pid;#' \
  "$config_path" > "$temporary_path"
cat "$temporary_path" > "$config_path"

if ! grep -Eq '^[[:space:]]*pid[[:space:]]+/tmp/nginx\.pid;' "$config_path"; then
  echo "无法将 Nginx PID 路径改写为 /tmp/nginx.pid: $config_path" >&2
  exit 1
fi
