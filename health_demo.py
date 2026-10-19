"""Offline Mi Fitness export adapter; Python 3.11+, standard library only."""
import argparse
import csv
import hashlib
import html
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from zipfile import ZipFile, ZIP_DEFLATED

TZ = timezone(timedelta(hours=8))
FIELDS = ['date', 'sleep_minutes', 'sleep_start', 'sleep_end', 'sleep_score',
          'nap_minutes', 'steps', 'active_kcal', 'heart_rate_sample_mean_bpm',
          'heart_rate_samples', 'resting_sample_mean_bpm']


def number(value, minimum=0, maximum=None):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        if not math.isfinite(n) or n < minimum or (maximum is not None and n > maximum):
            return None
        return n
    except (TypeError, ValueError):
        return None


def stamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('timestamp needs explicit offset')
    return d.astimezone(TZ)


def nap_flag(value):
    if value in (True, 1, '1', 'true', 'True'):
        return True
    if value in (False, 0, '0', 'false', 'False', None):
        return False
    raise ValueError('invalid nap flag')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def aggregate(payload, start, end):
    """One account per export; +08 reporting; wake-date sleep; missing stays null."""
    if start > end or (end-start).days > 3660:
        raise ValueError('date range must be ordered and no longer than 3661 days')
    if not isinstance(payload, dict) or payload.get('schema_version') != '1.0':
        raise ValueError('expected bridge schema_version 1.0')
    records = payload.get('records')
    if not isinstance(records, dict):
        raise ValueError('expected records object')
    # Do not mix accounts. IDs are used only for validation and never emitted.
    users = {str(r['user_id']) for rows in records.values() if isinstance(rows, list)
             for r in rows if isinstance(r, dict) and r.get('user_id') is not None}
    if len(users) > 1:
        raise ValueError('multiple accounts found; export one account at a time')
    warnings = []
    counts = {'duplicates_removed': 0, 'invalid_records': 0,
              'extra_main_sleep_candidates': 0, 'activity_conflicts': 0}
    parsed = {}
    for name in ('sleep', 'daily_activity', 'heart_rate'):
        rows = records.get(name, [])
        if not isinstance(rows, list):
            raise ValueError(f'{name} must be a list')
        unique, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                counts['invalid_records'] += 1
                continue
            # Identical rows only. Conflicting versions are not silently collapsed.
            fingerprint = digest(row)
            if fingerprint in seen:
                counts['duplicates_removed'] += 1
                continue
            seen.add(fingerprint)
            unique.append(row)
        parsed[name] = unique
    sleep, activity, hr = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in parsed['sleep']:
        try:
            a, b = stamp(r['start_at']), stamp(r['end_at'])
            minutes = number(r.get('time_asleep_minutes'))
            if b <= a or minutes is None or minutes > (b-a).total_seconds()/60 + 2:
                raise ValueError('invalid sleep duration')
            score = number(r.get('sleep_score'), maximum=100)
            if r.get('sleep_score') is not None and score is None:
                warnings.append('存在无效睡眠评分，已留空。')
            sleep[b.date()].append({'start': a.isoformat(), 'end': b.isoformat(),
                                    'minutes': minutes, 'score': score,
                                    'nap': nap_flag(r.get('is_nap'))})
        except (ValueError, TypeError, KeyError, AttributeError):
            counts['invalid_records'] += 1
    for r in parsed['daily_activity']:
        try:
            day = date.fromisoformat(r['date'])
            steps = number(r.get('steps'))
            kcal = number(r.get('active_kcal'))
            if steps is None and kcal is None:
                raise ValueError('no usable activity')
            activity[day].append((steps, kcal))
        except (ValueError, TypeError, KeyError):
            counts['invalid_records'] += 1
    for r in parsed['heart_rate']:
        try:
            t = stamp(r['timestamp'])
            bpm = number(r.get('bpm'), minimum=1)
            if bpm is None:
                raise ValueError('invalid bpm')
            hr[t.date()].append((bpm, r.get('sample_type') == 'resting'))
        except (ValueError, TypeError, KeyError, AttributeError):
            counts['invalid_records'] += 1
    daily, safe_sleep = [], []
    for i in range((end-start).days+1):
        day = start + timedelta(days=i)
        sessions = sleep[day]
        main = [s for s in sessions if not s['nap']]
        main.sort(key=lambda s: (-s['minutes'], s['start'], s['end']))
        selected = main[0] if main else None
        counts['extra_main_sleep_candidates'] += max(0, len(main)-1)
        for s in sessions:
            safe_sleep.append({'wake_date': day.isoformat(), **s,
                               'selected_main': s is selected})
        acts = set(activity[day])
        if len(acts) > 1:
            counts['activity_conflicts'] += 1
        act = next(iter(acts)) if len(acts) == 1 else (None, None)
        samples = hr[day]
        resting = [v for v, is_rest in samples if is_rest]
        daily.append(dict(zip(FIELDS, [day.isoformat(),
            selected['minutes'] if selected else None,
            selected['start'] if selected else None,
            selected['end'] if selected else None,
            selected['score'] if selected else None,
            sum(s['minutes'] for s in sessions if s['nap']) if sessions else None,
            *act, round(mean(v for v, _ in samples), 2) if samples else None,
            len(samples), round(mean(resting), 2) if resting else None])))
    warnings += [
        '统计时区固定为 UTC+08:00；睡眠按醒来日期，活动按源日期，心率按采样时间归日。',
        '同日多个非午睡候选仅选最长一段；不是多段夜间睡眠的完整合并，需核对候选。',
        '同日午睡可能存在多设备重叠，未进行区间融合；午睡总量需核对。',
        '心率均值为样本算术平均，受采样频率影响，不等于全天平均或静息心率。',
        '未包含睡眠阶段：上游未知编码可能已归为浅睡，当前导出无法恢复。',
        '活动冲突日期留空；缺失记录不补零；缺失评分不推算。',
        '这是去标识化的健康数据，仍含日期与测量值，不是匿名数据或医学诊断。']
    quality = {**counts, 'warnings': list(dict.fromkeys(warnings)),
               'missing_dates': {key: [r['date'] for r in daily if r[key] is None]
                                 for key in ('sleep_minutes', 'steps', 'heart_rate_sample_mean_bpm')}}
    summary = {}
    for key in ('sleep_minutes', 'steps', 'active_kcal', 'heart_rate_sample_mean_bpm'):
        values = [r[key] for r in daily if r[key] is not None]
        summary[key] = {'days': len(values), 'mean': round(mean(values), 2) if values else None,
                        'min': min(values) if values else None,
                        'max': max(values) if values else None}
    return {'schema_version': 'health-analysis/1', 'synthetic': payload.get('synthetic') is True,
            'period': {'start': str(start), 'end': str(end), 'timezone': 'UTC+08:00'},
            'summary': summary, 'daily': daily, 'sleep_sessions': safe_sleep, 'quality': quality}


