"""统一编排入口：按 config.TARGET_PLATFORM 选择应用执行。"""
import json
import sys

from config import TARGET_PLATFORM, Platform, OUTPUT_JSON
from driver import connect, healthcheck, wake_and_unlock, ensure_atx_running


def run_meituan(d):
    from meituan_client import MeituanClient
    client = MeituanClient(d)
    results = client.collect(
        address="请填写你的配送地址",
        keyword="麦当劳",
        top_n=3,
    )
    client.dump(results)
    return results


def run_taobao_flash(d):
    from taobao_flash_client import TaobaoFlashClient
    client = TaobaoFlashClient(d)
    results = client.collect(keyword="可乐", top_n=3)
    client.dump(results)
    return results


def run_wechat(d):
    from wechat_client import WeChatClient
    client = WeChatClient(d)
    client.launch()
    ok = client.open_chat("文件传输助手")
    client.stop()
    return [{"platform": "wechat", "opened": ok, "sent": False,
             "note": "默认只导航和查看；发送属于 EXTERNAL_EFFECT，需独立授权"}]


HANDLERS = {
    Platform.MEITUAN: run_meituan,
    Platform.TAOBAO_FLASH: run_taobao_flash,
    Platform.WECHAT: run_wechat,
}


def main():
    d = connect()
    print("[+] 设备:", healthcheck(d))
    ensure_atx_running(d) or print("[!] ATX 未运行，请检查 init 是否成功")
    wake_and_unlock(d)

    handler = HANDLERS.get(TARGET_PLATFORM)
    if not handler:
        print(f"[-] 未支持的平台: {TARGET_PLATFORM}")
        sys.exit(1)

    results = handler(d)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[✓] 完成，共 {len(results)} 条，已写入 {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
