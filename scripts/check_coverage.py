#!/usr/bin/env python3
"""Track editorial coverage; never infer semantic correctness from a valid ledger."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'references' / 'checks.json'
TAGS = {'scope', 'block', 'text', 'copy', 'button', 'link', 'list', 'input', 'tooltip',
        'snackbar', 'informer', 'modal', 'onboarding', 'badge', 'empty', 'search',
        'loading', 'success', 'error', 'push', 'sms', 'email', 'release', 'legal', 'data'}
PASSES = ('context', 'relations', 'language', 'improvements', 'fit', 'human_reading')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def filled(value):
    return isinstance(value, str) and bool(value.strip())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def registry_checks(registry):
    checks = registry['checks']
    require(bool(checks), 'Registry is empty')
    ids = [c['id'] for c in checks]
    require(len(ids) == len(set(ids)), 'Duplicate check IDs')
    for c in checks:
        for key in ('id', 'group', 'criterion', 'method', 'example'):
            require(filled(c.get(key)), f'{c.get("id")}: missing {key}')
        require(bool(c.get('targets')) and set(c['targets']) <= TAGS, f'{c["id"]}: bad targets')
        require(bool(c.get('sources')), f'{c["id"]}: no sources')
        for src in c['sources']:
            require((REGISTRY.parent / src).is_file(), f'{c["id"]}: missing source {src}')
    return checks


def inventory_units(inventory):
    require(inventory.get('mode') in ('review', 'write'), 'mode must be review or write')
    materials = inventory.get('materials', [])
    require(bool(materials), 'Material inventory required')
    require(len({m['id'] for m in materials}) == len(materials), 'Duplicate material IDs')
    for m in materials:
        require(m.get('status') in ('read', 'unavailable', 'not_needed'), 'Unfinished material review')
        for key in ('id', 'locator', 'reason', 'used_for'):
            require(filled(m.get(key)), f'Material missing {key}')
    units = inventory['units']
    ids = [u['id'] for u in units]
    require(len(ids) == len(set(ids)), 'Duplicate unit IDs')
    require(sum(u.get('kind') == 'scope' for u in units) == 1, 'Exactly one scope required')
    require(any(u.get('kind') == 'block' for u in units), 'At least one block required')
    require(any(u.get('kind') == 'text' for u in units), 'At least one text unit required')
    by_id = {u['id']: u for u in units}
    for u in units:
        uid = u['id']
        require(filled(uid), 'Empty unit ID')
        require(u.get('kind') in ('scope', 'block', 'text'), f'{uid}: invalid kind')
        require(set(u.get('tags', [])) <= TAGS - {'scope', 'block', 'text', 'copy'}, f'{uid}: invalid tags')
        require(filled(u.get('locator')), f'{uid}: locator required')
        require(isinstance(u.get('text'), str), f'{uid}: text snapshot required')
        if u['kind'] == 'text':
            require(u.get('content_role', 'copy') in ('copy', 'value'), f'{uid}: invalid content role')
            if u.get('content_role') == 'value':
                require(filled(u.get('value_reason')), f'{uid}: value classification needs evidence')
                require('data' in u.get('tags', []), f'{uid}: values must retain data checks')
        if inventory['mode'] == 'write' and u['kind'] == 'text':
            require(filled(u['text']), f'{uid}: writing mode needs final text')
        require(filled(u.get('context')), f'{uid}: context required')
        if u['kind'] == 'scope':
            require(u.get('parent') is None, f'{uid}: scope cannot have parent')
        else:
            parent = by_id.get(u.get('parent'))
            require(parent is not None, f'{uid}: missing parent')
            require(parent['kind'] in ('scope', 'block'), f'{uid}: invalid parent')
            if u['kind'] == 'text':
                require(parent['kind'] == 'block', f'{uid}: text must belong to block')
            visited = {uid}
            node = u
            while node.get('parent') is not None:
                require(node['parent'] not in visited, f'{uid}: parent cycle')
                visited.add(node['parent'])
                require(node['parent'] in by_id, f'{uid}: missing ancestor')
                node = by_id[node['parent']]
        count = u.get('count', 1)
        require(type(count) is int and count >= 1, f'{uid}: invalid count')
        if count > 1:
            locations = u.get('locations', [])
            require(len(locations) == count and len(set(locations)) == count,
                    f'{uid}: all repeated locations required')
            require(all(filled(x) for x in locations) and filled(u.get('group_reason')),
                    f'{uid}: repeat grouping needs evidence')
    for block in (u for u in units if u['kind'] == 'block'):
        require(any(u.get('parent') == block['id'] for u in units), f'{block["id"]}: empty block')
    return units


def expected_pairs(checks, units):
    pairs = {}
    for c in checks:
        matching = []
        for u in units:
            tags = {u['kind']} | set(u.get('tags', []))
            if u['kind'] == 'text' and u.get('content_role', 'copy') == 'copy':
                tags.add('copy')
            if set(c['targets']) & tags:
                matching.append(u)
        for u in matching:
            pairs[(c['id'], u['id'])] = False
        if not matching:
            pairs[(c['id'], None)] = True
    return pairs


def make_ledger(registry, inventory):
    checks = registry_checks(registry)
    units = inventory_units(inventory)
    rows = []
    for (cid, uid), absent in expected_pairs(checks, units).items():
        rows.append({'check_id': cid, 'unit_id': uid,
                     'status': 'not_applicable' if absent else 'pending',
                     'evidence': 'No matching component in inventory' if absent else '',
                     'finding_ids': []})
    return {'mode': inventory['mode'], 'registry_sha256': digest(registry),
            'inventory_sha256': digest(inventory), 'inventory_review': '', 'material_review': '',
            'passes': {p: '' for p in PASSES}, 'rows': rows, 'findings': [],
            'second_look': {}, 'limitations': [], 'editorial_decisions': []}


def validate_editorial(inventory, ledger, units):
    """Check traceability of example-led choices, not their literary merit."""
    patterns = set(re.findall(r'^## (EX-\d+)\.',
                             (ROOT / 'references' / 'transformations.md').read_text(encoding='utf-8'), re.M))
    by_unit = {u['id']: u for u in units}
    copy_units = [u for u in units if u['kind'] == 'text' and u.get('content_role', 'copy') == 'copy']
    required_blocks = {u['parent'] for u in copy_units}
    decisions = ledger.get('editorial_decisions', [])
    blocks = [d['block_id'] for d in decisions]
    require(len(blocks) == len(set(blocks)), 'Duplicate editorial block decisions')
    require(set(blocks) == required_blocks, 'Editorial decisions must cover every block with authored copy')
    selected_texts = {}
    for d in decisions:
        bid = d['block_id']
        block_copy_ids = {u['id'] for u in copy_units if u['parent'] == bid}
        for key in ('intent', 'transfer', 'reason'):
            require(filled(d.get(key)), f'{bid}: editorial {key} required')
        require(isinstance(d.get('must_keep'), list) and bool(d['must_keep'])
                and all(filled(s) for s in d['must_keep']), f'{bid}: semantic constraints required')
        require(bool(d.get('pattern_ids')) and set(d['pattern_ids']) <= patterns,
                f'{bid}: valid source example IDs required')
        candidates = d.get('candidates', [])
        ids = [c['id'] for c in candidates]
        require(len(ids) == len(set(ids)) and 'original' not in ids, f'{bid}: invalid candidate IDs')
        require(d.get('selected') == 'original' or d.get('selected') in ids, f'{bid}: selected candidate missing')
        if not candidates:
            require(filled(d.get('keep_evidence')), f'{bid}: unchanged copy needs example-based evidence')
        for c in candidates:
            for key in ('id', 'operation', 'benefit', 'cost'):
                require(filled(c.get(key)), f'{bid}: candidate {key} required')
            require(isinstance(c.get('texts'), dict) and bool(c['texts']), f'{bid}: real alternative text required')
            require(block_copy_ids <= set(c['texts']),
                    f'{bid}: candidate must include every authored text in the block')
            for uid, text in c['texts'].items():
                require(uid in by_unit and by_unit[uid]['kind'] == 'text' and by_unit[uid]['parent'] == bid,
                        f'{bid}: candidate targets another block')
                require(isinstance(text, str), f'{uid}: candidate must contain actual text')
        if d['selected'] != 'original':
            chosen = next(c for c in candidates if c['id'] == d['selected'])
            for uid, text in chosen['texts'].items():
                actual = (by_unit[uid].get('candidate_text', by_unit[uid]['text'])
                          if inventory['mode'] == 'review' else by_unit[uid]['text'])
                require(actual == text, f'{uid}: selected candidate differs from inventory')
                selected_texts[uid] = text
    if inventory['mode'] == 'review':
        for u in copy_units:
            if 'candidate_text' in u and u['candidate_text'] != u['text']:
                require(selected_texts.get(u['id']) == u['candidate_text'], f'{u["id"]}: proposal lacks editorial choice')
        for uid, text in selected_texts.items():
            if text != by_unit[uid]['text']:
                require(any(uid in f['unit_ids'] and f['type'] in ('fix', 'improve')
                            for f in ledger.get('findings', [])), f'{uid}: selected change absent from findings')
    return len(decisions)


def validate(registry, inventory, ledger):
    checks = registry_checks(registry)
    units = inventory_units(inventory)
    require(ledger.get('mode') == inventory['mode'], 'Mode mismatch')
    require(ledger.get('registry_sha256') == digest(registry), 'Registry changed: review coverage again')
    require(ledger.get('inventory_sha256') == digest(inventory), 'Stale inventory/text: review coverage again')
    require(filled(ledger.get('inventory_review')), 'Inventory completeness and tags need manual review')
    require(filled(ledger.get('material_review')), 'Available material collection must be complete')
    editorial_count = validate_editorial(inventory, ledger, units)
    for p in PASSES:
        require(filled(ledger.get('passes', {}).get(p)), f'Missing editorial pass: {p}')
    expected = expected_pairs(checks, units)
    by_check = {c['id']: c for c in checks}
    rows = ledger['rows']
    keys = [(r['check_id'], r.get('unit_id')) for r in rows]
    require(len(keys) == len(set(keys)), 'Duplicate coverage pairs')
    require(set(keys) == set(expected),
            f'Coverage mismatch: missing {len(set(expected) - set(keys))}, extra {len(set(keys) - set(expected))}')
    findings = ledger.get('findings', [])
    fids = [f['id'] for f in findings]
    require(len(fids) == len(set(fids)), 'Duplicate finding IDs')
    by_fid = {f['id']: f for f in findings}
    linked_units = set()
    for f in findings:
        require(f['type'] in ('fix', 'improve', 'clarify'), f'{f["id"]}: invalid finding type')
        for key in ('title', 'before', 'why'):
            require(filled(f.get(key)), f'{f["id"]}: missing {key}')
        require(bool(f.get('check_ids')) and bool(f.get('unit_ids')), f'{f["id"]}: missing links')
        require(set(f['check_ids']) <= {c['id'] for c in checks}, f'{f["id"]}: unknown check')
        require(set(f['unit_ids']) <= {u['id'] for u in units}, f'{f["id"]}: unknown unit')
        if f['type'] != 'clarify':
            require(filled(f.get('after')), f'{f["id"]}: replacement required')
        else:
            require(filled(f.get('question')), f'{f["id"]}: question required')
        linked_units.update(f['unit_ids'])
    unverified = set()
    for r in rows:
        key = (r['check_id'], r.get('unit_id'))
        status = r.get('status')
        require(status in ('pass', 'finding', 'not_applicable', 'unverified'), f'{key}: pending/invalid status')
        require(filled(r.get('evidence')), f'{key}: evidence/reason required')
        if expected[key]:
            require(status == 'not_applicable', f'{key}: absent component cannot pass')
        elif status == 'not_applicable':
            require(by_check[r['check_id']].get('allow_not_applicable', False),
                    f'{key}: required for this target; unknown evidence must be unverified')
        if status == 'unverified':
            unverified.add(key)
        refs = r.get('finding_ids', [])
        if status == 'finding':
            require(bool(refs), f'{key}: finding ID required')
        if status in ('pass', 'not_applicable'):
            require(not refs, f'{key}: passed/inapplicable check cannot link open finding')
        for fid in refs:
            require(fid in by_fid, f'{key}: unknown finding {fid}')
            f = by_fid[fid]
            require(r['check_id'] in f['check_ids'] and r['unit_id'] in f['unit_ids'], f'{fid}: inconsistent links')
            if f['type'] == 'clarify':
                require(status == 'unverified', f'{fid}: clarification must remain unverified')
    for f in findings:
        linked = [r for r in rows if f['id'] in r.get('finding_ids', [])]
        require({r['check_id'] for r in linked} == set(f['check_ids']), f'{f["id"]}: check links incomplete')
        require({r['unit_id'] for r in linked} == set(f['unit_ids']), f'{f["id"]}: unit links incomplete')
    limits = ledger.get('limitations', [])
    require(all(filled(l.get('reason')) for l in limits), 'Limitation reason required')
    limit_keys = [(l['check_id'], l.get('unit_id')) for l in limits]
    require(len(limit_keys) == len(set(limit_keys)) and set(limit_keys) == unverified,
            'Every unverified pair must have exactly one visible limitation')
    second = ledger.get('second_look', {})
    require(set(second) <= {u['id'] for u in units}, 'Unknown unit in second look')
    for u in units:
        needs_second = u['kind'] == 'block' or (u['kind'] == 'text' and u.get('content_role', 'copy') == 'copy')
        if needs_second and u['id'] not in linked_units:
            require(filled(second.get(u['id'])), f'{u["id"]}: second look required for unit without findings')
    if inventory['mode'] == 'write':
        require(not findings, 'Writing mode: fix known issues in final draft, no open findings/report')
    counts = {s: sum(r['status'] == s for r in rows)
              for s in ('pass', 'finding', 'not_applicable', 'unverified')}
    return {'registry_checks': len(checks), 'units': len(units), 'pairs': len(rows), 'editorial_blocks': editorial_count,
            'statuses': counts, 'findings': len(findings), 'coverage_accounted_for': True,
            'all_applicable_verified': not unverified,
            'semantic_quality_verified_by_script': False}


def render(registry):
    checks = registry_checks(registry)
    lines = ['# Реестр проверок UX-копирайтинга', '',
             f'**{len(checks)} проверок**. Канонический источник — [checks.json](checks.json).', '',
             'Этот файл создаётся командой `python3 scripts/check_coverage.py render`; правь JSON и обновляй представление.', '',
             'Применяй [протокол покрытия](coverage.md) в обоих режимах. Все ID должны получить исход, но неприменимое и непроверенное не считаются успешной проверкой. Примеры учебные: переносится приём, а факты проверяются заново.', '']
    lines += ['## Состав', '', '| Группа | ID | Проверок |', '|---|---|---:|']
    for group in dict.fromkeys(c['group'] for c in checks):
        subset = [c for c in checks if c['group'] == group]
        lines.append(f'| {group} | {subset[0]["id"]} — {subset[-1]["id"]} | {len(subset)} |')
    lines += ['', 'Теги определяют объекты проверки. Если подходящих объектов нет, ID учитывается как неприменимый. Если объект есть, отсутствие данных означает unverified. Дополнительное снятие по условию допускается только для пунктов с пометкой «зависит от условия».', '']
    current = None
    for c in checks:
        if c['group'] != current:
            current = c['group']
            lines += [f'## {current}', '']
        sources = ', '.join(f'[{s}]({s})' for s in c['sources'])
        applicability = 'зависит от условия; неприменимость обоснуй' if c.get('allow_not_applicable') else 'обязательна для объекта'
        lines += [f'### {c["id"]} · {c["criterion"]}', '',
                  f'Область: `{", ".join(c["targets"])}`; {applicability}. {c["method"]}', '',
                  f'Пример / исключение: {c["example"]}', '', f'Основание: {sources}.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('init', 'validate'):
        p = sub.add_parser(command)
        p.add_argument('--inventory', required=True)
        p.add_argument('--coverage', required=True)
    sub.add_parser('render')
    args = parser.parse_args()
    registry = read(REGISTRY)
    try:
        if args.command == 'render':
            (REGISTRY.parent / 'checks.md').write_text(render(registry), encoding='utf-8')
            print(f'Rendered {len(registry["checks"])} checks')
        elif args.command == 'init':
            ledger = make_ledger(registry, read(args.inventory))
            with Path(args.coverage).open('x', encoding='utf-8') as out:
                json.dump(ledger, out, ensure_ascii=False, indent=2)
                out.write('\n')
            print(f'Created {len(ledger["rows"])} pending/absent pairs; manual review required')
        else:
            print(json.dumps(validate(registry, read(args.inventory), read(args.coverage)), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Coverage error: {exc}\n')


if __name__ == '__main__':
    main()
