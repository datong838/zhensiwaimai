"""Local monthly planning only: no browser, dispatch, or completion writes."""
from __future__ import annotations

import calendar
import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

METRICS = 'daily-store-metrics-rotation-to-wechat'
COUPON = 'coupon-issue-task-flow'
INSPECTION = 'store-inspection'
SOURCES = {METRICS: 'brand-shop-switcher-organisation-tree',
           COUPON: 'brand-shop-switcher-organisation-tree',
           INSPECTION: 'jinsha-store-list'}


def is_open(row):
    return isinstance(row.get('status'), str) and row['status'].strip() == '营业中'


def identity(row, flow):
    if flow not in SOURCES:
        raise ValueError('unknown-workflow')
    if not isinstance(row, dict):
        raise ValueError('merchant-record-invalid')
    if flow == INSPECTION:
        fields = [row.get(k) for k in ('platform', 'name', 'city')]
        if fields[0] not in ('美团外卖', '淘宝闪购'):
            raise ValueError('merchant-platform-invalid')
    else:
        raw = row.get('shopId')
        if isinstance(raw, bool) or not str(raw).isdigit() or int(raw) <= 0:
            raise ValueError('merchant-id-invalid')
        fields = ['淘宝闪购', str(int(raw))]
        if not isinstance(row.get('shopName'), str) or not row['shopName'].strip():
            raise ValueError('merchant-name-missing')
    if any(not isinstance(v, str) or not v.strip() or '\x1f' in v for v in fields):
        raise ValueError('merchant-identity-missing')
    return '\x1f'.join(v.strip() for v in fields)


def refresh(previous, snapshot, *, flow, month, today):
    """Return a new registry, never mutate or replace the caller's evidence."""
    first = date.fromisoformat(month + '-01')
    if today.strftime('%Y-%m') != month:
        raise ValueError('registry-month-mismatch')
    if flow not in SOURCES or snapshot.get('source') != SOURCES[flow]:
        raise ValueError('source-mismatch')
    if snapshot.get('complete') is not True:
        raise ValueError('source-incomplete')
    observed = datetime.fromisoformat(snapshot['collectedAt'].replace('Z', '+00:00'))
    if observed.tzinfo is None:
        raise ValueError('source-timezone-missing')
    observed_day = observed.astimezone(ZoneInfo('Asia/Shanghai')).date()
    if observed_day < first or observed_day > today or (today-observed_day).days > 7:
        raise ValueError('source-stale-or-future')
    records = snapshot.get('records') if flow == INSPECTION else snapshot.get('shops')
    if not isinstance(records, list) or type(snapshot.get('total')) is not int or snapshot['total'] != len(records):
        raise ValueError('source-total-mismatch')
    if flow == INSPECTION:
        proof = snapshot.get('platformProof', {})
        for platform in ('美团外卖', '淘宝闪购'):
            p = proof.get(platform, {})
            if (p.get('filters') != ['是会员', '营业中', '授权中'] or
                    p.get('paginationComplete') is not True or
                    type(p.get('total')) is not int or p['total'] != sum(r.get('platform') == platform for r in records)):
                raise ValueError('inspection-filters-or-pagination-unproved')
    else:
        if (snapshot.get('account') != 'gmfmmZH' or snapshot.get('failures') != [] or
                type(snapshot.get('expectedOrgs')) is not int or snapshot['expectedOrgs'] < 1 or
                snapshot.get('orgsDone') != snapshot['expectedOrgs']):
            raise ValueError('brand-tree-unproved')
        if snapshot.get('openCount') != sum(is_open(r) for r in records):
            raise ValueError('source-open-total-mismatch')
    if previous is not None and (previous.get('month') != month or previous.get('flow') != flow):
        raise ValueError('previous-registry-scope-mismatch')
    result = copy.deepcopy(previous) if previous is not None else {
        'schemaVersion': 1, 'flow': flow, 'month': month, 'merchants': {},
        'plan': None, 'tasks': {}, 'executionEnabled': False,
    }
    current = {}
    for row in records:
        key = identity(row, flow)
        if key in current:
            raise ValueError('source-duplicate-identity')
        current[key] = copy.deepcopy(row)
    # Both brand workflows have the same business roster: open merchants only.
    # The complete visible tree remains in the source snapshot for reconciliation.
    if flow in (METRICS, COUPON):
        current = {key: row for key, row in current.items() if is_open(row)}
    for merchant in result['merchants'].values():
        merchant['inLatestSource'] = False
    for key, row in current.items():
        merchant = result['merchants'].setdefault(key, {})
        merchant.update(record=row, inLatestSource=True,
                        eligible=(flow == INSPECTION or is_open(row)),
                        lastSeenAt=snapshot['collectedAt'])
    result['source'] = {k: copy.deepcopy(snapshot[k]) for k in ('source', 'collectedAt', 'total')}
    result['currentMerchantKeys'] = sorted(current)
    result['executionEnabled'] = False
    return result


