import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
state_path = root / 'var/run/dev-services.json'
log_path = root / 'var/log/dev-services.log'

def selected_env_path():
    if 'APP_ENV_FILE' not in os.environ:
        return root / 'backend/.env.dev'
    raw = os.environ['APP_ENV_FILE'].strip()
    if not raw:
        sys.exit('APP_ENV_FILE must not be blank.')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        backend_relative = root / 'backend' / path
        repo_relative = root / path
        path = repo_relative if not backend_relative.is_file() and repo_relative.is_file() else backend_relative
    return path.resolve()

def child_environment(*, app_env_file=None, python_unbuffered=False):
    # Keep operating-system necessities, but never pass arbitrary shell settings
    # (including application, Vite, npm, or uv overrides) to managed processes.
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL')
           if key in os.environ}
    if app_env_file is not None:
        env['APP_ENV_FILE'] = str(app_env_file)
    if python_unbuffered:
        env['PYTHONUNBUFFERED'] = '1'
    return env

def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=,stat='],
                            capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    if result.returncode or not value or value.split()[-1].startswith('Z'):
        return None
    return ' '.join(value.split()[:-1])

def alive(record):
    return bool(record and record.get('started') and
                identity(record['pid']) == record['started'])

def load_state():
    try:
        return json.loads(state_path.read_text())
    except FileNotFoundError:
        return {}

def inspect_status():
    state = load_state()
    if not alive(state.get('supervisor')):
        print('Stopped (no active managed supervisor).')
        return 1
    print(f"Supervisor: running (PID {state['supervisor']['pid']}); {state['phase']}")
    if state.get('env_file'):
        print(f"Environment file: {state['env_file']}")
    for name, record in state.get('services', {}).items():
        status = 'running' if alive(record) else 'exited'
        print(f"{name}: {status} (PID {record['pid']})")
    print(f'Logs: {log_path}')
    print('Process status only; this does not verify application health.')
    return 0 if state['phase'] == 'running' and all(
        alive(r) for r in state['services'].values()) else 1

if len(sys.argv) != 2 or sys.argv[1] not in ('start', 'stop', 'status', '_run'):
    print('Usage: ./scripts/dev.sh {start|stop|status}\n'
          'start runs in the background; use stop to stop all managed services.')
    sys.exit(0 if sys.argv[1:] in ([], ['--help']) else 2)
action = sys.argv[1]
if action == 'start':
    if alive(load_state().get('supervisor')):
        sys.exit('A managed start is already active. Use status or stop.')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a') as log:
        child = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '_run'],
                                 cwd=root, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
    # Briefly wait for startup, but do not block the terminal on dependency installation.
    for _ in range(50):
        if child.poll() is not None:
            sys.exit(f'Start failed (exit {child.returncode}). See {log_path}')
        state = load_state()
        if state.get('supervisor', {}).get('pid') == child.pid and state['phase'] == 'running':
            print(f'Services started in the background (supervisor PID {child.pid}).')
            print(f'Logs: {log_path}')
            sys.exit(0)
        time.sleep(0.1)
    print(f'Background startup in progress (PID {child.pid}). Use status to check progress.')
    print(f'Logs: {log_path}')
    sys.exit(0)
if action == 'status':
    sys.exit(inspect_status())
if action == 'stop':
    state = load_state()
    supervisor = state.get('supervisor')
    if supervisor is None or not alive(supervisor):
        print('No active managed supervisor. No processes were signalled.')
        sys.exit(0)
    os.kill(supervisor['pid'], signal.SIGTERM)
    for _ in range(100):
        if not alive(supervisor):
            print('Managed services stopped.')
            sys.exit(0)
        time.sleep(0.1)
    sys.exit('Shutdown is still in progress. Check status and the log file.')
env_path = selected_env_path()
state_path.parent.mkdir(parents=True, exist_ok=True)
lock = (state_path.parent / 'dev-services.lock').open('a')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit('A managed start is already active. Use status or stop.')
state = {'supervisor': {'pid': os.getpid(), 'started': identity(os.getpid())},
         'phase': 'preparing dependencies', 'services': {}, 'env_file': str(env_path)}

def save_state():
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(state_path)

for tool in ('uv', 'node', 'npm'):
    if not shutil.which(tool):
        sys.exit(f'Missing {tool}. Follow README to install the development environment.')
if int(subprocess.check_output(['node', '-p', 'process.versions.node.split(".")[0]'])) < 22:
    sys.exit('Node.js 22 or later is required.')
# Check all ports before setup; strictPort also prevents automatic port changes.
for port in (8000, 5173, 5174):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            sys.exit(f'Port {port} is already in use. Stop the existing service first.')

children = []

def stop_all():
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(p.poll() is None for p in children):
        time.sleep(0.1)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()

def interrupted(signum, frame):
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)

def start(command, folder, env=None):
    child = subprocess.Popen(command, cwd=root / folder,
                             env=env if env is not None else child_environment(),
                             start_new_session=True)
    children.append(child)
    return child

def run(command, folder):
    child = start(command, folder)
    result = child.wait()
    children.remove(child)
    if result:
        raise RuntimeError(f'{folder}: command failed: {" ".join(command)} (exit {result})')

try:
    save_state()
    if not env_path.is_file():
        example = '.env.prod.example' if env_path.name == '.env.prod' else '.env.dev.example'
        raise RuntimeError(
            f'{env_path} is missing. Copy backend/{example} manually '
            'and fill the appropriate values; this script never creates or copies env files.'
        )
    run(['uv', 'sync', '--frozen'], 'backend')
    for folder in ('frontend/admin', 'frontend/mobile'):
        if not (root / folder / 'node_modules/.bin/vite').exists():
            run(['npm', 'ci'], folder)
    backend_env = child_environment(app_env_file=env_path, python_unbuffered=True)
    backend = start(['.venv/bin/python', '-m', 'app.manage', 'serve',
                     '--host', '127.0.0.1', '--port', '8000'], 'backend', env=backend_env)
    state['services']['Backend'] = {'pid': backend.pid, 'started': identity(backend.pid)}
    save_state()
    frontend_env = child_environment(app_env_file=env_path)
    admin = start(['npm', 'run', 'dev', '--', '--strictPort'], 'frontend/admin', env=frontend_env)
    state['services']['Admin'] = {'pid': admin.pid, 'started': identity(admin.pid)}
    save_state()
    mobile = start(['npm', 'run', 'dev', '--', '--strictPort'], 'frontend/mobile', env=frontend_env)
    state['services']['Mobile'] = {'pid': mobile.pid, 'started': identity(mobile.pid)}
    state['phase'] = 'running'
    save_state()
    print('\nStarting services:\nMobile: http://localhost:5173\nAdmin: http://localhost:5174'
          '\nBackend: http://127.0.0.1:8000/docs\nUse ./scripts/dev.sh stop to stop all services.', flush=True)
    while True:
        for name, child in (('Backend', backend), ('Admin', admin), ('Mobile', mobile)):
            if child.poll() is not None:
                raise RuntimeError(f'{name} exited ({child.returncode}); stopping the other services.')
        time.sleep(0.3)
except KeyboardInterrupt:
    print('\nStopping services...', flush=True)
except Exception as exc:  # noqa: BLE001 - CLI 顶层统一转退出码，保留 traceback 以外的干净提示
    print(str(exc), file=sys.stderr)
    sys.exit(1)
finally:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    stop_all()
    state_path.unlink(missing_ok=True)
