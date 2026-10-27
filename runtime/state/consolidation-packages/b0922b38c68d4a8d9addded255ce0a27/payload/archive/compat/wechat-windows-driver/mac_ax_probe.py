#!/usr/bin/env python3
# 用 ctypes 直连 HIServices/AXUIElement 枚举微信 AX 树（修复 AXUIElementRef 悬空问题）
import ctypes, subprocess, sys

HS = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework/HIServices')
CF = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

CFStringRef = ctypes.c_void_p
CFArrayRef = ctypes.c_void_p
CFTypeRef = ctypes.c_void_p
AXUIElementRef = ctypes.c_void_p
kCFStringEncodingUTF8 = 0x08000100

CF.CFStringCreateWithCString.restype = CFStringRef
CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
CF.CFStringGetLength.restype = ctypes.c_long
CF.CFStringGetLength.argtypes = [CFStringRef]
CF.CFStringGetCString.restype = ctypes.c_bool
CF.CFStringGetCString.argtypes = [CFStringRef, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
CF.CFRelease.restype = None
CF.CFRelease.argtypes = [CFTypeRef]
CF.CFRetain.restype = CFTypeRef
CF.CFRetain.argtypes = [CFTypeRef]
CF.CFGetTypeID.restype = ctypes.c_ulong
CF.CFGetTypeID.argtypes = [CFTypeRef]
CF.CFArrayGetCount.restype = ctypes.c_long
CF.CFArrayGetCount.argtypes = [CFArrayRef]
CF.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
CF.CFArrayGetValueAtIndex.argtypes = [CFArrayRef, ctypes.c_long]
CF.CFStringGetTypeID.restype = ctypes.c_ulong; CF.CFStringGetTypeID.argtypes = []
CF.CFArrayGetTypeID.restype = ctypes.c_ulong; CF.CFArrayGetTypeID.argtypes = []
_string_tid = CF.CFStringGetTypeID()
_array_tid = CF.CFArrayGetTypeID()

HS.AXUIElementCreateApplication.restype = AXUIElementRef
HS.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
HS.AXUIElementCopyAttributeValue.restype = ctypes.c_int
HS.AXUIElementCopyAttributeValue.argtypes = [AXUIElementRef, CFStringRef, ctypes.POINTER(ctypes.c_void_p)]

def cfstr(s):
    return CF.CFStringCreateWithCString(None, s.encode('utf-8'), kCFStringEncodingUTF8)

def cfstr_to_py(cf):
    if not cf: return ""
    length = CF.CFStringGetLength(cf)
    buf = ctypes.create_string_buffer(length * 4 + 16)
    if CF.CFStringGetCString(cf, buf, len(buf), kCFStringEncodingUTF8):
        return buf.value.decode('utf-8', 'replace')
    return ""

def cf_to_py(cf):
    # cf 可能是 int(来自 out.value) 或 c_void_p(来自 CFArrayGetValueAtIndex)
    if not cf:
        return None
    if isinstance(cf, int):
        cf = ctypes.c_void_p(cf)
    tid = CF.CFGetTypeID(cf)
    if tid == _string_tid:
        return cfstr_to_py(cf)
    if tid == _array_tid:
        n = CF.CFArrayGetCount(cf)
        out = []
        for i in range(n):
            el = CF.CFArrayGetValueAtIndex(cf, i)
            if el:
                CF.CFRetain(el)  # 独立持有，避免父数组释放后悬空
            out.append(cf_to_py(el))
        return out
    # AXUIElementRef / AXValue 等：保留原始指针供继续遍历
    return cf

def get_attr(elem, name):
    attr = cfstr(name)
    out = ctypes.c_void_p()
    err = HS.AXUIElementCopyAttributeValue(elem, attr, ctypes.byref(out))
    CF.CFRelease(attr)
    if err != 0:
        return err, None
    return err, cf_to_py(out.value)

# ---- 主逻辑 ----
try:
    pids = subprocess.check_output(["pgrep", "-f", "WeChat.app/Contents/MacOS/WeChat"]).decode().split()
except Exception as e:
    print("pgrep 失败:", e); sys.exit(1)
pid = int(pids[0])
print("微信主进程 pid:", pid)
app = HS.AXUIElementCreateApplication(pid)

err, wins = get_attr(app, "AXWindows")
if err != 0:
    axerr_map = {-25200:"kAXErrorFailure",-25201:"kAXErrorIllegalArgument",-25202:"kAXErrorInvalidUIElement",
                 -25203:"kAXErrorInvalidUIElementObserver",-25204:"kAXErrorCannotComplete",
                 -25205:"kAXErrorAttributeUnsupported",-25211:"kAXErrorAPIDisabled",-25212:"kAXErrorNoValue"}
    print(f"获取 AXWindows 失败: AXError={err} ({axerr_map.get(err,'未知')})")
    if err in (-25204, -25211):
        print("=> 系统拒绝了 Accessibility 访问（TCC 辅助功能权限未授予当前进程）。")
        print("   需到 系统设置 > 隐私与安全性 > 辅助功能 把 WorkBuddy 加入并勾选，再重试。")
    sys.exit(2)

wins = wins or []
print("窗口数量:", len(wins), "\n")

role_count = {}
targets = {"textfields": [], "send_buttons": [], "lists": []}
printed = [0]; MAX_PRINT = 2000

def walk(elem, depth):
    if depth > 20 or printed[0] > MAX_PRINT: return
    err, role = get_attr(elem, "AXRole")
    if err != 0 or role is None: return
    role_count[role] = role_count.get(role, 0) + 1
    err, title = get_attr(elem, "AXTitle"); t = title or ""
    err, desc = get_attr(elem, "AXDescription"); d = desc or ""
    err, rid = get_attr(elem, "AXIdentifier"); rid = rid or ""
    if printed[0] < MAX_PRINT:
        line = "  " * depth + role
        if t: line += f"  title={t!r}"
        if d and d != t: line += f"  desc={d!r}"
        if rid: line += f"  id={rid!r}"
        print(line); printed[0] += 1
    if role in ("AXTextField", "AXTextArea"):
        targets["textfields"].append((depth, t, d, rid))
    if role == "AXButton" and ("发送" in (t + d)):
        targets["send_buttons"].append((depth, t, d, rid))
    if role in ("AXList", "AXOutline", "AXScrollArea", "AXTable", "AXOutlineRow", "AXRow", "AXCell"):
        targets["lists"].append((depth, role, t, rid))
    err, children = get_attr(elem, "AXChildren")
    if err == 0 and isinstance(children, list):
        for ch in children[:80]:
            if ch: walk(ch, depth + 1)

for w in wins:
    err, wt = get_attr(w, "AXTitle")
    print(f"#### 窗口: {wt or '(无标题)'} ####")
    walk(w, 0)

print("\n================ 统计 ================")
print("角色计数:")
for k, v in sorted(role_count.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")
print("\n【输入框候选 AXTextField/AXTextArea】:", len(targets["textfields"]))
for x in targets["textfields"][:15]: print("   ", x)
print("\n【发送按钮候选 AXButton 含'发送'】:", len(targets["send_buttons"]))
for x in targets["send_buttons"][:15]: print("   ", x)
print("\n【会话列表候选 AXList/AXOutline/AXScrollArea/AXTable】:", len(targets["lists"]))
for x in targets["lists"][:15]: print("   ", x)

print("\n================ 结论 ================")
# 关键判据：业务控件（输入框/发送按钮/会话列表）是否真的被 AX 树暴露
found_real = (len(targets["textfields"]) > 0 or len(targets["send_buttons"]) > 0 or len(targets["lists"]) > 0)
if not found_real:
    print("✗ 能拿到『窗口壳』(含少量标题栏按钮/分组)，但聊天界面的『输入框 / 发送按钮 / 会话列表』均未被 AX 树暴露。")
    print("  这说明 AX 通道本身是通的（已拿到窗口与标题栏按钮，非权限问题），")
    print("  而是 4.1.4 的自绘框架(WXUI)主动隐藏了内部业务控件。")
    print("  => 无法用 AXUIElement 定位输入框/发送按钮/会话列表；Mac 端不适合控件级 UI 自动化。")
else:
    print("✓ 找到了输入框/发送按钮/会话列表，可用 Accessibility API 定位。")
