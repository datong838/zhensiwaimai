"""Native AX composer focusing without materializing virtual message children."""
import time
import subprocess
import re
from contract import Rejected

AX_MESSAGE_TIMEOUT_SECONDS=3.0

def set_ax_messaging_timeout(ax,element):
    setter=getattr(ax,'AXUIElementSetMessagingTimeout',None)
    if not callable(setter):raise Rejected('wechat-ax-timeout-api-unavailable')
    result=setter(element,AX_MESSAGE_TIMEOUT_SECONDS)
    if result!=getattr(ax,'kAXErrorSuccess',0):
        raise Rejected('wechat-ax-timeout-configuration-failed')

def unique_pid(output):
    pids=output.split()
    if len(pids)!=1 or not pids[0].isdigit():raise Rejected('wechat-process-count-not-one')
    return int(pids[0])

def running_app():
    import AppKit
    result=subprocess.run(['pgrep','-x','WeChat'],capture_output=True,text=True,timeout=3)
    pid=unique_pid(result.stdout)
    app=AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None or app.bundleIdentifier()!='com.tencent.xinWeChat' or app.isTerminated():raise Rejected('wechat-process-identity-mismatch')
    return app

def choose_composer(candidates):
    found=[x for x in candidates if x[1][0]>400 and x[1][1]>40]
    if len(found)!=1:raise Rejected('wechat-chat-input-count-not-one')
    return found[0]

def choose_main_window(windows, ax_main):
    """Select a unique native main window; never infer from order or geometry."""
    if len(windows)==1:return windows[0]
    marked=[window for window in windows if ax_main(window) is True]
    if len(marked)!=1 or any(ax_main(window) is not False
                             for window in windows if window is not marked[0]):
        raise Rejected('wechat-main-window-count-not-one')
    return marked[0]

def is_search_results_dialog(window,size,attr):
    """Recognize a bounded local-search dialog by AX structure, never section labels."""
    if attr(window,'AXTitle') not in ('',None) or attr(window,'AXSubrole')!='AXDialog':return False
    if not (250<=size.width<=500 and 250<=size.height<=650):return False
    children=list(attr(window,'AXChildren') or [])
    lists=[child for child in children if attr(child,'AXRole')=='AXList']
    if len(lists)!=1:return False
    text_count=0;stack=list(attr(lists[0],'AXChildren') or []);seen=0
    while stack and seen<200:
        element=stack.pop();seen+=1
        if attr(element,'AXRole')=='AXStaticText':
            value=attr(element,'AXValue') or attr(element,'AXTitle')
            if str(value or '').strip():text_count+=1
        stack.extend(attr(element,'AXChildren') or [])
    # A local result list has multiple text rows.  Exact target matching plus
    # post-click native-title verification supplies the identity proof.
    return seen<200 and text_count>=2

def is_chat_history_search_window(window,size,attr):
    """Allow only WeChat's bounded chat-history search window beside the main chat."""
    if attr(window,'AXTitle')!='搜索聊天记录' or attr(window,'AXRole')!='AXWindow':return False
    if not (600<=size.width<=850 and 500<=size.height<=750):return False
    stack=list(attr(window,'AXChildren') or []);seen=0;lists=0;inputs=0;enter=0
    while stack and seen<200:
        element=stack.pop();seen+=1;role=attr(element,'AXRole');title=str(attr(element,'AXTitle') or '')
        if role=='AXList':lists+=1
        elif role in ('AXTextField','AXTextArea'):inputs+=1
        elif role=='AXButton' and title=='进入聊天':enter+=1
        stack.extend(attr(element,'AXChildren') or [])
    return seen<200 and lists==2 and inputs==1 and enter==1

def is_excel_preview_window(window,size,attr):
    """Allow one inert Excel attachment preview beside the unique chat window."""
    title=attr(window,'AXTitle')
    if not isinstance(title,str) or not re.fullmatch(r'[^/\\\r\n]+\.xlsx',title,re.IGNORECASE):return False
    if attr(window,'AXRole')!='AXWindow' or attr(window,'AXSubrole')!='AXStandardWindow':return False
    if not (800<=size.width<=1600 and 500<=size.height<=1000):return False
    children=list(attr(window,'AXChildren') or [])
    return len(children)==3 and {
        (attr(child,'AXRole'),attr(child,'AXSubrole')) for child in children
    }=={
        ('AXButton','AXCloseButton'),
        ('AXButton','AXFullScreenButton'),
        ('AXButton','AXMinimizeButton'),
    }

