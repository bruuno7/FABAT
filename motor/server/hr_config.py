"""URLs documentadas; su resolución no acredita publicación ni conectividad."""
import os
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

SLUGS = {'dispatch': 'slug-despacho-telefono', 'webcall': 'slug-despacho-webcall', 'voice': 'slug-ingesta-voz',
         'intake': 'slug-ingesta-texto', 'chat': 'slug-asistente-chat'}


def environment(env=None):
    return (os.environ if env is None else env).get('HR_ENV') or 'development'


def platform_base(env=None):
    return ((os.environ if env is None else env).get('HR_PLATFORM_BASE') or 'https://platform.eu.happyrobot.ai').rstrip('/')


def api_base(env=None):
    return ((os.environ if env is None else env).get('HR_API_BASE') or platform_base(env) + '/api/v2').rstrip('/')


def workflow_ids(env=None):
    e = os.environ if env is None else env
    return {k: e.get('HR_WORKFLOW_' + k.upper()) or slug for k, slug in SLUGS.items()}


def workflow_urls(env=None):
    e = os.environ if env is None else env
    stage = environment(e)
    prefix = '' if stage == 'production' else stage + '/'
    ids = workflow_ids(e)
    explicit = {'dispatch': 'HR_HOOK_DISPATCH', 'webcall': 'HR_DISPATCH_WEBCALL_URL',
                'voice': 'HR_WEBCALL_PUBLIC_URL', 'intake': 'HR_HOOK_INTAKE', 'chat': 'HR_CHAT_PUBLIC_URL'}
    # Patrón hooks de la documentación: confirmar copiando la URL del trigger en el editor.
    # El chat no tiene URL de despliegue documentada: copiar el enlace/widget real tras publicarlo.
    return {k: e.get(explicit[k] + '_' + stage.upper()) or e.get(explicit[k]) or
            (platform_base(e) + ('/hooks/' if k in ('dispatch', 'intake') else '/deployments/') + prefix + ids[k]
             if k != 'chat' else '') for k in ids}


def safe_url(url):
    """En diagnóstico público, sin credenciales de URL, query ni fragmento."""
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https'):
            return None
        return urlunsplit((p.scheme, p.netloc.rsplit('@', 1)[-1], p.path, '', ''))
    except ValueError:
        return None


class WorkflowStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {k: {'last_request': None, 'last_event': None, 'last_error': None, 'run_url': None} for k in SLUGS}

    def record(self, workflow, event, *, error=None, run_url=None):
        with self.lock:
            row = self.rows[workflow]
            if event in ('request', 'event'):
                row['last_' + event] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            if error is not None:
                row['last_error'] = error
            if run_url:
                row['run_url'] = safe_url(run_url)

    def view(self):
        urls, ids = workflow_urls(), workflow_ids()
        with self.lock:
            return {k: dict(v, slug=ids[k], url=safe_url(urls[k]), configured=bool(urls[k] and os.environ.get('HR_API_KEY') and
                         (os.environ.get('HR_SECRET') or os.environ.get('MANDO_HR_TOKEN')))) for k, v in self.rows.items()}
