"""Arranque de presentación: diagnóstico sin llamadas y canales explícitos."""
import argparse
import os

from . import doctor


def channels(session, telegram=None, delegated=None):
    comms = session.comms
    contacts = bool(comms.contacts.get('resources') or comms.contacts.get('roles'))
    configured = bool(os.environ.get('HR_API_KEY') and contacts and
                      (comms.voice_mode == 'web_call' or comms._allowed))
    simulated = session.comms_mode != 'happyrobot' or not configured
    failed = any(c.get('fell_back') for c in list(comms.calls.values()))
    tg = telegram.view() if telegram else {'status': 'off'}
    voice = 'simulada' if simulated or failed else 'real configurada; pendiente de confirmar'
    banner = 'voz simulada: sin conexión con la plataforma' if failed else 'voz simulada' if simulated else ''
    tg_failed = tg['status'] == 'error' or bool(tg.get('error'))
    if tg_failed:
        banner += (' · ' if banner else '') + 'Telegram sin conexión: continúa en /asistente'
    if delegated and delegated.workflow_status.view()['intake']['last_error']:
        banner += (' · ' if banner else '') + 'texto entendido en local'
    return {'happyrobot': 'simulado' if simulated else 'degradado' if failed else 'real configurado; pendiente de confirmar',
            'telegram': 'sin conexión' if tg_failed else 'real' if tg['status'] == 'on' else 'apagado' if tg['status'] == 'off' else 'conectando',
            'voice': voice, 'banner': banner}


def demo(argv=None):
    import uvicorn
    from .app import create_app
    parser = argparse.ArgumentParser(description='Presentación con diagnóstico y plan B local')
    parser.add_argument('--case', default=os.environ.get('MANDO_DEMO_CASE', 'demo-1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('MANDO_PORT', '8000')))
    parser.add_argument('--lan', action='store_true')
    args = parser.parse_args(argv)
    doctor.main(['--sin-red'])
    diagnosis = doctor.diagnosticar(sondear_red=False)
    # Telegram es un canal independiente: su ausencia no desactiva una voz configurada.
    missing_voice = [c for c in diagnosis.faltan_imprescindibles() if not c.clave.startswith('TELEGRAM')]
    mode = 'happyrobot' if os.environ.get('MANDO_COMMS') == 'happyrobot' and not missing_voice else 'sim'
    app = create_app(args.case, comms_mode=mode, autoplay=False, port=args.port, playbook='seed', local_params=False)
    status = channels(app.state.session, app.state.telegram, app.state.intake)
    print('\nPRESENTACIÓN · caso ' + args.case + ' · pausa inicial · simulación N=1')
    for name in ('happyrobot', 'telegram', 'voice'):
        print(f'{name.upper()}: {status[name].upper()}')
    print(f'Mando: http://127.0.0.1:{args.port}/ · acceso con token: /acceso')
    print('Espacio: iniciar · R: reiniciar escena · K: momento clave (simulado)')
    print('Doctor previo sin red: no certifica publicación, audio ni llamada real. Ver estado en el panel.')
    uvicorn.run(app, host='0.0.0.0' if args.lan else '127.0.0.1', port=args.port, log_level='warning')
