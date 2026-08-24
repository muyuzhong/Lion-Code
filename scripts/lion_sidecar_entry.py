"""PyInstaller 的稳定入口；产品构造仍由顶层 sidecar 接口拥有。"""

from lion_code.sidecar import main

if __name__ == "__main__":
    raise SystemExit(main())
