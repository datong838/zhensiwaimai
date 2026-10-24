"""Opt-in fixed daily slots; no effects or business completion claims."""
from datetime import datetime

def boundaries(skill, day):
    values=skill.get('schedule_times')
    if not isinstance(values,list) or not values:
        raise ValueError('fixed-schedule-times-invalid')
    result=[]
    for value in values:
        parsed=datetime.strptime(value,'%H:%M')
        if parsed.strftime('%H:%M')!=value:
            raise ValueError('fixed-schedule-time-format')
        result.append(day.replace(hour=parsed.hour,minute=parsed.minute,second=0,microsecond=0))
    if result!=sorted(set(result)):
        raise ValueError('fixed-schedule-order-or-duplicate')
    return result

def gate(skill, now, last_success):
    slots=boundaries(skill,now)
    due=[slot for slot in slots if slot<=now]
    if not due:return True,'not_due'
    try:last=datetime.fromisoformat(last_success) if last_success else None
    except ValueError:last=None
    if last and last.date()==now.date() and last>=due[-1]:return True,'done_today'
    return False,''

def next_boundary(skills, after):
    upcoming=[]
    for skill in skills:
        if not skill.get('enabled') or 'schedule_times' not in skill:continue
        times=sorted(set(skill['schedule_times']+skill.get('retry_check_times',[])))
        upcoming.extend(slot for slot in boundaries({'schedule_times':times},after) if slot>after)
    return min(upcoming) if upcoming else None


CUSTOMER_DUTY_HOURS = {
    'meituan-intelligent-customer-service-12': 12,
    'meituan-intelligent-customer-service-15': 15,
    'meituan-intelligent-customer-service': 17,
}

def customer_slot_superseded(name, now):
    hour = CUSTOMER_DUTY_HOURS.get(name)
    if hour is None:
        return False
    due = [value for value in CUSTOMER_DUTY_HOURS.values() if value <= now.hour]
    return bool(due and hour < max(due))

def customer_success_in_slot(name, finished_at, day):
    hour = CUSTOMER_DUTY_HOURS.get(name)
    if hour is None:
        return True
    try:
        stamp = datetime.fromisoformat(finished_at or '')
    except (ValueError, TypeError):
        return False
    return stamp.date() == day.date() and stamp.hour >= hour
