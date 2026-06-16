FORCE_PORT=0
for arg in "$@"; do
  case "$arg" in
    --port=*)
      FE_PORT="${arg#*=}"
      FORCE_PORT=1
      ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      if [[ "$arg" =~ ^[0-9]+$ ]]; then
        FE_PORT="$arg"
        FORCE_PORT=1
      else
        echo "未知参数: $arg"
        exit 1
      fi
      ;;
  esac
done