"""Apply pending updates before starting the desktop application."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from opti_update import UPDATE_DIR, app_running, apply_pending, check_for_update


def install_requirements(data):
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as stream:
        stream.write(data)
        path = Path(stream.name)
    try:
        python = Path(sys.executable).with_name('python.exe')
        result = subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(path)],
            capture_output=True, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('新版相依套件安裝失敗，保留目前版本。')
    finally:
        path.unlink(missing_ok=True)


def ready_to_update(directory=UPDATE_DIR, checks=120, interval=.25):
    """Allow a tray exit to finish before deciding whether startup may update files."""
    if not app_running():
        return True
    if not (Path(directory)/'pending.json').is_file():
        return False
    for _ in range(checks):
        time.sleep(interval)
        if not app_running():
            return True
    return False


def record_error(error):
    (UPDATE_DIR/'last-error.txt').write_text(str(error), encoding='utf-8')


def apply_waiting_update(root, apply_only=False):
    if not ready_to_update():
        if apply_only:
            record_error('OptiChat 尚未完全結束，更新將在下次啟動時再試。')
        return None
    check_error = None
    if not apply_only:
        try:
            # Always revalidate the R2 manifest at launch; no 24-hour cache gate.
            check_for_update(force=True)
        except Exception as error:
            # Local chat still works when R2 is unavailable. Retry on the next launch and in the app.
            check_error = error
    try:
        apply_pending(root, installer=install_requirements)
    except Exception as error:
        record_error(error)
        return False
    if check_error:
        record_error('R2 更新檢查失敗，稍後會重試：'+str(check_error))
    else:
        (UPDATE_DIR/'last-error.txt').unlink(missing_ok=True)
    return True


def main():
    root = Path(__file__).resolve().parent
    apply_only = '--apply-only' in sys.argv[1:]
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    # Serialize launchers; never replace files while the chat application is alive.
    import msvcrt
    with (UPDATE_DIR/'launch.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            update_result = apply_waiting_update(root, apply_only)
            if update_result is not None:
                if apply_only:
                    return
                from opti_setup import dependencies_ready, run_setup
                if not dependencies_ready() and not run_setup():
                    return
            elif apply_only:
                return
            subprocess.Popen([sys.executable, str(root/'opti_app.py')], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
            # Keep a second launcher from updating files before the new app claims its mutex.
            for _ in range(50):
                if app_running():
                    break
                time.sleep(.1)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
