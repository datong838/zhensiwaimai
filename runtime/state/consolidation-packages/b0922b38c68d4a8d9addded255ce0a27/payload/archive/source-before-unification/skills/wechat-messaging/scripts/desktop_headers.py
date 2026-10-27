"""Narrow OCR decoration fallback, always corroborated by exact raw AX title."""
import re
import time
from pathlib import Path
from types import SimpleNamespace

class DesktopHeaders:
    def __init__(self, base):
        self.base=base
        self._ocr_find_exact_group_rows=base.find_exact_group_rows
    def __getattr__(self, name):return getattr(self.base,name)
    def _ax_visible_after_click(self,group):
        for attempt in range(3):
            verified=self.base.open_group_exact_ax_visible(group)
            if verified is not None and verified.ok:return verified
            if attempt<2:time.sleep(.3)
        return None
    def _open_unique_search_result(self, group, search_name, artifacts):
        """Click the sole local search result; displayed group text is not an identity gate."""
        if not search_name:
            return None
        artifacts=Path(artifacts); shot=artifacts/'open_group_core_prefix.png'
        self.base.screenshot_search_region(shot)
        hits=self.base.ocr(shot)
        if not isinstance(hits, list):
            return None
        compact=lambda text: re.sub(r'\s+', '', str(text or '')).strip()
        headings=[hit for hit in hits if compact(hit.text) in ('最常使用','群聊')]
        boundaries=[hit for hit in hits if compact(hit.text) in ('聊天记录','搜索网络结果','创建新的群聊')]
        if len(headings) != 1:
            return None
        top=headings[0].cy
        lower=min((hit.cy for hit in boundaries if hit.cy>top),default=None)
        if lower is None:
            return None
        labels={'最常使用','群聊','聊天记录','搜索网络结果','创建新的群聊'}
        rows=[hit for hit in hits if hit.cx<700 and top<hit.cy<lower and compact(hit.text) not in labels]
        if len(rows) != 1:
            return None
        scale=self.base.screen_scale()
        self.base.click_local(rows[0].cx,rows[0].cy,activate=False,scale=scale)
        return SimpleNamespace(ok=True,action='open-group',group=group,header=None,
                               note='unique-search-result-clicked',artifacts=[str(shot)])

    def _open_unique_exact_local_result(self, group, artifacts):
        """Open one exact local result, then prove identity from the raw AX header."""
        artifacts=Path(artifacts); shot=artifacts/'open_group_exact_local.png'
        self.base.screenshot_search_region(shot)
        hits=self.base.ocr(shot)
        if not isinstance(hits, list):
            return None
        visual=lambda text: re.sub(r'\s+', '', str(text or '').replace('＋', '+')).strip()
        headings=[hit for hit in hits if visual(hit.text)=='最常使用' or visual(hit.text)=='群聊']
        if len(headings)!=1:
            return None
        top=headings[0].cy
        lower=min((hit.cy for hit in hits if hit.cy>top and any(marker in visual(hit.text)
                  for marker in ('聊天记录','搜索网络结果','创建新的群聊'))),default=None)
        if lower is None:
            return None
        def exact_local(hit):
            text=visual(hit.text)
            tail=text[len(group):] if text.startswith(group) else None
            return tail is not None and re.fullmatch(r'[〇○>》›?？Qq①-⑩]*',tail) is not None
        rows=[hit for hit in hits if hit.cx<700 and top<hit.cy<lower and exact_local(hit)]
        if len(rows)!=1:
            return None
        scale=self.base.screen_scale()
        self.base.click_local(rows[0].cx,rows[0].cy,activate=False,scale=scale)
        verified=self._ax_visible_after_click(group)
        if verified is None or not verified.ok:
            return None
        verified.note='ocr-exact-local-result-raw-ax-header'
        verified.artifacts=[str(shot)]
        return verified

    def _open_ocr_plus_variant(self, group, artifacts):
        """Click one normalized visual plus-row, then require raw AX identity."""
        if "+" not in group:
            return None
        artifacts=Path(artifacts); shot=artifacts/'open_group_plus_variant.png'
        self.base.screenshot_search_region(shot)
        hits=self.base.ocr(shot)
        if not isinstance(hits, list):
            return None
        visual=lambda text: re.sub(r'\s+', '', str(text).replace("＋", "+")).strip()
        # The desktop OCR adds non-semantic glyphs (for example "〇>") to a
        # frequent-result row. It may also render a lower network result. Use
        # only a target-prefix with a strictly decorative tail, and then the
        # unique top-most row. Identity remains fail-closed: the opened chat
        # must expose the raw AX group header before any send is possible.
        def direct_result(hit):
            text=visual(hit.text)
            tail=text[len(group):] if text.startswith(group) else None
            return tail is not None and re.fullmatch(r'[〇○>》›?？]*',tail) is not None
        rows=[hit for hit in hits if hit.cx < 700 and hit.cy >= 120 and direct_result(hit)]
        rows.sort(key=lambda hit: hit.cy)
        if not rows or (len(rows)>1 and rows[1].cy-rows[0].cy < max(20,rows[0].h*1.5)):
            return None
        scale=self.base.screen_scale()
        self.base.click_local(rows[0].cx,rows[0].cy,activate=False,scale=scale)
        verified=self._ax_visible_after_click(group)
        if verified is None or not verified.ok:
            return None
        verified.note='ocr-plus-variant-raw-ax-header'
        verified.artifacts=[str(shot)]
        return verified

    def activate_wechat(self):
        from desktop_input import activate_wechat
        return activate_wechat()
    def open_group(self,group,artifacts,*,exact=False,search_name=None):
        # A visible local exact row is stronger and faster evidence than polling
        # AX rows that this desktop client exposes as non-clickable static text.
        if exact:
            selected=self._open_unique_exact_local_result(group,artifacts)
            if selected is not None:
                return selected
        receipt=self.base.open_group(group,artifacts,exact=exact,search_name=search_name)
        if exact and not receipt.ok and receipt.note in ('exact-group-result-count:0','exact-group-header-count:0'):
            selected=self._open_unique_exact_local_result(group,artifacts)
            if selected is not None:
                return selected
            selected=self._open_unique_search_result(group,search_name,artifacts)
            if selected is not None:
                return selected
            visual=self._open_ocr_plus_variant(group,artifacts)
            if visual is not None:
                return visual
            from desktop_input import open_exact_search_result
            scale=self.base.screen_scale()
            clicked=open_exact_search_result(
                search_name or group,lambda x,y:self.base.click_local(x,y,activate=False,scale=scale))
            if clicked:
                verified=self._ax_visible_after_click(group)
                if verified is not None and verified.ok:
                    verified.note='ax-native-search-result'
                    verified.artifacts=list(getattr(receipt,'artifacts',[]) or [])
                    return verified
        if exact and not receipt.ok and receipt.note=='exact-group-header-count:0':
            verified=self._ax_visible_after_click(group)
            if verified is not None and verified.ok:
                verified.note='exact-group-section-text-row'
                verified.artifacts=list(getattr(receipt,'artifacts',[]) or [])
                return verified
        header=str(getattr(receipt,'header',None) or '').strip()
        exact_without_count=(exact and receipt.ok and self.base.exact_group_text(header,group)
                             and not re.fullmatch(re.escape(group)+r'\s*[（(]\d+[）)]',header)
                             and receipt.note!='exact-group-section-text-row')
        if exact_without_count:
            artifacts=Path(artifacts);shot=artifacts/'open_group_force_search.png'
            self.base.ensure_window_size();self.base.screenshot_main_region(shot)
            hits=self.base.ocr(shot);headers=self.base.find_exact_headers(hits,group)
            filtered=[hit for hit in hits if hit not in headers]
            searched=self.base.open_group_exact(group,artifacts,shot,filtered,self.base.screen_scale(),search_name)
            if not searched.ok and searched.note=='exact-group-header-count:0':
                verified=self._ax_visible_after_click(group)
                if verified is not None and verified.ok:
                    verified.note='exact-group-section-text-row'
                    verified.artifacts=list(getattr(searched,'artifacts',[]) or [])
                    return verified
            return searched
        return receipt
    def find_exact_group_rows(self,hits,group):
        from desktop_input import exact_search_result
        row=exact_search_result(group)
        if row is None:return self._ocr_find_exact_group_rows(hits,group)
        x,y,_,_=self.base.window_bounds();scale=self.base.screen_scale()
        return [self.base.OcrHit(
            cx=(row['x']+row['width']/2-x)*scale,
            cy=(row['y']+row['height']/2-y)*scale,
            w=row['width']*scale,h=row['height']*scale,
            confidence=1.0,text=row['text'])]
    def ax_confirms_raw_group_header(self,group):
        for attempt in range(3):
            try:return self.base.ax_confirms_raw_group_header(group)
            except RuntimeError as error:
                if 'wechat-process-count-not-one' not in str(error) or attempt==2:raise
                time.sleep(.2)
    def find_exact_headers(self,hits,group):
        exact=self.base.find_exact_headers(hits,group)
        if exact:return exact
        right=max((h.cx+h.w/2 for h in hits),default=0)
        pattern=re.escape(group)+r'\s*[（(]\d+[）)]\s*[〇C]'
        candidates=[h for h in hits if h.cy<120 and h.cx>max(300,right*.27)
                    and re.fullmatch(pattern,h.text.strip())]
        return candidates if len(candidates)==1 and self.ax_confirms_raw_group_header(group) else []