def demo_payload():
    rng = random.Random(42)
    records = {'sleep': [], 'daily_activity': [], 'heart_rate': []}
    base = date(2026, 10, 1)
    for i in range(14):
        d = base + timedelta(days=i)
        meta = {'user_id': 'SYNTHETIC_ACCOUNT', 'device_id': 'SYNTHETIC_DEVICE'}
        if i != 6:
            end = datetime.combine(d, datetime.min.time(), TZ) + timedelta(hours=7, minutes=rng.randrange(70))
            start = end - timedelta(minutes=rng.randrange(360, 510))
            duration = int((end-start).total_seconds()/60)
            records['sleep'].append({**meta, 'start_at': start.isoformat(), 'end_at': end.isoformat(),
                'time_asleep_minutes': duration-15, 'is_nap': False,
                'sleep_score': None if i == 4 else rng.randrange(65, 95)})
        if i != 9:
            records['daily_activity'].append({**meta, 'date': str(d), 'steps': rng.randrange(2500, 14000),
                                              'active_kcal': rng.randrange(100, 600)})
        for h in (8, 12, 18, 22):
            records['heart_rate'].append({**meta, 'timestamp': f'{d}T{h:02d}:00:00+08:00',
                'bpm': rng.randrange(55, 105), 'sample_type': 'resting' if h == 8 else 'passive'})
    records['sleep'].append(records['sleep'][0].copy())
    return {'schema_version': '1.0', 'source': 'mi_fitness_data_bridge',
            'synthetic': True, 'records': records}


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def write_outputs(result, out):
    if out.exists() and any(out.iterdir()):
        raise ValueError('output directory must be empty; choose a new path')
    out.mkdir(parents=True, exist_ok=True)
    write_json(out/'analysis_packet.json', result)
    with (out/'daily.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(result['daily'])
    label = '合成数据演示' if result['synthetic'] else '导入数据汇总（未与 App 核验）'
    rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(r[k])) if r[k] is not None else "—"}</td>'
                                  for k in FIELDS) + '</tr>' for r in result['daily'])
    notes = ''.join(f'<li>{html.escape(s)}</li>' for s in result['quality']['warnings'])
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>运动健康数据示例</title><style>body{{font:16px system-ui;max-width:1200px;margin:40px auto;padding:20px;color:#243347;background:#f5f8fb}}h1{{color:#176b64}}.scroll{{overflow:auto;background:white;border-radius:12px}}table{{border-collapse:collapse;font-size:13px}}td,th{{padding:12px;border-bottom:1px solid #ddd;white-space:nowrap}}li{{margin:10px 0}}pre{{white-space:pre-wrap}}</style>
<h1>{label}</h1><p>{result['period']['start']} 至 {result['period']['end']} · UTC+08:00 · 缺失显示为 —</p>
<h2>每日数据</h2><div class="scroll"><table><thead><tr>{''.join('<th>'+k+'</th>' for k in FIELDS)}</tr></thead><tbody>{rows}</tbody></table></div>
<h2>数据质量</h2><pre>{html.escape(json.dumps({k:v for k,v in result['quality'].items() if k != 'warnings'}, ensure_ascii=False, indent=2))}</pre><ul>{notes}</ul></html>'''
    (out/'report.html').write_text(doc, encoding='utf-8')
    (out/'analysis_request.txt').write_text('请分析同目录 analysis_packet.json。先检查 quality 和覆盖情况，再描述作息、活动与心率变化。区分事实与推测，不能据此诊断或推断因果。缺失不是零，sample mean 不是全天均值。synthetic=true 时只说明方法，不评价我的真实健康。\n', encoding='utf-8')
    # Package only the approved outputs, not the input, report, credentials or GPS.
    with ZipFile(out/'submit_to_chatgpt.zip', 'w', ZIP_DEFLATED) as z:
        for name in ('analysis_packet.json', 'daily.csv', 'analysis_request.txt'):
            z.write(out/name, name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, help='bridge JSON export')
    p.add_argument('--demo', action='store_true', help='use synthetic data')
    p.add_argument('--start', required=True, type=date.fromisoformat)
    p.add_argument('--end', required=True, type=date.fromisoformat)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    if a.demo == bool(a.input):
        p.error('choose exactly one of --demo or --input')
    try:
        payload = demo_payload() if a.demo else json.loads(a.input.read_text(encoding='utf-8-sig'))
        result = aggregate(payload, a.start, a.end)
        write_outputs(result, a.out)
        print('Done:', a.out.resolve())
    except (ValueError, OSError, TypeError) as exc:
        # Do not echo input values or file contents into logs.
        p.exit(1, f'Failed ({type(exc).__name__}). Check JSON schema, dates, offsets, account count and empty output path.\n')


if __name__ == '__main__':
    main()
