"""One desktop interaction owner; shared transport plus stronger content proofs."""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from contract import Rejected, file_hash
from evidence import file_frame_matches, image_distance, retryable_preflight, text_proof
from desktop_text_readback import SHARED, _copy_exact_bubble, _read_unique_payload_anchor
from desktop_headers import DesktopHeaders
from desktop_input import focus_chat_input

def file_card_count(hits,name,size,width,height):
    aliases={name}
    if name.endswith('.xlsx'):aliases.add(name[:-5]+'.xIsx')
    count=0
    for h in hits:
        if h.text.strip() not in aliases or h.cx<=width*.45 or not height*.10<h.cy<height*.8:continue
        nearby='\n'.join(x.text for x in hits if 0<x.cy-h.cy<65 and abs(x.cx-h.cx)<240)
        if file_frame_matches(name+'\n'+nearby,name,size):count+=1
    return count


class DesktopAdapter:
    channel = 'desktop'
    supported = {'text', 'image', 'file'}

    def __init__(self):
        if str(SHARED) not in sys.path:
            sys.path.insert(0, str(SHARED))
        import desktop_sender
        import desktop_preflight
        import wechat_desktop
        from wechat_interaction_lock import WeChatInteractionLock
        self.sender = desktop_sender
        self.preflight_module = desktop_preflight
        self.wd = DesktopHeaders(wechat_desktop)
        # All locator paths, including its internal calls, use the native main-window raise.
        wechat_desktop.activate_wechat = self.wd.activate_wechat
        # Internal exact-search selection uses the same native group-section proof.
        wechat_desktop.find_exact_group_rows = self.wd.find_exact_group_rows
        self.sender.wd = self.wd
        self.sender.focus_chat_input = focus_chat_input
        self.Lock = WeChatInteractionLock

    @contextmanager
    def session(self, request):
        remaining = max(0, request['context']['deadlineAt'] - time.time())
        with self.Lock('wechat-messaging', timeout_seconds=min(60, remaining)):
            yield

    def current_group_preflight(self, request):
        """Return a verified current-group receipt without navigating or searching."""
        self.wd.activate_wechat()
        state = self.wd.wechat_ax_state()
        window = state['window']
        group = request['groupName']
        headers = [item for item in state.get('texts', [])
                   if item['x'] > window['x'] + 280 and item['y'] < window['y'] + 180
                   and re.fullmatch(re.escape(group) + r'\s*[（(]\d+[）)]', item['text'].strip())]
        if not headers:
            return None
        if len(headers) != 1:
            raise Rejected('current-group-header-not-unique')
        self.sender.focus_chat_input()
        value = self.sender.focused_text_value()
        resume_text = request.get('context', {}).get('resumePreparedText')
        resume_hash = request.get('context', {}).get('resumePreparedTextSha256')
        if resume_text is not None:
            import hashlib
            if (group != '电销+直播攻坚组' or not isinstance(resume_text, str)
                    or hashlib.sha256(resume_text.encode('utf-8')).hexdigest() != resume_hash
                    ):
                return {'ok': False, 'reason': 'resume-prepared-text-readback-mismatch',
                        'sendAttempts': 0, 'group': group, 'header': headers[0]['text']}
            cleared = False
            if value not in ('', resume_text):
                # User-authorized cleanup is restricted to the uniquely
                # hash-bound blocked zero-send item in this exact group.
                self.sender.set_focused_text('')
                value = self.sender.focused_text_value()
                if value != '':
                    return {'ok': False, 'reason': 'zero-send-non-target-draft-clear-unverified',
                            'sendAttempts': 0, 'group': group, 'header': headers[0]['text']}
                cleared = True
            if value == '':
                return {'ok': True, 'reason': None, 'sendAttempts': 0, 'group': group,
                        'header': headers[0]['text'], 'note': 'ax-current-group-fast-path',
                        'groupTypeVerified': True, 'groupTypeProof': 'member-count-header',
                        'composerVerifiedEmpty': True, 'nonTargetDraftCleared': cleared,
                        'attempts': []}
            return {'ok': True, 'reason': None, 'sendAttempts': 0, 'group': group,
                    'header': headers[0]['text'], 'note': 'ax-current-group-fast-path',
                    'groupTypeVerified': True, 'groupTypeProof': 'member-count-header',
                    'composerVerifiedExactPreparedText': True,
                    'composerSha256': resume_hash, 'attempts': []}
        if value != '':
            return {'ok': False, 'reason': 'current-group-composer-not-empty',
                    'sendAttempts': 0, 'group': group, 'header': headers[0]['text']}
        return {'ok': True, 'reason': None, 'sendAttempts': 0, 'group': group,
                'header': headers[0]['text'], 'note': 'ax-current-group-fast-path',
                'groupTypeVerified': True, 'groupTypeProof': 'member-count-header',
                'composerVerifiedEmpty': True,
                'attempts': []}

    def preflight(self, request, output):
        current = self.current_group_preflight(request)
        if current is not None:
            return current | {'candidateStrategy': 'current-group-fast-path'}
        end = min(request['context']['deadlineAt'], time.time() + 30)
        attempts = []
        while True:
            result = self.preflight_module.run_exact_group_preflight(
                request['groupName'], output, locator=self.wd, acquire_lock=False,
                search_group=request['context'].get('searchGroupName'))
            attempts.append({'reason': result.get('reason'), 'elapsedMs': result.get('stageMs')})
            if result.get('ok') is True:
                result = result | {'candidateStrategy': result.get('note') or 'exact-group-preflight'}
                if result.get('note') == 'unique-search-result-clicked' and request['context'].get('searchGroupName'):
                    self._unique_search_group = request['groupName']
                    return result | {'groupTypeVerified': True, 'groupTypeProof': 'unique-search-result',
                                     'attempts': attempts}
                # A member-count suffix in the header distinguishes a group from a contact.
                state = self.wd.wechat_ax_state()
                w = state['window']
                group = request['groupName']
                groups = [x for x in state['texts']
                          if x['x'] > w['x'] + 280 and x['y'] < w['y'] + 100
                          and re.fullmatch(re.escape(group) + r'\s*[（(]\d+[）)]', x['text'])]
                if not groups:
                    section_text_proof = (result.get('note') in ('exact-group-section-text-row','unique-core-search-and-exact-header')
                                          and result.get('group') == group
                                          and self.wd.exact_group_text(result.get('header') or '', group))
                    if not section_text_proof:
                        return {'ok': False, 'reason': 'group-type-not-proven', 'attempts': attempts}
                    return result | {'groupTypeVerified': True,
                                     'groupTypeProof': 'unique-group-section-text-and-exact-header',
                                     'attempts': attempts}
                return result | {'groupTypeVerified': True, 'groupTypeProof': 'member-count-header', 'attempts': attempts}
            if (request['context'].get('searchGroupName')
                    and result.get('reason') == 'exact-group-result-count:0'):
                return result | {'attempts': attempts, 'candidateStrategy': 'unique-core-prefix-not-found'}
            # Exact locate can switch the visible conversation before the
            # same preflight round observes its title (notably with folded
            # pinned chats). Re-read only the current AX header before
            # repeating locate; this never sends, clicks, or relaxes identity.
            if result.get('reason') == 'ax-exact-header-count:0':
                current = self.current_group_preflight(request)
                if current is not None:
                    return current | {'candidateStrategy': 'current-group-post-locate-fast-path',
                                      'attempts': attempts}
            if not retryable_preflight(result) or time.time() + 2 > end:
                return result | {'attempts': attempts}
            time.sleep(2)

    def sender_preflight(self, request, fallback, group, output, **kwargs):
        """Keep a verified current chat on the no-navigation path inside sender."""
        if group != request['groupName']:
            raise Rejected('sender-preflight-group-mismatch')
        if getattr(self,'_unique_search_group',None) == group:
            self.sender.focus_chat_input()
            if self.sender.focused_text_value() != '':
                return {'ok':False,'reason':'current-group-composer-not-empty',
                        'sendAttempts':0,'group':group,'attempts':[]}
            return {'ok':True,'reason':None,'sendAttempts':0,'group':group,
                    'note':'unique-search-result-clicked','groupTypeVerified':True,
                    'groupTypeProof':'unique-search-result','composerVerifiedEmpty':True,'attempts':[]}
        current = self.current_group_preflight(request)
        if current is not None:
            return current
        return fallback(group, output, **kwargs)

    def allow_ax_title_fallback(self, request, group, preflight, error):
        """AX identity is stronger than OCR only for the verified current-chat path."""
        if (str(error) == 'desktop-group-title-not-unique:0'
                and group == request['groupName']
                and getattr(self,'_unique_search_group',None) == group):
            return True
        return (str(error) == 'desktop-group-title-not-unique:0'
                and group == request['groupName']
                and preflight.get('note') == 'ax-current-group-fast-path'
                and preflight.get('group') == group
                and preflight.get('groupTypeVerified') is True
                and self.wd.ax_confirms_raw_group_header(group))

    def send_one(self, request, item, work, grant, deadline):
        self.cleanup_owned_preview(request,item,work)
        resume_text = request.get('context', {}).get('resumePreparedText')
        resume_hash = request.get('context', {}).get('resumePreparedTextSha256')
        if resume_text is not None:
            import hashlib
            if (item.get('type') != 'text' or request.get('groupName') != '电销+直播攻坚组'
                    or resume_text != item.get('text')
                    or hashlib.sha256(resume_text.encode('utf-8')).hexdigest() != resume_hash):
                raise Rejected('resume-prepared-text-payload-mismatch')
            self.wd.activate_wechat()
            if not self.wd.ax_confirms_raw_group_header(request['groupName']):
                raise Rejected('resume-prepared-text-group-mismatch')
            self.sender.focus_chat_input()
            current = self.sender.focused_text_value()
            if current not in ('', resume_text):
                self.sender.set_focused_text('')
                current = self.sender.focused_text_value()
                if current != '':
                    raise Rejected('zero-send-non-target-draft-clear-unverified')
            if current not in ('', resume_text):
                raise Rejected('resume-prepared-text-readback-mismatch')
        args = argparse.Namespace(group=request['groupName'], payload_type=item['type'],
            item=[item.get('text', item.get('path'))], authorization=grant['authorizationRef'],
            ledger=str(work / 'transport-ledger'), marker_name='attempt.json',
            output_dir=str(work / 'transport'), execute=True)
        # The shared sender has its own locate stage.  Recheck and reuse the
        # current verified group there, so a successful outer fast path cannot
        # be followed by a redundant search or conversation click.
        fallback = self.sender.shared_preflight.run_exact_group_preflight
        fallback_verify_group = self.sender.verify_group
        fallback_set_text = self.sender.set_focused_text
        fallback_normalize_empty = self.sender.normalize_empty_composer
        def preflight(group, output, **kwargs):
            return self.sender_preflight(request, fallback, group, output, **kwargs)
        def set_text(value):
            if resume_text is not None and value == resume_text:
                current = self.sender.focused_text_value()
                if current == resume_text:
                    return
            return fallback_set_text(value)
        def normalize_empty():
            if resume_text is not None:
                value = self.sender.focused_text_value()
                if value == resume_text:
                    return True
                if value != '':
                    self.sender.set_focused_text('')
                return self.sender.focused_text_value() == ''
            return fallback_normalize_empty()
        def verify_group(shot, group, opened):
            try:
                return fallback_verify_group(shot, group, opened)
            except Exception as error:
                if self.allow_ax_title_fallback(request, group, opened, error):
                    return None
                raise
        self.sender.shared_preflight.run_exact_group_preflight = preflight
        self.sender.verify_group = verify_group
        if resume_text is not None:
            self.sender.set_focused_text = set_text
            self.sender.normalize_empty_composer = normalize_empty
        try:
            # Caller owns the common UI lock through stronger readback: never reacquire it.
            raw = self.sender._send_locked(args)
        finally:
            self.sender.shared_preflight.run_exact_group_preflight = fallback
            self.sender.verify_group = fallback_verify_group
            self.sender.set_focused_text = fallback_set_text
            self.sender.normalize_empty_composer = fallback_normalize_empty
        if raw.get('sendAttempts') != 1:
            return {'status': 'blocked', 'sendAttempts': raw.get('sendAttempts', 0),
                    'reason': raw.get('reason', 'transport-not-attempted'), 'transport': raw}
        if item['type'] == 'text':
            if raw.get('postSendInputCleared') != [True, True]:
                return {'status': 'unknown', 'sendAttempts': 1, 'reason': 'composer-not-proven-empty', 'transport': raw}
            proof = _copy_exact_bubble(request['groupName'], item, work)
            proof['newOutgoingEvidence'] = self.text_newness(request, item, work, proof)
            verified = text_proof(item, proof) and proof['newOutgoingEvidence'].get('ok') is True
            level = 'native-text-exact'
        else:
            if self.verified_media_transport(request,item,raw):
                proof={'ok':True,'transportVerified':True,
                       'completionFrames':[str(work/'transport'/f'after-send-{n}.png') for n in (1,2)]}
            else:
                try:
                    proof = self.wait_media(request, item, work, raw, deadline)
                except Exception as error:
                    return {'status':'unknown','sendAttempts':1,'reason':str(error),'transport':raw}
            verified = proof.get('ok') is True and (raw.get('verified') is True or proof.get('completionFrames'))
            level = 'image-content-match' if item['type'] == 'image' else 'file-name-size-ui'
        return {'status': 'verified' if verified else 'unknown', 'sendAttempts': 1,
                'verificationLevel': level if verified else 'insufficient',
                'reason': None if verified else proof.get('reason', 'content-readback-incomplete'),
                'evidence': proof, 'transport': raw}

    def verified_media_transport(self,request,item,raw):
        preflight=raw.get('groupPreflight') or {}
        exact=lambda value:self.wd.exact_group_text(str(value or '').strip(),request['groupName'])
        accepted_notes=('exact-group-section-text-row','unique-core-search-and-exact-header','ax-current-group-fast-path')
        return (item.get('type') in ('file','image') and raw.get('ok') is True
                and raw.get('verified') is True and raw.get('state')=='verified'
                and raw.get('sendAttempts')==1 and raw.get('postSendInputCleared')==[True,True]
                and raw.get('groupName')==request['groupName']
                and [p.get('sha256') for p in raw.get('payloads',[])]==[item.get('sha256')]
                and preflight.get('ok') is True and preflight.get('note') in accepted_notes
                and preflight.get('group')==request['groupName'] and exact(preflight.get('header')))

    def cleanup_owned_preview(self,request,item,work):
        import json
        from PIL import Image, ImageChops
        prior_path=work/'transport'/'receipt.json'
        if not prior_path.is_file():return
        prior=json.loads(prior_path.read_text())
        if prior.get('sendAttempts')!=0 or prior.get('stage')!='prepare_payload':return
        if prior.get('groupName')!=request['groupName'] or item['type']!='file':return
        if [p.get('sha256') for p in prior.get('payloads',[])]!=[item['sha256']]:raise Rejected('owned-preview-hash-mismatch')
        if not self.wd.ax_confirms_raw_group_header(request['groupName']):raise Rejected('owned-preview-group-mismatch')
        self.wd.activate_wechat();self.sender.focus_chat_input()
        value=self.sender.focused_text_value()
        if value=='':return
        if value!='\ufffc':raise Rejected('owned-preview-composer-changed')
        shot=work/'owned-preview-current.png'
        for sample in range(3):
            self.wd.screenshot_main_region(shot)
            with Image.open(shot).convert('RGB') as current, Image.open(work/'transport'/'prepared.png').convert('RGB') as original:
                if current.size!=original.size:raise Rejected('owned-preview-geometry-changed')
                w,h=current.size;box=(int(w*.28),int(h*.82),int(w*.90),int(h*.93))
                if ImageChops.difference(current.crop(box),original.crop(box)).getbbox() is None:break
            time.sleep(.3)
        else:raise Rejected('owned-preview-content-changed')
        self.sender.set_focused_text('')
        if not self.sender.chat_input_empty():raise Rejected('owned-preview-clear-failed')

    def wait_media(self, request, item, work, raw, deadline):
        end = min(deadline, time.time() + 15)
        attempt = 0
        proof = self.verify_media(request,item,work,raw)
        while (not proof.get('ok') or not raw.get('verified')) and time.time()+2 < end:
            attempt += 1
            self.wd.activate_wechat()
            frames=[]
            for n in (1,2):
                time.sleep(.8)
                frame=work/'transport'/f'content-{attempt}-{n}.png'
                self.wd.screenshot_main_region(frame)
                self.sender.verify_group(frame,request['groupName'],raw.get('groupPreflight'))
                if not self.sender.chat_input_empty():return {'ok':False,'reason':'media-composer-not-empty'}
                frames.append(frame)
            proof=self.verify_media(request,item,work,raw,frames)
            proof['completionFrames']=[str(p) for p in frames]
            if proof.get('ok'):break
        return proof

    def verify_media(self, request, item, work, raw, frames=None):
        from PIL import Image, ImageChops, ImageStat
        directory = work / 'transport'
        before_path = directory / 'before-send.png'
        frames = frames or [directory / f'after-send-{n}.png' for n in (1, 2)]
        if not before_path.is_file() or not all(p.is_file() for p in frames):
            return {'ok': False, 'reason': 'media-evidence-missing'}
        if file_hash(item['path']) != item['sha256']:
            return {'ok': False, 'reason': 'payload-drift'}
        proofs = []
        for frame in frames:
            with Image.open(frame).convert('RGB') as image, Image.open(before_path).convert('RGB') as before:
                if image.size != before.size:
                    return {'ok': False, 'reason': 'media-evidence-geometry-changed'}
                if item['type'] == 'file':
                    hits = self.wd.ocr(frame)
                    names = [h for h in hits if item['name'] == h.text.strip()
                             and h.cx > image.width * .45 and image.height * .12 < h.cy < image.height * .8]
                    if not names:
                        return {'ok': False, 'reason': 'full-file-name-missing'}
                    h = max(names, key=lambda hit: hit.cy)
                    nearby = '\n'.join(x.text for x in hits if abs(x.cy-h.cy) < 100 and abs(x.cx-h.cx) < 240)
                    box = (max(0, int(h.cx-240)), max(0, int(h.cy-60)),
                           min(image.width, int(h.cx+240)), min(image.height, int(h.cy+100)))
                    delta = sum(ImageStat.Stat(ImageChops.difference(image.crop(box), before.crop(box))).mean)
                    before_count=file_card_count(self.wd.ocr(before_path),item['name'],item['size'],image.width,image.height)
                    after_count=file_card_count(hits,item['name'],item['size'],image.width,image.height)
                    if not file_frame_matches(nearby, item['name'], item['size']) or (delta < 3 and after_count<=before_count):
                        return {'ok': False, 'reason': 'file-name-size-transfer-or-newness-unproven'}
                    proofs.append({'position': [h.cx, h.cy], 'fullName': True, 'size': True, 'changed': delta,'beforeCount':before_count,'afterCount':after_count})
                else:
                    from desktop_image import find_image_in_chat
                    match = find_image_in_chat(image, before, Path(item['path']))
                    if not match.get('ok'):
                        return match
                    proofs.append(match)
        positions = [p.get('position', p.get('center')) for p in proofs]
        stable = all(abs(a-b) <= 10 for a, b in zip(*positions))
        return {'ok': stable, 'frames': proofs, 'reason': None if stable else 'media-not-stable',
                'byteExact': False}

    def reconcile(self, request, item, work, prior):
        raw = prior.get('transport') or {}
        if item['type'] in ('file','image'):
            if self.verified_media_transport(request,item,raw) and self.wd.ax_confirms_raw_group_header(request['groupName']):
                level='image-content-match' if item['type']=='image' else 'file-name-size-ui'
                return {'status':'verified','sendAttempts':0,'verificationLevel':level,
                        'evidence':{'transportVerified':True},'transport':raw,'reconciled':True}
            if raw.get('groupName') not in (None,request['groupName']) or (
                    raw.get('payloads') and [p.get('sha256') for p in raw['payloads']]!=[item['sha256']]):
                raise Rejected('reconcile-binding-mismatch')
            return {'status':'unknown','sendAttempts':0,'reason':'reconcile-evidence-insufficient','transport':raw}
        # Text readback never invokes a sender.
        if item['type'] != 'text' or raw.get('sendAttempts') != 1 or raw.get('postSendInputCleared') != [True, True]:
            return {'status': 'unknown', 'sendAttempts': 0, 'reason': 'reconcile-evidence-insufficient'}
        if raw.get('groupName') != request['groupName'] or [p.get('sha256') for p in raw.get('payloads', [])] != [item['sha256']]:
            raise Rejected('reconcile-binding-mismatch')
        proof = _copy_exact_bubble(request['groupName'], item, work)
        # Reconcile is read-only and runs after the original send frame has ended.
        # It therefore cannot recreate a trustworthy before-send baseline.  The
        # retained transport receipt binds the single physical send, while the
        # exact native-copy proof binds the visible bubble to the requested text.
        return {'status': 'verified' if text_proof(item, proof) else 'unknown',
                'sendAttempts': 0, 'verificationLevel': 'native-text-exact', 'evidence': proof,
                'transport': raw, 'reconciled': True}

    def text_newness(self, request, item, work, proof):
        """Tie native-copy evidence to retained new outgoing bubble frames."""
        from PIL import Image, ImageChops, ImageStat
        positions = proof.get('bubblePositions', [])
        if len(positions) != 2:
            return {'ok':False, 'reason':'copy-position-missing'}
        points = []
        before_path = work/'transport'/'before-send.png'
        if not before_path.is_file():
            return {'ok':False, 'reason':'text-baseline-missing'}
        for n in (1,2):
            frame = work/'transport'/f'after-send-{n}.png'
            if not frame.is_file():
                return {'ok':False, 'reason':'text-post-frame-missing'}
            with Image.open(frame).convert('RGB') as image, Image.open(before_path).convert('RGB') as before:
                if image.size != before.size:
                    return {'ok':False, 'reason':'text-frame-geometry-changed'}
                anchor = _read_unique_payload_anchor(self.wd,frame,request['groupName'],item['text'],*image.size)
                if anchor.get('ok') is not True:
                    return {'ok':False, 'reason':'text-new-bubble-ambiguous'}
                matches = [p for p in anchor.get('linePositions',{}).values()
                           if all(abs(a-b)<=6 for a,b in zip(p,positions[-1]))]
                if len(matches)!=1:
                    return {'ok':False, 'reason':'copy-not-bound-to-send-frame'}
                x,y=matches[0]
                box=(max(0,int(x-80)),max(0,int(y-25)),min(image.width,int(x+80)),min(image.height,int(y+25)))
                crop=image.crop(box)
                green=sum(1 for r,g,b in crop.getdata() if g>150 and g-r>20 and g-b>30)
                changed=sum(ImageStat.Stat(ImageChops.difference(crop,before.crop(box))).mean)
                if green < 100 or changed < 3:
                    return {'ok':False,'reason':'new-outgoing-text-not-proven'}
                points.append({'position':[x,y],'greenPixels':green,'changed':changed})
        return {'ok':True,'frames':points}


# Compatibility export for existing offline callers.
from desktop_image import find_image_in_chat