def plan_sa(registry, selections, work_items):
    """Exact SA matching; errors reject the whole proposed replacement."""
    if not isinstance(selections, list) or not isinstance(work_items, list) or not work_items:
        raise ValueError('plan-input-invalid')
    if any(not isinstance(x, str) or not x.strip() or '\x1f' in x for x in work_items) or len(set(work_items)) != len(work_items):
        raise ValueError('work-items-invalid')
    chosen = []
    for selected in selections:
        if (not isinstance(selected, dict) or not selected or
                set(selected) - {'platform', 'shopId', 'name', 'city'} or
                not ({'shopId', 'name'} & set(selected)) or
                any(v is None or not str(v).strip() for v in selected.values())):
            raise ValueError('sa-selector-invalid')
        matches = []
        for key, merchant in registry['merchants'].items():
            if not merchant['inLatestSource'] or not merchant['eligible']:
                continue
            r = merchant['record']
            actual = {'platform': r.get('platform', '淘宝闪购'), 'shopId': str(r.get('shopId', '')),
                      'name': r.get('name', r.get('shopName')), 'city': r.get('city', '')}
            if all(str(actual[k]).strip() == str(v).strip() for k, v in selected.items()):
                matches.append(key)
        if len(matches) != 1:
            raise ValueError('sa-not-found-or-ambiguous')
        if matches[0] in chosen:
            raise ValueError('sa-duplicate-merchant')
        chosen.append(matches[0])
    result = copy.deepcopy(registry)
    result['plan'] = {'merchantKeys': chosen, 'workItems': list(work_items)}
    for key in chosen:
        for item in work_items:
            task_key = key + '\x1f' + item
            result['tasks'].setdefault(task_key, {'merchantKey': key, 'workItem': item, 'status': 'pending'})
    return result


def daily_plan(registry, *, today, capacity=None):
    if today.strftime('%Y-%m') != registry['month']:
        raise ValueError('daily-plan-month-mismatch')
    if capacity is not None and (type(capacity) is not int or capacity < 1):
        raise ValueError('daily-capacity-invalid')
    if registry['plan'] is None:
        return {'status': 'waiting-sa', 'days': [], 'overflow': []}
    plan = registry['plan']
    pending = []
    blocked = []
    for key, task in sorted(registry['tasks'].items()):
        if task['merchantKey'] not in plan['merchantKeys'] or task['workItem'] not in plan['workItems']:
            continue
        merchant = registry['merchants'][task['merchantKey']]
        if task['status'] != 'pending':
            continue  # verified, attempted and unknown never become resend tasks.
        if not merchant['inLatestSource'] or not merchant['eligible']:
            blocked.append(key)
        else:
            pending.append(key)
    remaining_days = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    per_day = capacity or max(1, (len(pending) + remaining_days - 1) // remaining_days)
    days = [{'date': (today + timedelta(days=i)).isoformat(),
             'taskKeys': pending[i*per_day:(i+1)*per_day]} for i in range(remaining_days)]
    return {'status': 'local-plan-only', 'executionEnabled': False, 'days': days,
            'overflow': pending[remaining_days*per_day:], 'blocked': blocked}
