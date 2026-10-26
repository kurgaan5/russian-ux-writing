#!/usr/bin/env python3
"""Build a self-contained annotated review from one JSON registry and one image."""
import argparse
import base64
import json
import math
from pathlib import Path
import re
import struct


def validate(data):
    for key in ('title', 'scope'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'{key} must be a nonempty string')
    for key in ('width', 'height'):
        if type(data.get(key)) is not int or data[key] <= 0:
            raise ValueError(f'{key} must be a positive integer')
    findings = data.get('findings')
    if not isinstance(findings, list) or not findings:
        raise ValueError('findings must be a nonempty list')
    ids = set()
    def box(value, label):
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f'{label} must contain x, y, width, height')
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in value):
            raise ValueError(f'{label} must contain finite numbers')
        x, y, w, h = value
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > data['width'] or y+h > data['height']:
            raise ValueError(f'{label} is outside the source image')
    crop = data.get('crop', [0, 0, data['width'], data['height']])
    box(crop, 'crop')
    for f in findings:
        if not isinstance(f, dict):
            raise ValueError('each finding must be an object')
        identity = f.get('id', '')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,19}', identity) or identity in ids:
            raise ValueError('finding IDs must be unique stable identifiers, e.g. F01')
        ids.add(identity)
        if f.get('type') not in ('meaning', 'language', 'question'):
            raise ValueError(f'{identity}: unsupported type')
        for key in ('title', 'before', 'reason'):
            if not isinstance(f.get(key), str) or not f[key].strip():
                raise ValueError(f'{identity}: {key} must be nonempty')
        if f['type'] != 'question' and (not isinstance(f.get('after'), str) or not f['after'].strip()):
            raise ValueError(f'{identity}: an actionable replacement is required')
        for key in ('after', 'layout', 'note'):
            if key in f and not isinstance(f[key], str):
                raise ValueError(f'{identity}: {key} must be a string')
        box(f.get('box'), identity+' box')
        x, y, w, h = f['box']
        if x < crop[0] or y < crop[1] or x+w > crop[0]+crop[2] or y+h > crop[1]+crop[3]:
            raise ValueError(f'{identity}: box is outside the displayed crop')
        if 'focus' in f:
            box(f['focus'], identity+' focus')
        if 'pin' in f:
            pin = f['pin']
            if not isinstance(pin, list) or len(pin) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in pin):
                raise ValueError(f'{identity}: invalid pin')
            if not (crop[0] <= pin[0] <= crop[0]+crop[2] and crop[1] <= pin[1] <= crop[1]+crop[3]):
                raise ValueError(f'{identity}: pin is outside the displayed crop')


def build(review_path, image_path, output_path):
    data = json.loads(review_path.read_text(encoding='utf-8-sig'))
    validate(data)
    image = image_path.read_bytes()
    if image.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
        if len(image) < 24 or struct.unpack('>II', image[16:24]) != (data['width'], data['height']):
            raise ValueError('PNG dimensions do not match the registry')
    elif image.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif image.startswith(b'RIFF') and image[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('source image must be PNG, JPEG or WebP')
    if output_path.resolve() in (review_path.resolve(), image_path.resolve()):
        raise ValueError('output must not overwrite an input')
    if output_path.exists():
        raise ValueError('output exists; choose a new versioned filename')
    template = (Path(__file__).resolve().parent.parent/'assets'/'review-site.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    html = template.replace('__REVIEW_DATA__', payload).replace('__REVIEW_IMAGE__', 'data:'+mime+';base64,'+base64.b64encode(image).decode('ascii'))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')
    return len(data['findings'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='JSON: {"title":"Редактура","scope":"Баннер и форма","width":1920,"height":1080,"findings":[{"id":"F01","type":"language","title":"Запятая","before":"Выберите время чтобы продолжить","after":"Выберите время, чтобы продолжить","reason":"Запятая перед «чтобы».","box":[100,100,300,40],"layout":"Вёрстка не проверена"}]}')
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        count = build(args.review, args.image, args.out)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    print(f'Built {args.out} with {count} findings from one registry.')


if __name__ == '__main__':
    main()