def is_detached_chat_window(window,size,attr):
    """Recognize, but never operate, one structurally complete detached chat."""
    title=attr(window,'AXTitle')
    if not isinstance(title,str) or not title.strip() or title=='微信':return False
    if attr(window,'AXRole')!='AXWindow' or attr(window,'AXSubrole')!='AXStandardWindow':return False
    if not (500<=size.width<=800 and 500<=size.height<=800):return False
    children=list(attr(window,'AXChildren') or [])
    if len(children)!=10:return False
    for label in ('聊天记录','从手机导入聊天记录','语音通话','聊天信息','置顶'):
        if sum(attr(child,'AXRole')=='AXButton' and attr(child,'AXTitle')==label
               for child in children)!=1:return False
    for subrole in ('AXCloseButton','AXFullScreenButton','AXMinimizeButton'):
        if sum(attr(child,'AXRole')=='AXButton' and attr(child,'AXSubrole')==subrole
               for child in children)!=1:return False
    splits=[child for child in children if attr(child,'AXRole')=='AXSplitGroup']
    if len(splits)!=1:return False
    parts=list(attr(splits[0],'AXChildren') or [])
    return (sum(attr(part,'AXRole')=='AXList' and attr(part,'AXTitle')=='消息' for part in parts)==1
            and sum(attr(part,'AXRole')=='AXTextArea' and attr(part,'AXTitle')=='输入' for part in parts)==1
            and sum(attr(part,'AXRole')=='AXButton' and attr(part,'AXTitle')=='发送' for part in parts)==1)

def _exact_group_text(value,expected):
    value=re.sub(r'\s+','',str(value or '').strip())
    expected=re.sub(r'\s+','',expected.strip())
    if value==expected:return True
    # Core-text lookup may expose a visually truncated AX row; the caller
    # still requires full-title and member-count proof after opening.
    return '💰' not in expected and value.startswith(expected)

def _search_text_items(root,attr,pair):
    """Return native text rows and whether each belongs to a clickable AX row.

    WeChat changes result-section captions (for example, frequently used versus
    group chats).  Captions are presentation only, so selection uses the AX row
    ancestry instead.  If AX does not expose ancestry, callers may only accept
    one exact text row; duplicate text is intentionally ambiguous.
    """
    actionable_roles={'AXRow','AXCell','AXButton','AXLink'}
    items=[];stack=[(root,False)];seen=0
    while stack and seen<200:
        element,in_clickable=stack.pop();seen+=1
        role=attr(element,'AXRole')
        clickable=in_clickable or role in actionable_roles
        if role=='AXStaticText':
            value=attr(element,'AXValue') or attr(element,'AXTitle')
            position=pair(element,'AXPosition','point')
            dimensions=pair(element,'AXSize','size')
            if value and position and dimensions:
                items.append({'text':str(value).strip(),'x':position[0],'y':position[1],
                              'width':dimensions[0],'height':dimensions[1],
                              'clickable':clickable})
        stack.extend((child,clickable) for child in (attr(element,'AXChildren') or []))
    return items

def search_dialog_exact_row(window,size,attr,pair,group_name):
    """Return one native clickable local result; captions never affect selection."""
    if not is_search_results_dialog(window,size,attr):return None
    listing=[child for child in list(attr(window,'AXChildren') or [])
             if attr(child,'AXRole')=='AXList'][0]
    items=_search_text_items(listing,attr,pair)
    rows=[item for item in items if _exact_group_text(item['text'],group_name)
          and item['width']>=40 and item['height']>=10]
    unique={(round(item['x']),round(item['y']),round(item['width']),round(item['height'])):item
            for item in rows}
    clickable=[item for item in unique.values() if item['clickable']]
    if len(clickable)==1:return clickable[0]
    # An unclickable text node can be a chat-history snippet or a network hit.
    # Never guess its section from visible wording; fail closed instead.
    return None

def exact_search_result(group_name):
    """Read one structurally bounded native local-search result, if present."""
    import ApplicationServices as AX
    running=running_app();app=AX.AXUIElementCreateApplication(running.processIdentifier())
    def attr(e,k):
        error,v=AX.AXUIElementCopyAttributeValue(e,k,None)
        return v if error==0 else None
    def pair(e,k,kind):
        raw=attr(e,k)
        if raw is None:return None
        value_kind=AX.kAXValueCGPointType if kind=='point' else AX.kAXValueCGSizeType
        ok,v=AX.AXValueGetValue(raw,value_kind,None)
        if not ok:return None
        return (v.x,v.y) if kind=='point' else (v.width,v.height)
    rows=[];dialogs=0
    for window in list(attr(app,'AXWindows') or []):
        size=pair(window,'AXSize','size')
        if not size:continue
        dimensions=type('Size',(),{'width':size[0],'height':size[1]})()
        if is_search_results_dialog(window,dimensions,attr):dialogs+=1
        row=search_dialog_exact_row(window,dimensions,attr,pair,group_name)
        if row:rows.append(row)
    if len(rows)>1:raise Rejected('wechat-search-native-result-not-unique')
    return rows[0] if len(rows)==1 and dialogs==1 else None

