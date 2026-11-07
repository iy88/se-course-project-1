import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

root = Path(__file__).resolve().parent.parent
state_path = root / 'var/run/dev-services.json'
log_path = root / 'var/log/dev-services.log'
stop_path = root / 'var/run/dev-services.stop'

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
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA')
           if key in os.environ}
    if app_env_file is not None:
        env['APP_ENV_FILE'] = str(app_env_file)
    if python_unbuffered:
        env['PYTHONUNBUFFERED'] = '1'
    return env

def identity(pid):
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            code = wintypes.DWORD()
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
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

if len(sys.argv) != 2 or sys.argv[1] not in ('start', 'stop', 'restart', 'status', '_run'):
    print(('Usage: ./scripts/dev.sh {start|stop|restart|status}\n'
           'start runs in the background; use stop to stop all managed services.'))
    sys.exit(0 if sys.argv[1:] in ([], ['--help']) else 2)
action = sys.argv[1]
if action == 'restart':
    # 默认沿用正在托管的环境；显式 APP_ENV_FILE 可切换目标。
    previous_env = load_state().get('env_file')
    if 'APP_ENV_FILE' not in os.environ and previous_env:
        os.environ['APP_ENV_FILE'] = previous_env
    selected_env_path()  # 在停止前验证环境选择参数。
    script = str(Path(__file__).resolve())
    result = subprocess.run([sys.executable, script, 'stop'], check=False)
    if result.returncode:
        sys.exit(result.returncode)
    sys.exit(subprocess.run([sys.executable, script, 'start'], check=False).returncode)
if action == 'start':
    if alive(load_state().get('supervisor')):
        sys.exit('A managed start is already active. Use status or stop.')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start_token = uuid.uuid4().hex
    launch_env = dict(os.environ, DEV_SERVICES_START_TOKEN=start_token)
    with log_path.open('a') as log:
        child = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '_run'],
                                 cwd=root, env=launch_env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                                 start_new_session=sys.platform != 'win32')
    # Briefly wait for startup, but do not block the terminal on dependency installation.
    for _ in range(50):
        if child.poll() is not None:
            sys.exit(f'Start failed (exit {child.returncode}). See {log_path}')
        state = load_state()
        if state.get('start_token') == start_token and state['phase'] == 'running':
            print(f"Services started in the background (supervisor PID {state['supervisor']['pid']}).")
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
    stop_path.write_text(str(supervisor['pid']))
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
    if sys.platform == 'win32':
        import msvcrt
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit('A managed start is already active. Use status or stop.')
stop_path.unlink(missing_ok=True)
state = {'supervisor': {'pid': os.getpid(), 'started': identity(os.getpid())},
         'phase': 'preparing dependencies', 'services': {}, 'env_file': str(env_path),
         'start_token': os.environ.get('DEV_SERVICES_START_TOKEN')}

def save_state():
    temporary = state_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(state_path)

for tool in ('uv', 'node', 'npm'):
    if not shutil.which(tool):
        sys.exit(f'Missing {tool}. Follow README to install the development environment.')
if int(subprocess.check_output(['node', '-p', 'process.versions.node.split(".")[0]'])) < 22:
    sys.exit('Node.js 22 or later is required.')
# strictPort also prevents Vite from silently selecting a different port.
def check_port(host, port):
    with socket.socket() as sock:
        # 与服务监听 socket 一致，允许重启时复用 TIME_WAIT 地址。
        # 已有监听者仍会使 bind 失败。
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE if sys.platform == 'win32' else socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            sys.exit(f'Port {port} cannot be bound: {exc}')

children = []

def stop_all():
    if sys.platform == 'win32':
        for child in children:
            if child.poll() is None:
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            child.wait()
        return
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
    if stop_path.exists() and stop_path.read_text() == str(os.getpid()):
        raise KeyboardInterrupt
    if sys.platform == 'win32' and command[0] == 'npm':
        npm = shutil.which('npm.cmd')
        if npm is None:
            raise RuntimeError('Missing npm.cmd. Install Node.js and npm first.')
        command = [npm, *command[1:]]
    child = subprocess.Popen(command, cwd=root / folder,
                             stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr,
                             env=env if env is not None else child_environment(),
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                             start_new_session=sys.platform != 'win32')
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
            (f'{env_path} is missing. Copy backend/{example} manually '
             'and fill the appropriate values; this script never creates or copies env files.')
        )
    run(['uv', 'sync', '--frozen'], 'backend')
    for folder in ('frontend/admin', 'frontend/mobile'):
        if not (root / folder / ('node_modules/.bin/vite.cmd' if sys.platform == 'win32' else 'node_modules/.bin/vite')).exists():
            run(['npm', 'ci'], folder)
    backend_env = child_environment(app_env_file=env_path, python_unbuffered=True)
    python = str(root / 'backend' / ('.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python'))
    listeners = json.loads(subprocess.check_output(
        [python, '-c', 'import json; from app.core.config import load_settings; s=load_settings(); '
         'print(json.dumps([[s.api_host,s.api_port],[s.ws_host,s.ws_port]]))'],
        cwd=root / 'backend', env=backend_env,
    ))
    if len({port for _, port in listeners} | {5173, 5174}) != 4:
        raise RuntimeError('API, WebSocket and frontend ports must be distinct')
    for host, port in [*listeners, ('127.0.0.1', 5173), ('127.0.0.1', 5174)]:
        check_port(host, port)
    services = {}
    for name, command in (
        ('Scheduler', 'taskiq-scheduler'), ('Worker', 'taskiq-worker'),
        ('WS', 'serve-ws'), ('API', 'serve-api'),
    ):
        child = start([python, '-m', 'app.manage', command], 'backend', env=backend_env)
        services[name] = child
        state['services'][name] = {'pid': child.pid, 'started': identity(child.pid)}
        save_state()
    frontend_env = child_environment(app_env_file=env_path)
    admin = start(['npm', 'run', 'dev', '--', '--strictPort'], 'frontend/admin', env=frontend_env)
    state['services']['Admin'] = {'pid': admin.pid, 'started': identity(admin.pid)}
    save_state()
    mobile = start(['npm', 'run', 'dev', '--', '--strictPort'], 'frontend/mobile', env=frontend_env)
    state['services']['Mobile'] = {'pid': mobile.pid, 'started': identity(mobile.pid)}
    services.update(Admin=admin, Mobile=mobile)
    state['phase'] = 'running'
    save_state()
    print(('\nStarting services:\nMobile: http://localhost:5173\nAdmin: http://localhost:5174'
           f'\nAPI: http://127.0.0.1:{listeners[0][1]}/docs'
           f'\nWebSocket: ws://127.0.0.1:{listeners[1][1]}/ws'
           '\nUse ./scripts/dev.sh stop to stop all services.'), flush=True)
    while True:
        if stop_path.exists() and stop_path.read_text() == str(os.getpid()):
            break
        for name, child in services.items():
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
    stop_path.unlink(missing_ok=True)
