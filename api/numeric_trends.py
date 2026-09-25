"""Bounded plots of recorded numbers, without conversion or inferred ranges."""
import math
from datetime import datetime, timezone

POINT_LIMIT = 200


def series(records, query, clinic_timezone):
    from actions import fail
    if len(records) > POINT_LIMIT:
        fail(f'Trend needs a narrower date range: {len(records)} records match; the limit is {POINT_LIMIT} points. No partial chart was created.')
    points=[]
    for row in records:
        data=row['data']
        value=data.get('value')
        low=data.get('low'); high=data.get('high')
        numeric=lambda value:isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
        if not numeric(value) or data.get('value_type','number')!='number':
            fail('Trend requires recorded numeric values. Review this concept in the observation catalog; no values were converted or omitted.')
        if any(bound is not None and not numeric(bound) for bound in (low,high)) or low is not None and high is not None and low>high:
            fail('Trend contains an invalid supplied reference range. Review the original records; no range was inferred.')
        # Native observations are recorded at their source event time. Older
        # local observations have only a record timestamp; label that fallback.
        when=data.get('observed_at') or data.get('occurred_at') or row['created_at']
        try:
            instant=datetime.fromisoformat(when.replace('Z','+00:00'))
            if instant.tzinfo is None:instant=instant.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError,AttributeError):
            fail('Trend contains an invalid recorded timestamp. Review the original records before plotting.')
        points.append({'record_id':row['id'],'version':row['version'],
                       'observed_at':instant.astimezone(timezone.utc).isoformat(),
                       'time_basis':'observed' if data.get('observed_at') or data.get('occurred_at') or data.get('native_spine') else 'recorded',
                       'value':value,'ref_low':low,'ref_high':high,
                       'flag':'low' if low is not None and value<low else 'high' if high is not None and value>high else None,
                       'event_id':data.get('event_id'),'source_id':data.get('source_id'),'source':data.get('receipt')})
    points.sort(key=lambda p:(p['observed_at'],p['record_id']))
    names=sorted({r['data'].get('name') or query['code'] for r in records})
    return {'concept':{'code':query['code'],'name':names[0] if len(names)==1 else query['code'],'unit':query['unit']},
            'series':points,'timezone':clinic_timezone,'point_limit':POINT_LIMIT}
