#!/usr/bin/env python3
"""Apply the shipped Neco identity and integrations through Open WebUI's API."""
import base64
import json
from pathlib import Path
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'neco'))
from prompt import avatar_path, build_persona, load_character, list_characters

FILTERS = (
    # Keep installed function IDs stable across source-file renames. Existing
    # models keep their attachments and do not receive duplicate filters.
    (
        'neco_system_vitals',
        'Neco System Vitals',
        ROOT / 'openwebui/functions/senses.py',
        'Experimental read-only host telemetry context for Neco.',
    ),
    (
        'neco_memory_context',
        'Neco Continuity Memory',
        ROOT / 'openwebui/functions/recall.py',
        'Read-only retrieval of Neco local episodic memory and evolving state.',
    ),
    (
        'neco_grounding',
        'Neco Grounding',
        ROOT / 'openwebui/functions/grounding.py',
        'Always-on host facts and the cat\'s own model/memory config.',
    ),
)


class SetupError(Exception):
    """A safe, actionable message constructed by this script."""


def step(message):
    print('[setup] ' + message, flush=True)


def main():
    step('Reading .env')
    settings = {}
    allowed = {
        'NECO_MODEL', 'OPENWEBUI_PORT', 'OPENWEBUI_URL', 'OWNER_NAME',
        'NECO_PERSONA', 'NECO_MACHINE', 'NECO_CHARACTER'
    }
    for line in (ROOT / '.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() in allowed:
            words = shlex.split(value, comments=True)
            settings[key.strip()] = words[0] if words else ''

    model = settings.get('NECO_MODEL', '').strip()
    if not model:
        raise SetupError('Set NECO_MODEL in .env first.')

    step('Reading saved API key (contents hidden)')
    token = (ROOT / '.runtime/neco_token').read_text().strip()
    if not token:
        raise SetupError('Run ./scripts/set-token.sh with an admin API key first.')

    base = settings.get('OPENWEBUI_URL') or 'http://127.0.0.1:' + settings.get('OPENWEBUI_PORT', '3300')
    persona = settings.get('NECO_PERSONA', 'lite').strip().lower()
    owner = settings.get('OWNER_NAME') or 'friend'
    machine = settings.get('NECO_MACHINE') or 'this machine'

    character = (settings.get('NECO_CHARACTER') or 'neco').strip().lower()
    try:
        info = load_character(character)
    except ValueError as error:
        raise SetupError(str(error)) from error
    cat = info['name']

    step('Building ' + cat + ' identity + orientation + voice')
    try:
        prompt = build_persona(owner=owner, machine=machine, mode=persona, character=character)
    except ValueError as error:
        raise SetupError(str(error)) from error
    if not prompt.strip():
        raise SetupError(cat + ' prompt is empty.')

    def api(path, payload=None, method=None):
        if method is None:
            method = 'POST' if payload is not None else 'GET'
        request = urllib.request.Request(
            base.rstrip('/') + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    step('Checking models visible to the Open WebUI account')
    models = api('/api/models')
    if model not in {item['id'] for item in models.get('data', [])}:
        raise SetupError('NECO_MODEL is not available to this account. Check the Ollama connection and model name.')

    installed_filter_ids = []
    for filter_id, name, filter_file, description in FILTERS:
        step('Installing ' + name)
        filter_payload = {
            'id': filter_id,
            'name': name,
            'content': filter_file.read_text(),
            'meta': {'description': description},
        }
        try:
            existing_filter = api('/api/v1/functions/id/' + filter_id)
        except urllib.error.HTTPError as error:
            if error.code not in (401, 404):
                raise
            existing_filter = None

        if existing_filter:
            function = api('/api/v1/functions/id/' + filter_id + '/update', filter_payload)
        else:
            function = api('/api/v1/functions/create', filter_payload)
        if not function:
            raise SetupError('Open WebUI did not confirm ' + name + '.')

        function = api('/api/v1/functions/id/' + filter_id)
        if not function.get('is_active'):
            function = api('/api/v1/functions/id/' + filter_id + '/toggle', {}, method='POST')
        if not function or not function.get('is_active'):
            raise SetupError(name + ' could not be enabled.')
        installed_filter_ids.append(filter_id)

    path = '/api/v1/models/model?id=' + urllib.parse.quote(model, safe='')
    step('Reading existing model configuration')
    try:
        existing = api(path)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        existing = None
    if existing is not None and existing.get('write_access') is False:
        raise SetupError('This API key cannot edit the model. Use an admin key.')

    payload = {key: existing[key] for key in
        ('id', 'base_model_id', 'name', 'meta', 'params', 'access_grants', 'is_active')
        if existing and key in existing}
    if not existing:
        payload = dict(id=model, base_model_id=None, name=cat, meta={}, params={}, is_active=True)
    else:
        # Rename only when the entry already carries a cat's name (switching cats);
        # leave a user's own custom display name alone.
        known = {load_character(c)['name'] for c in list_characters()}
        if payload.get('name') in known or payload.get('name') == model:
            payload['name'] = cat
    payload['params'] = dict(payload.get('params') or {}, system=prompt)

    image_file = avatar_path(character)
    step('Reading avatar ' + str(image_file.relative_to(ROOT)))
    image = image_file.read_bytes()
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):
        raise SetupError(str(image_file.relative_to(ROOT)) + ' is not a PNG.')
    avatar = 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')
    payload['meta'] = dict(payload.get('meta') or {}, profile_image_url=avatar)
    payload['meta']['capabilities'] = dict(payload['meta'].get('capabilities') or {}, builtin_tools=False)

    filter_ids = list(payload['meta'].get('filterIds') or [])
    for filter_id in installed_filter_ids:
        if filter_id not in filter_ids:
            filter_ids.append(filter_id)
    payload['meta']['filterIds'] = filter_ids

    step('Saving identity, avatar, vitals, grounding, and continuity filters')
    result = api('/api/v1/models/model/update' if existing else '/api/v1/models/create', payload)
    if not result:
        raise SetupError('Open WebUI did not confirm the model update.')

    step('Verifying saved identity, avatar, and filters')
    saved = api(path)
    if not saved or saved.get('params', {}).get('system') != prompt:
        raise SetupError(cat + ' prompt could not be verified after saving.')
    if saved.get('meta', {}).get('profile_image_url') != payload['meta']['profile_image_url']:
        raise SetupError(cat + ' avatar could not be verified after saving.')
    if saved.get('meta', {}).get('capabilities', {}).get('builtin_tools') is not False:
        raise SetupError('Chat-only capability could not be verified after saving.')
    saved_filters = saved.get('meta', {}).get('filterIds', [])
    for filter_id in installed_filter_ids:
        if filter_id not in saved_filters:
            raise SetupError(filter_id + ' could not be attached to ' + cat + '.')

    print(cat + ' ' + persona + ' identity, orientation, avatar, vitals, grounding, and continuity memory saved for ' + model + '.')
    print('Hard-refresh the Den (Ctrl+Shift+R) and start a new chat; the browser can keep the old avatar cached.')
    print('The model now shows as ' + cat + '. If the picture is still missing, rerun: python3 scripts/setup-persona.py')
    print('Persistent memory starts from new conversations by default; old chats are not backfilled unless explicitly enabled.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f'Persona setup failed: HTTP {error.code}. Check your admin API key and API endpoint permissions.', file=sys.stderr)
        sys.exit(1)
    except SetupError as error:
        print('Persona setup failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as error:
        name = Path(error.filename).name if error.filename else 'required file'
        hint = 'Run ./scripts/set-token.sh.' if name == 'neco_token' else 'Run ./install.sh or restore the missing repo file.'
        print(f'Persona setup failed: missing {name}. {hint}', file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError:
        print('Persona setup failed: cannot reach Open WebUI. Check the container, OPENWEBUI_PORT/OPENWEBUI_URL, and /health.', file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print('Persona setup failed: Open WebUI request timed out. Wait for first boot to finish, then retry.', file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print('Persona setup failed: Open WebUI returned a non-JSON response. Check its URL/port and container logs.', file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print('Persona setup failed: a required file is not readable. Run as the user who installed the project.', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f'Persona setup failed: {type(error).__name__} at the step above. Check .env syntax and the Open WebUI API response format.', file=sys.stderr)
        sys.exit(1)