def open_exact_search_result(group_name,click):
    """Click one structurally bounded native local-search result, if present."""
    row=exact_search_result(group_name)
    if row is None:return False
    click(row['x']+row['width']/2,row['y']+row['height']/2)
    return True

def focus_chat_input():
    import AppKit, ApplicationServices as AX
    running=running_app()
    app=AX.AXUIElementCreateApplication(running.processIdentifier())
    def attr(e,k):
        set_ax_messaging_timeout(AX,e)
        error,v=AX.AXUIElementCopyAttributeValue(e,k,None)
        return v if error==0 else None
    def pair(e,k,kind):
        raw=attr(e,k)
        if raw is None:return None
        ok,v=AX.AXValueGetValue(raw,kind,None)
        if not ok:return None
        return (v.width,v.height) if kind==AX.kAXValueCGSizeType else (v.x,v.y)
    windows=[]
    for candidate in attr(app,'AXWindows') or []:
        size=pair(candidate,'AXSize',AX.kAXValueCGSizeType)
        if attr(candidate,'AXTitle')=='微信' and size and size[0]>=700 and size[1]>=500:
            windows.append(candidate)
    main=choose_main_window(windows,lambda window:attr(window,'AXMain'))
    stack=[main];candidates=[]
    while stack:
        e=stack.pop();role=attr(e,'AXRole')
        if role=='AXList' and attr(e,'AXTitle')=='消息':continue
        if role=='AXTextArea':
            size=pair(e,'AXSize',AX.kAXValueCGSizeType)
            if size:candidates.append((e,size))
        stack.extend(attr(e,'AXChildren') or [])
    target,size=choose_composer(candidates)
    AX.AXUIElementSetAttributeValue(target,'AXFocused',True)
    for _ in range(5):
        focused=attr(app,'AXFocusedUIElement')
        if focused is not None and attr(focused,'AXRole')=='AXTextArea' and pair(focused,'AXSize',AX.kAXValueCGSizeType)==size and pair(focused,'AXPosition',AX.kAXValueCGPointType)==pair(target,'AXPosition',AX.kAXValueCGPointType):return
        time.sleep(.1)
    raise Rejected('wechat-composer-native-focus-failed')

def activate_wechat():
    import AppKit,ApplicationServices as AX
    running=running_app()
    app=AX.AXUIElementCreateApplication(running.processIdentifier())
    def attr(e,k):
        set_ax_messaging_timeout(AX,e)
        error,v=AX.AXUIElementCopyAttributeValue(e,k,None)
        return v if error==0 else None
    # NSArray may manufacture fresh PyObjC proxies on each iteration.
    windows=list(attr(app,'AXWindows') or [])
    sizes={}
    for window in windows:
        raw=attr(window,'AXSize')
        if raw is None:raise Rejected('wechat-window-size-unavailable')
        ok,size=AX.AXValueGetValue(raw,AX.kAXValueCGSizeType,None)
        if not ok:raise Rejected('wechat-window-size-unavailable')
        sizes[id(window)]=size
    mains=[w for w in windows if attr(w,'AXTitle')=='微信'
           and sizes[id(w)].width>=700 and sizes[id(w)].height>=500]
    if not mains:
        named=[w for w in windows if attr(w,'AXTitle')=='微信']
        if len(named)==1:
            # Keep the fast path read-only for a normal window.  A single
            # undersized named window is deterministic, however, and must be
            # normalized by the shared locator before AX main-window gating.
            from wechat_desktop import ensure_window_size
            ensure_window_size()
            return activate_wechat()
    main=choose_main_window(mains,lambda window:attr(window,'AXMain'))
    preview_count=0;detached_count=0
    for w in windows:
        size=sizes[id(w)]
        if w==main:
            if size.width<700 or size.height<500:raise Rejected('wechat-main-window-too-small')
        elif w in mains and attr(w,'AXMain') is False:
            # A unique AXMain candidate is raised below; inactive WeChat main
            # windows are never targets and cannot steal the subsequent AX focus.
            continue
        elif is_excel_preview_window(w,size,attr):
            preview_count+=1
            if preview_count>1:raise Rejected('wechat-unexpected-secondary-window')
        elif is_detached_chat_window(w,size,attr):
            detached_count+=1
            if detached_count>1:raise Rejected('wechat-unexpected-secondary-window')
        elif (attr(w,'AXTitle') not in ('微信 (窗口)','图片和视频')
              and not is_search_results_dialog(w,size,attr)
              and not is_chat_history_search_window(w,size,attr)
              and (size.width>500 or size.height>400)):
            raise Rejected('wechat-unexpected-secondary-window')
    AX.AXUIElementSetAttributeValue(main,'AXMinimized',False)
    running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    AX.AXUIElementPerformAction(main,'AXRaise')
    time.sleep(.3)
